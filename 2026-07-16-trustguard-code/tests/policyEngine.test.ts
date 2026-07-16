import { readFileSync, writeFileSync, mkdirSync, rmSync } from "fs";
import { join } from "path";
import { PolicyEngine, defaultPolicySet } from "../src/core/policyEngine";
import { Policy, ChangeSet, Verdict } from "../src/types";

describe("PolicyEngine", () => {
  const createChangeSet = (content: string): ChangeSet => ({
    files: [{ path: "example.txt", oldHash: "", newContent: content }],
    author: "tester",
  });

  it("should allow changes when all policies approve", async () => {
    const engine = new PolicyEngine(defaultPolicySet);
    const cs = createChangeSet("hello world");
    const verdict = await engine.evaluate(cs);
    expect(verdict.allowed).toBe(true);
  });

  it("should reject changes when a policy denies", async () => {
    const denyPolicy: Policy = async () => ({ allowed: false, reasons: ["denied"] });
    const engine = new PolicyEngine([denyPolicy]);
    const cs = createChangeSet("bad content");
    const verdict = await engine.evaluate(cs);
    expect(verdict.allowed).toBe(false);
    expect(verdict.reasons).toContain("denied");
  });
});
