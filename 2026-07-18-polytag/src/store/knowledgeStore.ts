import { join } from 'path';
import { randomUUID } from 'crypto';
import sqlite3 from 'sqlite3';
import { open, Database } from 'sqlite';
import {
  KnowledgeRef,
  KnowledgeEntry,
  AuditRecord,
  TaskDefinition,
  ExecutionContext,
  PolicyDecision,
  PolicyRule,
  RuntimeAdapter,
  TargetRef,
  MessageContent,
  ApprovalPayload,
} from '../types.ts';

/**
 * KnowledgeStore provides a versioned, channel‑scoped fact store.
 * Facts are stored immutably; each insertion bumps the version.
 */
export class KnowledgeStore {
  private static instance: KnowledgeStore;
  private db!: Database<sqlite3.Database, sqlite3.Statement>;

  private constructor() {}

  /** Returns the singleton instance, initializing the SQLite DB on first use. */
  public static async getInstance(): Promise<KnowledgeStore> {
    if (!KnowledgeStore.instance) {
      KnowledgeStore.instance = new KnowledgeStore();
      await KnowledgeStore.instance.init();
    }
    return KnowledgeStore.instance;
  }

  /** Opens (or creates) the SQLite file and ensures the schema exists. */
  private async init(): Promise<void> {
    const dbPath = join(process.cwd(), 'knowledge_store.sqlite');
    this.db = await open({
      filename: dbPath,
      driver: sqlite3.Database,
    });
    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS facts (
        id TEXT PRIMARY KEY,
        projectId TEXT NOT NULL,
        channelId TEXT NOT NULL,
        version INTEGER NOT NULL,
        fact TEXT NOT NULL,
        authorId TEXT NOT NULL,
        createdAt INTEGER NOT NULL
      );
    `);
  }

  /**
   * Retrieves the latest facts for a given project/channel.
   * Returns an empty array if none exist.
   */
  public async getFacts(ref: KnowledgeRef): Promise<KnowledgeEntry[]> {
    console.log(
      `KnowledgeStore: fetching facts for project ${ref.projectId}, channel ${ref.channelId}`,
    );
    const rows = await this.db.all<KnowledgeEntry[]>(
      `
      SELECT * FROM facts
      WHERE projectId = ? AND channelId = ?
      ORDER BY version ASC;
    `,
      ref.projectId,
      ref.channelId,
    );
    return rows;
  }

  /**
   * Appends a new immutable fact. The version is automatically set to
   * (max existing version + 1) for the channel.
   */
  public async appendFact(entry: Omit<KnowledgeEntry, 'id' | 'version' | 'createdAt'>): Promise<KnowledgeEntry> {
    console.log(
      `KnowledgeStore: appending fact to project ${entry.projectId}, channel ${entry.channelId}`,
    );
    const maxRow = await this.db.get<{ version: number } | undefined>(
      `
      SELECT MAX(version) as version FROM facts
      WHERE projectId = ? AND channelId = ?;
    `,
      entry.projectId,
      entry.channelId,
    );
    const nextVersion = (maxRow?.version ?? 0) + 1;
    const now = Date.now();
    const fact: KnowledgeEntry = {
      id: randomUUID(),
      projectId: entry.projectId,
      channelId: entry.channelId,
      version: nextVersion,
      fact: entry.fact,
      authorId: entry.authorId,
      createdAt: now,
    };
    await this.db.run(
      `
      INSERT INTO facts (id, projectId, channelId, version, fact, authorId, createdAt)
      VALUES (?, ?, ?, ?, ?, ?, ?);
    `,
      fact.id,
      fact.projectId,
      fact.channelId,
      fact.version,
      fact.fact,
      fact.authorId,
      fact.createdAt,
    );
    return fact;
  }

  /**
   * Returns a snapshot of facts up to a specific version.
   * If version is 0, returns the latest snapshot.
   */
  public async snapshot(ref: KnowledgeRef, version: number): Promise<KnowledgeEntry[]> {
    console.log(
      `KnowledgeStore: creating snapshot for project ${ref.projectId}, channel ${ref.channelId}, version ${version}`,
    );
    const targetVersion = version > 0 ? version : await this.getLatestVersion(ref);
    const rows = await this.db.all<KnowledgeEntry[]>(
      `
      SELECT * FROM facts
      WHERE projectId = ? AND channelId = ? AND version <= ?
      ORDER BY version ASC;
    `,
      ref.projectId,
      ref.channelId,
      targetVersion,
    );
    return rows;
  }

  /** Helper to obtain the highest version number for a channel. */
  private async getLatestVersion(ref: KnowledgeRef): Promise<number> {
    const row = await this.db.get<{ version: number } | undefined>(
      `
      SELECT MAX(version) as version FROM facts
      WHERE projectId = ? AND channelId = ?;
    `,
      ref.projectId,
      ref.channelId,
    );
    return row?.version ?? 0;
  }
}

/**
 * AuditLogger persists immutable run records.
 * It re‑uses the same SQLite file but a separate table.
 */
export class AuditLogger {
  private static instance: AuditLogger;
  private db!: Database<sqlite3.Database, sqlite3.Statement>;

  private constructor() {}

  public static async getInstance(): Promise<AuditLogger> {
    if (!AuditLogger.instance) {
      AuditLogger.instance = new AuditLogger();
      await AuditLogger.instance.init();
    }
    return AuditLogger.instance;
  }

  private async init(): Promise<void> {
    const dbPath = join(process.cwd(), 'audit_logger.sqlite');
    this.db = await open({
      filename: dbPath,
      driver: sqlite3.Database,
    });
    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS audit (
        runId TEXT PRIMARY KEY,
        runtimeId TEXT,
        startTime INTEGER,
        endTime INTEGER,
        status TEXT,
        output TEXT,
        errorMessage TEXT,
        approvalId TEXT
      );
    `);
  }

  /** Persists a new audit record. */
  public async logRun(record: AuditRecord): Promise<void> {
    console.log(`AuditLogger: logging run ${record.runId} with status ${record.status}`);
    await this.db.run(
      `
      INSERT INTO audit (runId, runtimeId, startTime, endTime, status, output, errorMessage, approvalId)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    `,
      record.runId,
      record.runtimeId,
      record.startTime,
      record.endTime,
      record.status,
      record.output,
      record.errorMessage,
      record.approvalId,
    );
  }

  /** Retrieves a stored record for the given runId, if any. */
  public async getRecord(runId: string): Promise<AuditRecord | undefined> {
    console.log(`AuditLogger: fetching record for run ${runId}`);
    const row = await this.db.get<AuditRecord>(
      `SELECT * FROM audit WHERE runId = ?`,
      runId,
    );
    return row;
  }

  /** Query helper for admin UI – not required for core logic. */
  public async queryRuns(filter: Partial<AuditRecord>): Promise<AuditRecord[]> {
    console.log('AuditLogger: querying runs with filter', filter);
    const conditions: string[] = [];
    const params: any[] = [];
    if (filter.runtimeId) {
      conditions.push('runtimeId = ?');
      params.push(filter.runtimeId);
    }
    if (filter.status) {
      conditions.push('status = ?');
      params.push(filter.status);
    }
    const whereClause = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const rows = await this.db.all<AuditRecord[]>(`SELECT * FROM audit ${whereClause}`, ...params);
    return rows;
  }
}

/**
 * PolicyEngine evaluates policy rules before a task is dispatched.
 * Rules can be registered at runtime; each rule receives the task and context.
 */
export class PolicyEngine {
  private rules: PolicyRule[] = [];

  /** Registers a new policy rule. */
  public registerRule(rule: PolicyRule): void {
    console.log('PolicyEngine: registering new rule');
    this.rules.push(rule);
  }

  /**
   * Evaluates all registered rules and returns a consolidated decision.
   * The first rule that denies or requires approval short‑circuits evaluation.
   */
  public evaluate(task: TaskDefinition, context: ExecutionContext): PolicyDecision {
    console.log(`PolicyEngine: evaluating task ${task.taskId}`);
    for (const rule of this.rules) {
      const decision = rule.evaluate(task, context);
      if (!decision.allow) {
        console.log(`PolicyEngine: rule denied task ${task.taskId} – ${decision.reason}`);
        return decision;
      }
      if (decision.requiresApproval) {
        console.log(`PolicyEngine: rule requires approval for task ${task.taskId} – ${decision.reason}`);
        return decision;
      }
    }
    // Default allow if no rule objects.
    return { allow: true, requiresApproval: false, reason: 'All checks passed' };
  }
}

/**
 * TaskRouter selects the cheapest runtime capable of satisfying a task.
 * It assumes each RuntimeAdapter may expose a `cost` numeric property.
 */
export class TaskRouter {
  /**
   * Selects a runtime that supports all required capabilities.
   * The first matching runtime is chosen; callers may order candidates by cost.
   */
  public selectRuntime(task: TaskDefinition, candidates: RuntimeAdapter[]): RuntimeAdapter {
    console.log(`TaskRouter: selecting runtime for task ${task.taskId}`);
    for (const runtime of candidates) {
      const missing = task.requiredCapabilities.filter((cap) => !runtime.supportsCapability(cap));
      if (missing.length === 0) {
        console.log(`TaskRouter: selected runtime ${(<any>runtime).name ?? 'unknown'}`);
        return runtime;
      }
    }
    throw new Error(`No runtime satisfies required capabilities: ${task.requiredCapabilities.join(', ')}`);
  }

  /**
   * Returns a runtime that is read‑only (i.e., does not require write capabilities).
   * Used as a fallback when write‑capable runtimes are unavailable.
   */
  public fallbackToReadOnly(task: TaskDefinition, candidates: RuntimeAdapter[]): RuntimeAdapter {
    console.log(`TaskRouter: falling back to read‑only runtime for task ${task.taskId}`);
    const readOnlyTask = { ...task, requiredCapabilities: task.requiredCapabilities.filter((c) => c !== 'file_write') };
    return this.selectRuntime(readOnlyTask, candidates);
  }
}

/**
 * Export a ready‑to‑use singleton for convenience.
 */
export const knowledgeStore = await KnowledgeStore.getInstance();
export const auditLogger = await AuditLogger.getInstance();
export const policyEngine = new PolicyEngine();
export const taskRouter = new TaskRouter();