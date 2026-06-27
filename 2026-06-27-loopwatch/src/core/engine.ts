import { promises as fsPromises, createReadStream, watch, FSWatcher } from "fs";
import { createHash } from "crypto";
import * as path from "path";
import * as readline from "readline";
import { EventEmitter } from "events";

import {
  LoopRun,
  RuleResult,
  Alert,
  LoopwatchConfig,
  Severity,
  RunId,
  RuleId,
} from "../types";

import { RuleEngine } from "../rules/engine";
import { CostEstimator } from "../cost/estimator";
import { AlertDispatcher } from "../alerts/dispatcher";

/**
 * Core class that monitors loop‑run log files, feeds them to the rule engine,
 * runs cost estimation, and dispatches alerts.
 */
export class LoopMonitor extends EventEmitter {
  private config: LoopwatchConfig;
  private ruleEngine: RuleEngine;
  private costEstimator: CostEstimator;
  private alertDispatcher: AlertDispatcher;
  private watcher?: FSWatcher;

  constructor(config: LoopwatchConfig) {
    super();
    this.config = config;
    this.ruleEngine = new RuleEngine(config.rules);
    this.costEstimator = new CostEstimator(config.costEstimation);
    this.alertDispatcher = new AlertDispatcher(config.alerts);
  }

  /** Start watching the configured globs */
  async start(): Promise<void> {
    const globs = this.config.watchGlobs;
    // For simplicity we watch the first glob only in this minimal implementation.
    const filePath = globs[0];
    this.watcher = watch(filePath, async (event) => {
      if (event === "change") {
        await this.processFile(filePath);
      }
    });
    // Initial processing
    await this.processFile(filePath);
  }

  private async processFile(filePath: string): Promise<void> {
    const stream = createReadStream(filePath, { encoding: "utf8" });
    const rl = readline.createInterface({ input: stream, crlfDelay: Infinity });
    for await (const line of rl) {
      if (!line.trim()) continue;
      let run: LoopRun;
      try {
        run = JSON.parse(line) as LoopRun;
      } catch {
        continue; // ignore malformed lines
      }
      const results: RuleResult[] = this.ruleEngine.evaluate(run);
      const alerts: Alert[] = results
        .filter((r) => !r.passed)
        .map((r) => ({
          id: createHash("sha256").update(r.ruleId + run.runId).digest("hex"),
          message: r.message ?? "Rule violation",
          severity: r.severity,
          channel: "default",
          timestamp: new Date().toISOString(),
        }));
      if (alerts.length) {
        await this.alertDispatcher.dispatch(alerts);
      }
      this.costEstimator.recordRun(run);
    }
  }

  /** Stop watching files */
  async stop(): Promise<void> {
    if (this.watcher) {
      this.watcher.close();
    }
  }
}
