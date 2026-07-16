import { readFileSync, existsSync } from "fs";
import { resolve, dirname } from "path";
import { exit } from "process";
import { PolicyEngine, defaultPolicySet } from "../src/core/policyEngine";
import { FileSystemGuard } from "../src/fs/fileSystemGuard";
import { AIConnector } from "../src/ai/aiConnector";
import {
  ChangeSet,
  Verdict,
  ApplyResult,
  FileContentResult,
  WriteResult,
  AIResponse,
  Policy,
} from "../src/types";

/**
 * Simple command‑line interface that reads a JSON ChangeSet from stdin,
 * evaluates policies, and applies the changes if allowed.
 */
async function run() {
  const stdin = process.stdin;
  let data = "";
  for await (const chunk of stdin) {
    data += chunk;
  }
  let changeSet: ChangeSet;
  try {
    changeSet = JSON.parse(data);
  } catch (e) {
    console.error("Invalid JSON input");
    exit(1);
  }

  const engine = new PolicyEngine(defaultPolicySet);
  const guard = new FileSystemGuard(engine);

  const verdict: Verdict = await engine.evaluate(changeSet);
  if (!verdict.allowed) {
    console.error("Policy denied the change set:", verdict.reasons);
    exit(1);
  }

  const result: ApplyResult = await guard.applyChangeSet(changeSet);
  if (result.applied) {
    console.log("Change set applied successfully.");
  } else {
    console.error("Failed to apply change set:", result.errors);
    exit(1);
  }
}

run().catch(err => {
  console.error(err);
  exit(1);
});
