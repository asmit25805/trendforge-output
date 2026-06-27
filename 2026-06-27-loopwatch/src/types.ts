// src/types.ts

/**
 * Severity levels used by rules and alerts.
 */
export type Severity = "info" | "warning" | "error";

/**
 * Possible outcomes of a loop run.
 */
export type RunOutcome = "report" | "action" | "escalated";

/**
 * Unique identifier for a rule definition.
 */
export type RuleId = string;

/**
 * Unique identifier for a loop run (ISO‑8601 UUID string).
 */
export type RunId = string; // e.g., "550e8400-e29b-41d4-a716-446655440000"

/**
 * Representation of a single loop execution.
 */
export interface LoopRun {
  runId: RunId;
  timestamp: string; // ISO‑8601
  pattern: string; // name of the loop pattern
  durationMs: number;
  tokensUsed: number;
  provider: string; // e.g., "grok", "claude"
  outcome?: RunOutcome;
  metadata?: Record<string, unknown>;
}

/**
 * Definition of a rule supplied by the user.
 */
export interface RuleDefinition {
  id: RuleId;
  description: string;
  severity: Severity;
  /** JavaScript predicate that receives a LoopRun and returns a boolean */
  script: string;
}

/**
 * Result of evaluating a rule against a LoopRun.
 */
export interface RuleResult {
  ruleId: RuleId;
  passed: boolean;
  severity: Severity;
  message?: string;
}

/**
 * Projection of future cost based on token usage.
 */
export interface CostProjection {
  provider: string;
  estimatedTokens: number;
  estimatedCostUsd: number;
  windowMs: number;
}

/**
 * Configuration for an alert channel.
 */
export interface AlertChannelConfig {
  type: string; // e.g., "slack", "github", "email"
  webhookUrl?: string;
  /** Additional channel‑specific options */
  options?: Record<string, unknown>;
}

/**
 * Alert payload dispatched by the AlertDispatcher.
 */
export interface Alert {
  id: string;
  message: string;
  severity: Severity;
  channel: string;
  timestamp: string; // ISO‑8601
  metadata?: Record<string, unknown>;
}

/**
 * Top‑level configuration object for LoopWatch.
 */
export interface LoopwatchConfig {
  /** Glob pattern(s) for log files to watch */
  watchGlobs: string[];
  /** Rule definitions */
  rules: RuleDefinition[];
  /** Alert channel configurations */
  alerts: AlertChannelConfig[];
  /** Cost estimation settings */
  costEstimation?: {
    providerPricing: Record<string, number>; // USD per 1k tokens
    slidingWindowMs: number;
  };
}
