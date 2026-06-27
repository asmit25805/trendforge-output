import { RuleEngine } from "../src/rules/engine";
import {
  LoopRun,
  RuleResult,
  Severity,
  RuleDefinition,
} from "../src/types";

describe("RuleEngine evaluation logic", () => {
  let engine: RuleEngine;
  const baseRun: LoopRun = {
    runId: "run-123",
    timestamp: new Date().toISOString(),
    pattern: "daily-triage",
    durationMs: 1500,
    tokensUsed: 800,
    provider: "grok",
    outcome: "report",
    metadata: {},
  };

  beforeEach(() => {
    console.info("[TEST] Instantiating a fresh RuleEngine");
    engine = new RuleEngine();
  });

  test("engine evaluates with no rules and returns empty array", () => {
    console.info("[TEST] Evaluating run with zero rules");
    const results = engine.evaluate(baseRun);
    expect(Array.isArray(results)).toBe(true);
    expect(results).toHaveLength(0);
  });

  test("engine adds a rule that passes and returns a passing RuleResult", () => {
    console.info("[TEST] Adding passing rule (duration < 2000ms)");
    const passingRule: RuleDefinition = {
      ruleId: "duration-check",
      description: "Run duration must be under 2 seconds",
      severity: "info" as Severity,
      condition: (run: LoopRun) => run.durationMs < 2000,
    } as unknown as RuleDefinition;

    engine.addRule(passingRule);
    console.info("[TEST] Evaluating run that satisfies the rule");
    const results = engine.evaluate(baseRun);
    expect(results).toHaveLength(1);
    const result = results[0] as RuleResult;
    expect(result.ruleId).toBe("duration-check");
    expect(result.passed).toBe(true);
    expect(result.severity).toBe("info");
    expect(typeof result.message).toBe("string");
  });

  test("engine adds a rule that fails with warning severity", () => {
    console.info("[TEST] Adding warning rule (tokensUsed > 500)");
    const warningRule: RuleDefinition = {
      ruleId: "token-usage",
      description: "Token usage should stay below 500",
      severity: "warning" as Severity,
      condition: (run: LoopRun) => run.tokensUsed <= 500,
    } as unknown as RuleDefinition;

    engine.addRule(warningRule);
    console.info("[TEST] Evaluating run that violates the rule");
    const results = engine.evaluate(baseRun);
    expect(results).toHaveLength(1);
    const result = results[0] as RuleResult;
    expect(result.ruleId).toBe("token-usage");
    expect(result.passed).toBe(false);
    expect(result.severity).toBe("warning");
    expect(typeof result.message).toBe("string");
  });

  test("engine evaluates multiple rules and aggregates results", () => {
    console.info("[TEST] Adding two rules: one passing, one failing");
    const ruleA: RuleDefinition = {
      ruleId: "duration-ok",
      description: "Duration under 2s",
      severity: "info" as Severity,
      condition: (run: LoopRun) => run.durationMs < 2000,
    } as unknown as RuleDefinition;

    const ruleB: RuleDefinition = {
      ruleId: "high-token",
      description: "Tokens used must be <= 500",
      severity: "error" as Severity,
      condition: (run: LoopRun) => run.tokensUsed <= 500,
    } as unknown as RuleDefinition;

    engine.addRule(ruleA);
    engine.addRule(ruleB);
    console.info("[TEST] Evaluating run against both rules");
    const results = engine.evaluate(baseRun);
    expect(results).toHaveLength(2);
    const ids = results.map((r) => r.ruleId).sort();
    expect(ids).toEqual(["duration-ok", "high-token"]);
    const passed = results.find((r) => r.ruleId === "duration-ok")!;
    const failed = results.find((r) => r.ruleId === "high-token")!;
    expect(passed.passed).toBe(true);
    expect(failed.passed).toBe(false);
    expect(failed.severity).toBe("error");
  });

  test("engine handles rule condition throwing an exception and reports error severity", () => {
    console.info("[TEST] Adding rule with faulty condition that throws");
    const faultyRule: RuleDefinition = {
      ruleId: "exception-rule",
      description: "Faulty condition should be caught",
      severity: "error" as Severity,
      condition: (run: LoopRun) => {
        throw new Error("Intentional failure");
      },
    } as unknown as RuleDefinition;

    engine.addRule(faultyRule);
    console.info("[TEST] Evaluating run; expecting error result");
    const results = engine.evaluate(baseRun);
    expect(results).toHaveLength(1);
    const result = results[0] as RuleResult;
    expect(result.ruleId).toBe("exception-rule");
    expect(result.passed).toBe(false);
    expect(result.severity).toBe("error");
    expect(result.message).toContain("Intentional failure");
  });

  test("engine respects rule severity levels when generating results", () => {
    console.info("[TEST] Adding three rules with distinct severities");
    const infoRule: RuleDefinition = {
      ruleId: "info-rule",
      description: "Info level rule that passes",
      severity: "info" as Severity,
      condition: () => true,
    } as unknown as RuleDefinition;

    const warningRule: RuleDefinition = {
      ruleId: "warning-rule",
      description: "Warning level rule that fails",
      severity: "warning" as Severity,
      condition: () => false,
    } as unknown as RuleDefinition;

    const errorRule: RuleDefinition = {
      ruleId: "error-rule",
      description: "Error level rule that fails",
      severity: "error" as Severity,
      condition: () => false,
    } as unknown as RuleDefinition;

    engine.addRule(infoRule);
    engine.addRule(warningRule);
    engine.addRule(errorRule);
    console.info("[TEST] Evaluating run against all three rules");
    const results = engine.evaluate(baseRun);
    expect(results).toHaveLength(3);
    const severityMap = results.reduce((acc, cur) => {
      acc[cur.ruleId] = cur.severity;
      return acc;
    }, {} as Record<string, Severity>);
    expect(severityMap["info-rule"]).toBe("info");
    expect(severityMap["warning-rule"]).toBe("warning");
    expect(severityMap["error-rule"]).toBe("error");
  });
});