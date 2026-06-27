import { ConfigLoader } from "../src/config/loader";
import { LoopMonitor } from "../src/core/engine";
import { LoopRun, LoopwatchConfig } from "../src/types";
import { promises as fs } from "fs";
import * as path from "path";
import { open, Database } from "sqlite";
import sqlite3 from "sqlite3";
import { EventEmitter } from "events";
import { randomUUID } from "crypto";

/**
 * Represents a periodic task that generates a synthetic LoopRun and writes it
 * to a log file watched by LoopMonitor.
 */
class Task {
  /** Human‑readable name of the task. */
  readonly name: string;
  /** Interval in milliseconds between executions. */
  readonly intervalMs: number;
  /** Function that performs the task work. */
  readonly action: () => Promise<void>;

  /**
   * @param name Identifier for logging.
   * @param intervalMs Execution frequency.
   * @param action Async work to run each tick.
   */
  constructor(name: string, intervalMs: number, action: () => Promise<void>) {
    this.name = name;
    this.intervalMs = intervalMs;
    this.action = action;
  }

  /** Starts the periodic execution; returns a handle to stop it. */
  start(): NodeJS.Timer {
    console.log(`[Task:${this.name}] Starting with interval ${this.intervalMs} ms`);
    const timer = setInterval(() => {
      console.log(`[Task:${this.name}] Triggered`);
      this.action().catch((err) => {
        console.error(`[Task:${this.name}] Unexpected error:`, err);
      });
    }, this.intervalMs);
    return timer;
  }
}

/**
 * Simple SQLite wrapper that stores LoopRun records for later inspection.
 */
class RunHistory {
  private db!: Database;

  /** Opens (or creates) the SQLite database file. */
  async init(dbPath: string): Promise<void> {
    console.log(`[RunHistory] Initialising SQLite DB at ${dbPath}`);
    this.db = await open({
      filename: dbPath,
      driver: sqlite3.Database,
    });
    await this.db.exec(`
      CREATE TABLE IF NOT EXISTS runs (
        runId TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        pattern TEXT NOT NULL,
        durationMs INTEGER NOT NULL,
        tokensUsed INTEGER NOT NULL,
        provider TEXT NOT NULL,
        outcome TEXT NOT NULL,
        metadata TEXT
      )
    `);
  }

  /** Persists a LoopRun record. */
  async insert(run: LoopRun): Promise<void> {
    console.log(`[RunHistory] Inserting run ${run.runId}`);
    const stmt = await this.db.prepare(`
      INSERT OR REPLACE INTO runs
      (runId, timestamp, pattern, durationMs, tokensUsed, provider, outcome, metadata)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    await stmt.run(
      run.runId,
      run.timestamp,
      run.pattern,
      run.durationMs,
      run.tokensUsed,
      run.provider,
      run.outcome,
      JSON.stringify(run.metadata)
    );
    await stmt.finalize();
  }

  /** Closes the underlying DB connection. */
  async close(): Promise<void> {
    console.log("[RunHistory] Closing SQLite connection");
    await this.db.close();
  }
}

/**
 * Writes a single LoopRun as a JSON line to the specified log file.
 * The function is idempotent – the same runId will always produce the same line.
 *
 * @param logFile Path to the log file watched by LoopMonitor.
 * @param run The LoopRun object to serialize.
 */
async function appendRunLog(logFile: string, run: LoopRun): Promise<void> {
  console.log(`[IO] Appending run ${run.runId} to ${logFile}`);
  const line = JSON.stringify(run) + "\n";
  await fs.appendFile(logFile, line, { encoding: "utf8" });
}

/**
 * Generates a synthetic LoopRun with deterministic fields based on the task name.
 *
 * @param taskName Name of the originating task.
 * @returns A new LoopRun instance.
 */
function generateRun(taskName: string): LoopRun {
  const now = new Date();
  const runId = randomUUID();
  const durationMs = Math.floor(500 + Math.random() * 1500);
  const tokensUsed = Math.floor(200 + Math.random() * 800);
  return {
    runId,
    timestamp: now.toISOString(),
    pattern: taskName,
    durationMs,
    tokensUsed,
    provider: "grok",
    outcome: "report",
    metadata: { generatedBy: "basic-usage-example" },
  };
}

/**
 * Main entry point. Sets up configuration loading, the monitor, SQLite history,
 * and a couple of example tasks that write loop run logs.
 */
async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const configPath = args[0] ?? path.resolve(process.cwd(), "loopwatch.yaml");
  const logsDir = args[1] ?? path.resolve(process.cwd(), "logs");
  const dryRun = process.env.DRY_RUN === "1";

  console.log(`[Main] Configuration path: ${configPath}`);
  console.log(`[Main] Logs directory: ${logsDir}`);
  console.log(`[Main] Dry‑run mode: ${dryRun}`);

  // Ensure the logs directory exists.
  console.log("[Main] Ensuring logs directory exists");
  await fs.mkdir(logsDir, { recursive: true });

  // Load configuration.
  const loader = new ConfigLoader();
  const config: LoopwatchConfig = await loader.load(configPath);
  console.log("[Main] Configuration loaded");

  // Initialise SQLite run history.
  const history = new RunHistory();
  const dbPath = path.join(logsDir, "run-history.sqlite");
  await history.init(dbPath);

  // Instantiate and start the monitor.
  const monitor = new LoopMonitor();
  await monitor.start();

  // Register a shutdown hook to clean up resources.
  const shutdown = async () => {
    console.log("[Main] Shutdown initiated");
    await monitor.shutdown();
    await history.close();
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);

  // Create a sample task that writes a run every 5 seconds.
  const taskA = new Task(
    "sample-task-a",
    5000,
    async () => {
      const run = generateRun("sample-task-a");
      const logFile = path.join(logsDir, "sample-a.log");
      if (!dryRun) {
        await appendRunLog(logFile, run);
        await history.insert(run);
      } else {
        console.log(`[Dry‑run] Would append run ${run.runId} to ${logFile}`);
      }
    }
  );

  // Create a second task with a different interval.
  const taskB = new Task(
    "sample-task-b",
    8000,
    async () => {
      const run = generateRun("sample-task-b");
      const logFile = path.join(logsDir, "sample-b.log");
      if (!dryRun) {
        await appendRunLog(logFile, run);
        await history.insert(run);
      } else {
        console.log(`[Dry‑run] Would append run ${run.runId} to ${logFile}`);
      }
    }
  );

  // Start tasks concurrently.
  const timers: NodeJS.Timer[] = [taskA.start(), taskB.start()];

  // Keep the process alive until a termination signal is received.
  console.log("[Main] Example is now running – press Ctrl+C to stop");
  // eslint-disable-next-line @typescript-eslint/no-empty-function
  await new Promise(() => {});
}

// Execute the script when run directly.
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error("[Main] Fatal error:", err);
    process.exit(1);
  });
}