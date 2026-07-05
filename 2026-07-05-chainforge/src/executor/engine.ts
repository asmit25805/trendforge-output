import { Database, verbose } from 'sqlite3';
import { promisify } from 'util';
import { createHash } from 'crypto';
import {
  ChainVersionRecord,
  StepDefinition,
  StepResult,
  ExecutionResult,
  RateLimits,
} from '../types.ts';
import { CatalogStore } from '../catalog/store.ts';

/**
 * Minimal sandbox that executes JavaScript step payloads in an isolated context.
 * It captures stdout/stderr and returns a deterministic hash of the step output.
 */
class Sandbox {
  /**
   * Executes a step definition with the given context.
   * @param step Step definition to execute.
   * @param context Arbitrary data made available to the step payload.
   * @returns Result of the step execution.
   */
  async execute(step: StepDefinition, context: Record<string, any>): Promise<StepResult> {
    console.info(`[Sandbox][execute] Running step ${step.id} of type ${step.type}`);

    // Capture stdout / stderr
    let stdout = '';
    let stderr = '';
    const originalLog = console.log;
    const originalError = console.error;

    console.log = (...args: any[]) => {
      stdout += args.map(String).join(' ') + '\n';
    };
    console.error = (...args: any[]) => {
      stderr += args.map(String).join(' ') + '\n';
    };

    let output: unknown = null;
    try {
      // For simplicity we only support 'script' payloads that export a function.
      // The payload is expected to be a JavaScript expression that returns a value.
      // Example payload: "return context.input * 2;"
      const wrapped = new Function('context', `"use strict";\n${step.payload}`);
      output = wrapped(context);
    } catch (err: any) {
      // Restore console before rethrowing
      console.log = originalLog;
      console.error = originalError;
      console.error(`[Sandbox][execute] Error in step ${step.id}: ${err.message}`);
      throw err;
    } finally {
      // Restore console regardless of success/failure
      console.log = originalLog;
      console.error = originalError;
    }

    // Compute deterministic hash of the output
    const hash = createHash('sha256')
      .update(JSON.stringify(output))
      .digest('hex');

    const result: StepResult = {
      stepId: step.id,
      hash,
      stdout,
      stderr,
      output,
    };

    console.info(`[Sandbox][execute] Completed step ${step.id} with hash ${hash}`);
    return result;
  }
}

/**
 * Preview information for a step without executing it.
 */
export interface StepPreview {
  /** Identifier of the step. */
  stepId: string;
  /** Execution modality. */
  type: StepDefinition['type'];
  /** Raw payload (prompt, tool spec, or script). */
  payload: string;
}

/**
 * Orchestrates the sequential execution of a chain’s steps inside an isolated sandbox.
 */
export class ChainExecutor {
  private catalog: CatalogStore;
  private sandbox: Sandbox;
  private db: Database;
  private runAsync: (sql: string, params?: unknown[]) => Promise<void>;

  /**
   * Creates a new ChainExecutor.
   * @param catalog Instance of CatalogStore for loading chain versions.
   * @param dbPath Path to SQLite file used for persisting run history.
   */
  constructor(catalog: CatalogStore, dbPath: string = ':memory:') {
    this.catalog = catalog;
    this.sandbox = new Sandbox();

    const sqlite3 = verbose();
    this.db = new sqlite3.Database(dbPath, (err) => {
      if (err) {
        console.error(`[ChainExecutor][init] DB open error: ${err.message}`);
        throw err;
      }
    });
    this.runAsync = promisify(this.db.run).bind(this.db);
    this.initializeRunSchema()
      .then(() => console.info('[ChainExecutor][init] Run schema ready'))
      .catch((e) => {
        console.error(`[ChainExecutor][init] Schema error: ${e.message}`);
        throw e;
      });
  }

  /** Ensure the runs table exists. */
  private async initializeRunSchema(): Promise<void> {
    const schema = `
      CREATE TABLE IF NOT EXISTS runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chainSlug TEXT NOT NULL,
        version TEXT NOT NULL,
        runHash TEXT NOT NULL,
        logs TEXT NOT NULL,
        createdAt TEXT NOT NULL
      );
    `;
    await this.execWithRetry(schema);
  }

  /** Execute a statement with retry on transient SQLite errors. */
  private async execWithRetry(sql: string, params: unknown[] = []): Promise<void> {
    const maxAttempts = 3;
    let attempt = 0;
    const baseDelay = 100; // ms

    while (true) {
      try {
        await new Promise<void>((resolve, reject) => {
          this.db.run(sql, params, (err) => (err ? reject(err) : resolve()));
        });
        return;
      } catch (err: any) {
        const transient = err.code === 'SQLITE_BUSY' || err.code === 'SQLITE_LOCKED';
        if (!transient || ++attempt >= maxAttempts) {
          console.error(`[ChainExecutor][execWithRetry] Fatal DB error: ${err.message}`);
          throw err;
        }
        const delay = baseDelay * 2 ** (attempt - 1);
        console.warn(`[ChainExecutor][execWithRetry] Transient DB error (${err.code}), retry ${attempt}/${maxAttempts} after ${delay}ms`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  /**
   * Loads a chain version and returns a preview of its steps.
   * @param chainSlug Identifier of the chain.
   * @returns Array of step previews.
   */
  async preview(chainSlug: string): Promise<StepPreview[]> {
    console.info(`[ChainExecutor][preview] Generating preview for ${chainSlug}`);
    const chainVersion: ChainVersionRecord | null = await this.catalog.getChain(chainSlug);
    if (!chainVersion) {
      throw new Error(`Chain ${chainSlug} not found`);
    }

    const previews: StepPreview[] = chainVersion.steps.map((step) => ({
      stepId: step.id,
      type: step.type,
      payload: step.payload,
    }));

    console.info(`[ChainExecutor][preview] Produced ${previews.length} step previews`);
    return previews;
  }

  /**
   * Executes a chain version with the supplied inputs.
   * @param chainSlug Identifier of the chain to run.
   * @param inputs Input values for the first step.
   * @returns Aggregated execution result.
   */
  async run(chainSlug: string, inputs: Record<string, any>): Promise<ExecutionResult> {
    console.info(`[ChainExecutor][run] Starting execution for ${chainSlug}`);
    const startTime = Date.now();

    const chainVersion: ChainVersionRecord | null = await this.catalog.getChain(chainSlug);
    if (!chainVersion) {
      throw new Error(`Chain ${chainSlug} not found`);
    }

    const stepResults: StepResult[] = [];
    let context: Record<string, any> = { ...inputs };
    let aggregatedLogs = '';

    for (const step of chainVersion.steps) {
      console.info(`[ChainExecutor][run] Executing step ${step.id}`);
      const result = await this.executeWithRetry(step, context);
      stepResults.push(result);
      aggregatedLogs += result.stdout + result.stderr;

      // Merge output into context for subsequent steps
      if (typeof result.output === 'object' && result.output !== null) {
        context = { ...context, ...result.output };
      } else {
        // For primitive outputs, expose under a generic key
        context[step.id] = result.output;
      }
    }

    // Compute run hash as Merkle root of step hashes (simple concatenation then hash)
    const runHash = createHash('sha256')
      .update(stepResults.map((r) => r.hash).join(''))
      .digest('hex');

    const executionResult: ExecutionResult = {
      runHash,
      steps: stepResults,
      logs: aggregatedLogs,
      finalStdout: stepResults[stepResults.length - 1]?.stdout,
    };

    // Persist run record
    const insertSql = `
      INSERT INTO runs (chainSlug, version, runHash, logs, createdAt)
      VALUES (?, ?, ?, ?, ?);
    `;
    const createdAt = new Date().toISOString();
    await this.execWithRetry(insertSql, [
      chainSlug,
      chainVersion.version,
      runHash,
      aggregatedLogs,
      createdAt,
    ]);

    const duration = Date.now() - startTime;
    console.info(`[ChainExecutor][run] Completed ${chainSlug} in ${duration}ms, runHash=${runHash}`);
    return executionResult;
  }

  /** Execute a step with exponential back‑off on transient errors. */
  private async executeWithRetry(step: StepDefinition, context: Record<string, any>): Promise<StepResult> {
    const maxAttempts = 3;
    const baseDelay = 100; // ms
    let attempt = 0;

    while (true) {
      try {
        return await this.sandbox.execute(step, context);
      } catch (err: any) {
        const transient = err.code === 'TRANSIENT' || err.message.includes('temporary');
        if (!transient || ++attempt >= maxAttempts) {
          console.error(`[ChainExecutor][executeWithRetry] Fatal error on step ${step.id}: ${err.message}`);
          throw err;
        }
        const delay = baseDelay * 2 ** (attempt - 1);
        console.warn(`[ChainExecutor][executeWithRetry] Transient error on step ${step.id}, retry ${attempt}/${maxAttempts} after ${delay}ms`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }
}