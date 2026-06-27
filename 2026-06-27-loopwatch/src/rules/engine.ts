import { createHash } from "crypto";
import { Script, createContext } from "vm";

import {
  LoopRun,
  RuleResult,
  Severity,
  RuleId,
  RuleDefinition,
} from "../types";

/**
 * Internal representation of a compiled rule.
 */
interface CompiledRule {
  /** Original rule definition */
  definition: RuleDefinition;
  /** Sandbox script that evaluates to a boolean */
  script: Script;
}

/**
 * Engine that evaluates LoopRun objects against a set of compliance and safety rules.
 *
 * Rules are defined with a JavaScript expression (`condition`) that is executed in a
 * sandboxed VM with the LoopRun bound as `run`. The expression must return a boolean
 * indicating whether the rule passes (`true`) or fails (`false`).
 *
 * Example rule definition:
 * ```yaml
 * - id: "no-long-duration"
 *   severity: "warning"
 *   condition: "run.durationMs < 30000"
 *   message: "Run duration exceeds 30 seconds"
 * ```
 */
export class RuleEngine {
  /** Map of ruleId → compiled rule */
  private compiledRules: Map<RuleId, CompiledRule> = new Map();

  /**
   * Parses rule definitions from a configuration array and registers them.
   *
   * @param config Array of rule definitions.
   * @throws Will exit the process if any rule definition is invalid.
   */
  loadRules(config: RuleDefinition[]): void {
    console.info("[INFO] Loading rule definitions");
    this.compiledRules.clear();

    for (const def of config) {
      try {
        this.validateDefinition(def);
        const compiled = this.compileRule(def);
        this.compiledRules.set(def.id, compiled);
        console.info(`[INFO] Loaded rule ${def.id}`);
      } catch (err) {
        console.error(`[FATAL] Invalid rule definition: ${err instanceof Error ? err.message : err}`);
        process.exit(1);
      }
    }
  }

  /**
   * Registers a new rule at runtime.
   *
   * @param rule Rule definition to add.
   */
  addRule(rule: RuleDefinition): void {
    console.info(`[INFO] Adding rule ${rule.id} at runtime`);
    this.validateDefinition(rule);
    const compiled = this.compileRule(rule);
    this.compiledRules.set(rule.id, compiled);
    console.info(`[INFO] Rule ${rule.id} added`);
  }

  /**
   * Evaluates a LoopRun against all loaded rules.
   *
   * @param run The LoopRun to evaluate.
   * @returns Array of RuleResult objects, one per rule.
   */
  evaluate(run: LoopRun): RuleResult[] {
    console.info(`[INFO] Evaluating run ${run.runId} against ${this.compiledRules.size} rule(s)`);
    const results: RuleResult[] = [];

    for (const [ruleId, compiled] of this.compiledRules.entries()) {
      let passed: boolean;
      try {
        passed = this.runCondition(compiled.script, run);
      } catch (err) {
        console.error(`[ERROR] Rule ${ruleId} evaluation error: ${err instanceof Error ? err.message : err}`);
        // Treat evaluation errors as rule failures with highest severity.
        passed = false;
        compiled.definition.severity = "error";
      }

      const result: RuleResult = {
        ruleId,
        severity: compiled.definition.severity,
        message: compiled.definition.message,
        passed,
        details: { condition: compiled.definition.condition },
      };
      results.push(result);
    }

    console.info(`[INFO] Evaluation completed for run ${run.runId}`);
    return results;
  }

  /**
   * Validates that a rule definition contains all required fields.
   *
   * @param def Rule definition to validate.
   * @throws Error if validation fails.
   */
  private validateDefinition(def: RuleDefinition): void {
    if (!def.id || typeof def.id !== "string") {
      throw new Error("Rule must have a non‑empty string `id`");
    }
    if (!def.severity || !["info", "warning", "error"].includes(def.severity)) {
      throw new Error(`Rule ${def.id} has invalid severity`);
    }
    if (!def.condition || typeof def.condition !== "string") {
      throw new Error(`Rule ${def.id} missing ` + "`condition` string");
    }
    if (!def.message || typeof def.message !== "string") {
      throw new Error(`Rule ${def.id} missing ` + "`message` string");
    }
  }

  /**
   * Compiles a rule's condition into a sandboxed Script.
   *
   * @param def Rule definition.
   * @returns CompiledRule containing the sandbox script.
   */
  private compileRule(def: RuleDefinition): CompiledRule {
    // Wrap the condition in a function to avoid leaking globals.
    const wrapped = `(function(run) { return (${def.condition}); })`;
    const script = new Script(wrapped, { filename: `rule-${def.id}.js` });
    return { definition: def, script };
  }

  /**
   * Executes a compiled script with the provided LoopRun in a sandbox.
   *
   * @param script Compiled VM script.
   * @param run LoopRun instance.
   * @returns Boolean result of the condition.
   */
  private runCondition(script: Script, run: LoopRun): boolean {
    // Create a fresh context for each evaluation to guarantee isolation.
    const sandbox = { run, console };
    const context = createContext(sandbox);
    const fn = script.runInContext(context) as (run: LoopRun) => unknown;
    const result = fn(run);
    if (typeof result !== "boolean") {
      throw new Error("Condition did not return a boolean");
    }
    return result;
  }
}

/**
 * Definition of a compliance or safety rule.
 *
 * `condition` is a JavaScript expression evaluated with the LoopRun bound as `run`.
 * It must return a boolean where `true` means the rule passes.
 */
export interface RuleDefinition {
  /** Unique identifier for the rule */
  id: RuleId;
  /** Severity level for violations */
  severity: Severity;
  /** JavaScript boolean expression evaluated against a LoopRun */
  condition: string;
  /** Human‑readable description used when the rule fails */
  message: string;
}