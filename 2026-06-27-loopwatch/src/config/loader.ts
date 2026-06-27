import { promises as fsPromises, watch as fsWatch, FSWatcher } from "fs";
import { EventEmitter } from "events";
import * as path from "path";
import yaml from "js-yaml";

import {
  LoopwatchConfig,
  RuleDefinition,
  AlertChannelConfig,
  Severity,
} from "../types";

/**
 * Loads and validates the LoopWatch configuration file and provides a
 * watchable EventEmitter that emits `change` events when the file is edited.
 */
export class ConfigLoader {
  private configPath!: string;
  private emitter!: EventEmitter;
  private watcher?: FSWatcher;
  private lastConfig?: LoopwatchConfig;

  /**
   * Reads, parses, and validates a LoopWatch configuration file.
   *
   * @param configPath Path to the `loopwatch.yaml` file.
   * @returns A fully typed LoopwatchConfig object.
   * @throws Process exits with code 1 on fatal validation errors.
   */
  async load(configPath: string = "loopwatch.yaml"): Promise<LoopwatchConfig> {
    this.configPath = path.resolve(configPath);
    console.info(`[INFO] Loading configuration from ${this.configPath}`);

    const raw = await this.readFileWithRetry(this.configPath);
    const parsed = yaml.load(raw);
    if (typeof parsed !== "object" || parsed === null) {
      console.error("[FATAL] Configuration file does not contain a valid YAML object");
      process.exit(1);
    }

    const config = this.validateConfig(parsed as Record<string, unknown>);
    this.lastConfig = config;
    console.info("[INFO] Configuration loaded and validated successfully");
    return config;
  }

  /**
   * Starts watching the configuration file for changes. Emits a `change`
   * event with the new LoopwatchConfig each time the file is successfully
   * reloaded.
   *
   * @param configPath Path to the `loopwatch.yaml` file.
   * @returns An EventEmitter that emits `change` events.
   */
  watch(configPath: string = "loopwatch.yaml"): EventEmitter {
    this.configPath = path.resolve(configPath);
    this.emitter = new EventEmitter();

    console.info(`[INFO] Setting up watcher on ${this.configPath}`);
    try {
      this.watcher = fsWatch(this.configPath, (eventType) => {
        if (eventType !== "change") return;
        console.info(`[INFO] Detected change in configuration file`);
        this.reloadAndEmit()
          .catch((err) => {
            console.error("[ERROR] Failed to reload configuration after change:", err);
          });
      });
    } catch (err) {
      console.error("[FATAL] Unable to watch configuration file:", err instanceof Error ? err.message : err);
      process.exit(1);
    }

    return this.emitter;
  }

  /** Internal helper: reloads the config and emits a `change` event. */
  private async reloadAndEmit(): Promise<void> {
    const newConfig = await this.load(this.configPath);
    if (JSON.stringify(newConfig) !== JSON.stringify(this.lastConfig)) {
      console.info("[INFO] Configuration has changed – emitting `change` event");
      this.emitter.emit("change", newConfig);
    } else {
      console.info("[INFO] Configuration reload detected no substantive changes");
    }
  }

  /** Reads a file with exponential back‑off retry logic for transient errors. */
  private async readFileWithRetry(filePath: string, attempts = 3): Promise<string> {
    let delay = 100;
    for (let i = 0; i < attempts; i++) {
      try {
        console.info(`[INFO] Attempt ${i + 1} to read ${filePath}`);
        return await fsPromises.readFile(filePath, "utf8");
      } catch (err) {
        const isTransient = this.isTransientError(err);
        console.warn(
          `[WARN] Read attempt ${i + 1} failed (${isTransient ? "transient" : "fatal"}):`,
          err instanceof Error ? err.message : err,
        );
        if (!isTransient || i === attempts - 1) {
          console.error("[FATAL] Unable to read configuration file after retries");
          process.exit(1);
        }
        await this.sleep(delay);
        delay *= 2;
      }
    }
    // Unreachable – the loop always exits via process.exit on failure.
    throw new Error("Unreachable code in readFileWithRetry");
  }

  /** Determines whether an error is transient (e.g., ENOENT, EBUSY). */
  private isTransientError(err: unknown): boolean {
    if (!(err instanceof Error)) return false;
    const transientCodes = ["ENOENT", "EBUSY", "EAGAIN", "EMFILE"];
    // @ts-ignore – Node error may have a code property.
    return transientCodes.includes(err.code);
  }

  /** Simple promise‑based sleep. */
  private async sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /** Validates the raw parsed YAML object against the LoopwatchConfig schema. */
  private validateConfig(raw: Record<string, unknown>): LoopwatchConfig {
    const requiredTopLevel = ["rules", "pricing", "alerts", "watchPaths", "costThresholdUsd"];
    for (const key of requiredTopLevel) {
      if (!(key in raw)) {
        console.error(`[FATAL] Missing required top‑level field "${key}" in configuration`);
        process.exit(1);
      }
    }

    // ---- rules ----
    const rulesRaw = raw.rules;
    if (!Array.isArray(rulesRaw)) {
      console.error("[FATAL] `rules` must be an array");
      process.exit(1);
    }
    const rules: RuleDefinition[] = rulesRaw.map((r, idx) => this.validateRule(r, idx));

    // ---- pricing ----
    const pricingRaw = raw.pricing;
    if (!this.isPlainObject(pricingRaw)) {
      console.error("[FATAL] `pricing` must be a mapping of provider → price");
      process.exit(1);
    }
    const pricing: Record<string, number> = {};
    for (const [provider, price] of Object.entries(pricingRaw)) {
      if (typeof price !== "number" || price <= 0) {
        console.error(`[FATAL] Pricing for provider "${provider}" must be a positive number`);
        process.exit(1);
      }
      pricing[provider] = price;
    }

    // ---- alerts ----
    const alertsRaw = raw.alerts;
    if (!this.isPlainObject(alertsRaw)) {
      console.error("[FATAL] `alerts` must be a mapping of channel name → config");
      process.exit(1);
    }
    const alerts: Record<string, AlertChannelConfig> = {};
    for (const [channel, cfg] of Object.entries(alertsRaw)) {
      alerts[channel] = this.validateAlertChannel(cfg, channel);
    }

    // ---- watchPaths ----
    const watchPathsRaw = raw.watchPaths;
    if (!Array.isArray(watchPathsRaw) || !watchPathsRaw.every((p) => typeof p === "string")) {
      console.error("[FATAL] `watchPaths` must be an array of string glob patterns");
      process.exit(1);
    }
    const watchPaths = watchPathsRaw as string[];

    // ---- costThresholdUsd ----
    const costThresholdRaw = raw.costThresholdUsd;
    if (typeof costThresholdRaw !== "number" || costThresholdRaw <= 0) {
      console.error("[FATAL] `costThresholdUsd` must be a positive number");
      process.exit(1);
    }
    const costThresholdUsd = costThresholdRaw;

    return {
      rules,
      pricing,
      alerts,
      watchPaths,
      costThresholdUsd,
    };
  }

  /** Validates a single rule definition object. */
  private validateRule(raw: unknown, index: number): RuleDefinition {
    if (!this.isPlainObject(raw)) {
      console.error(`[FATAL] Rule at index ${index} is not an object`);
      process.exit(1);
    }
    const obj = raw as Record<string, unknown>;

    const required = ["id", "severity", "condition", "message"];
    for (const key of required) {
      if (!(key in obj)) {
        console.error(`[FATAL] Rule at index ${index} missing required field "${key}"`);
        process.exit(1);
      }
    }

    const id = obj.id;
    const severity = obj.severity;
    const condition = obj.condition;
    const message = obj.message;

    if (typeof id !== "string" || id.trim() === "") {
      console.error(`[FATAL] Rule id at index ${index} must be a non‑empty string`);
      process.exit(1);
    }
    if (!this.isValidSeverity(severity)) {
      console.error(`[FATAL] Rule severity "${severity}" at index ${index} is invalid`);
      process.exit(1);
    }
    if (typeof condition !== "string" || condition.trim() === "") {
      console.error(`[FATAL] Rule condition at index ${index} must be a non‑empty string`);
      process.exit(1);
    }
    if (typeof message !== "string" || message.trim() === "") {
      console.error(`[FATAL] Rule message at index ${index} must be a non‑empty string`);
      process.exit(1);
    }

    return {
      id,
      severity: severity as Severity,
      condition,
      message,
    };
  }

  /** Validates an alert channel configuration object. */
  private validateAlertChannel(raw: unknown, channelName: string): AlertChannelConfig {
    if (!this.isPlainObject(raw)) {
      console.error(`[FATAL] Alert channel "${channelName}" config must be an object`);
      process.exit(1);
    }
    const obj = raw as Record<string, unknown>;

    // For simplicity we require at least a `type` field; further validation is
    // delegated to the channel implementation.
    if (typeof obj.type !== "string" || obj.type.trim() === "") {
      console.error(`[FATAL] Alert channel "${channelName}" missing required string field "type"`);
      process.exit(1);
    }

    // Preserve the raw config for downstream consumers.
    return obj as AlertChannelConfig;
  }

  /** Helper to check plain objects (excluding arrays). */
  private isPlainObject(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
  }

  /** Helper to validate severity strings. */
  private isValidSeverity(value: unknown): boolean {
    return typeof value === "string" && ["info", "warning", "error"].includes(value);
  }
}