import { Database, open } from "sqlite";
import sqlite3 from "sqlite3";
import { promises as fs } from "fs";
import * as path from "path";

import {
  LoopRun,
  CostProjection,
  Severity,
  RunId,
  RuleResult,
} from "../types";

/**
 * Minimal representation of a future run used for cost estimation.
 */
export interface RunTemplate {
  /** Identifier of the LLM provider (e.g., grok, claude) */
  provider: string;
  /** Expected duration in milliseconds (optional, used for weighting) */
  durationMs?: number;
}

/**
 * Estimates token usage cost for upcoming runs based on historic data and
 * LLM pricing tables. Persists run history in a SQLite database and keeps an
 * in‑memory sliding window for fast calculations.
 */
export class CostEstimator {
  /** Path to the SQLite database file */
  private readonly dbPath: string;
  /** SQLite database instance */
  private db!: Database<sqlite3.Database, sqlite3.Statement>;
  /** In‑memory sliding window of recent runs (runId → LoopRun) */
  private recentRuns: Map<RunId, LoopRun> = new Map();
  /** Maximum number of runs to retain in the sliding window */
  private readonly windowSize: number;
  /** Pricing table: provider → $ per 1 M tokens */
  private pricing: Record<string, number> = {};
  /** Simple async mutex to serialize DB access */
  private mutex: Promise<void> = Promise.resolve();

  /**
   * Creates a CostEstimator.
   * @param options Optional configuration.
   */
  constructor(options?: { dbPath?: string; windowSize?: number }) {
    this.dbPath = options?.dbPath ?? path.resolve(".loopwatch_run_history.db");
    this.windowSize = options?.windowSize ?? 1000;
  }

  /**
   * Initializes the SQLite database and ensures the runs table exists.
   */
  async init(): Promise<void> {
    console.info(`[INFO] Initialising CostEstimator DB at ${this.dbPath}`);
    await this.ensureDirectory(path.dirname(this.dbPath));
    this.db = await open({
      filename: this.dbPath,
      driver: sqlite3.Database,
    });
    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS runs (
        runId TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        provider TEXT NOT NULL,
        tokensUsed INTEGER NOT NULL,
        durationMs INTEGER NOT NULL,
        pattern TEXT NOT NULL
      )
    `);
    console.info("[INFO] CostEstimator DB initialised");
  }

  /**
   * Updates internal history with a batch of LoopRun objects.
   * Persists runs to SQLite and maintains the in‑memory sliding window.
   * @param runs Array of LoopRun entries.
   */
  async updateHistory(runs: LoopRun[]): Promise<void> {
    if (runs.length === 0) {
      return;
    }
    console.info(`[INFO] Updating history with ${runs.length} run(s)`);
    await this.withLock(async () => {
      const insertStmt = await this.db.prepare(`
        INSERT OR REPLACE INTO runs
        (runId, timestamp, provider, tokensUsed, durationMs, pattern)
        VALUES (?, ?, ?, ?, ?, ?)
      `);
      try {
        await this.db.exec("BEGIN TRANSACTION");
        for (const run of runs) {
          await insertStmt.run(
            run.runId,
            run.timestamp,
            run.provider,
            run.tokensUsed,
            run.durationMs,
            run.pattern,
          );
          this.recentRuns.set(run.runId, run);
          if (this.recentRuns.size > this.windowSize) {
            // Remove oldest entry (by insertion order)
            const oldestKey = this.recentRuns.keys().next().value;
            this.recentRuns.delete(oldestKey);
          }
        }
        await this.db.exec("COMMIT");
        console.info("[INFO] History update committed");
      } catch (err) {
        await this.db.exec("ROLLBACK");
        console.error(
          `[ERROR] Failed to update history, transaction rolled back: ${
            err instanceof Error ? err.message : err
          }`,
        );
        throw err;
      } finally {
        await insertStmt.finalize();
      }
    });
  }

  /**
   * Estimates token usage and cost for a future run based on historic data.
   * Returns a CostProjection with confidence derived from variance.
   * @param template Description of the upcoming run.
   */
  async estimateNextRun(template: RunTemplate): Promise<CostProjection> {
    console.info(
      `[INFO] Estimating next run for provider ${template.provider}`,
    );
    const providerRuns = Array.from(this.recentRuns.values()).filter(
      (run) => run.provider === template.provider,
    );

    if (providerRuns.length === 0) {
      console.warn(
        `[WARN] No historic data for provider ${template.provider}, returning zero estimate`,
      );
      return {
        estimatedTokens: 0,
        estimatedCostUsd: 0,
        confidence: 0,
      };
    }

    const tokenValues = providerRuns.map((run) => run.tokensUsed);
    const avgTokens =
      tokenValues.reduce((sum, v) => sum + v, 0) / tokenValues.length;
    const variance =
      tokenValues.reduce((sum, v) => sum + (v - avgTokens) ** 2, 0) /
      tokenValues.length;
    const stdDev = Math.sqrt(variance);
    const confidence = 1 - stdDev / (avgTokens || 1); // simple heuristic

    const pricePerMToken = this.pricing[template.provider] ?? 0;
    const estimatedCostUsd = (avgTokens / 1_000_000) * pricePerMToken;

    console.info(
      `[INFO] Projection: ${avgTokens.toFixed(
        2,
      )} tokens → $${estimatedCostUsd.toFixed(4)} (confidence ${confidence.toFixed(
        2,
      )})`,
    );

    return {
      estimatedTokens: Math.round(avgTokens),
      estimatedCostUsd,
      confidence: Math.max(0, Math.min(1, confidence)),
    };
  }

  /**
   * Updates the pricing table for a given LLM provider.
   * @param provider Provider identifier.
   * @param pricePerMToken USD price per 1 M tokens.
   */
  setPricing(provider: string, pricePerMToken: number): void {
    console.info(
      `[INFO] Setting pricing for provider ${provider}: $${pricePerMToken} per 1M tokens`,
    );
    if (pricePerMToken < 0) {
      console.error("[FATAL] Negative pricing is invalid");
      process.exit(1);
    }
    this.pricing[provider] = pricePerMToken;
  }

  /**
   * Gracefully closes the SQLite connection.
   */
  async shutdown(): Promise<void> {
    console.info("[INFO] Shutting down CostEstimator");
    await this.withLock(async () => {
      await this.db.close();
    });
    console.info("[INFO] CostEstimator shutdown complete");
  }

  /**
   * Executes a function while holding the internal mutex to serialize access.
   * @param fn Async function to execute.
   */
  private async withLock(fn: () => Promise<void>): Promise<void> {
    const release = this.mutex;
    let resolveLock: () => void;
    this.mutex = new Promise<void>((res) => (resolveLock = res));
    await release;
    try {
      await fn();
    } finally {
      resolveLock!();
    }
  }

  /**
   * Ensures a directory exists, creating it recursively if needed.
   * @param dirPath Directory path.
   */
  private async ensureDirectory(dirPath: string): Promise<void> {
    try {
      await fs.mkdir(dirPath, { recursive: true });
    } catch (err) {
      console.error(
        `[ERROR] Failed to create directory ${dirPath}: ${
          err instanceof Error ? err.message : err
        }`,
      );
      throw err;
    }
  }
}