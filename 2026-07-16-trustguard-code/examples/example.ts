import { resolve, dirname } from "path";
import { existsSync, readFileSync } from "fs";
import { AIConnector } from "../src/ai/aiConnector";
import { PolicyEngine, defaultPolicySet } from "../src/core/policyEngine";
import { FileSystemGuard } from "../src/fs/fileSystemGuard";
import { SearchEngine } from "../src/search/searchEngine";
import {
  ChangeSet,
  Verdict,
  ApplyResult,
  FileContentResult,
  WriteResult,
  AIResponse,
} from "../src/types";

/**
 * Demonstrates a typical workflow using TrustGuard components.
 */
async function main() {
  const policyEngine = new PolicyEngine(defaultPolicySet);
  const fsGuard = new FileSystemGuard(policyEngine);
  const search = new SearchEngine();
  const ai = new AIConnector({ endpoint: "https://api.example.com/v1" });

  // Find all TypeScript source files.
  const files = await search.search("src/**/*.ts");

  // Create a dummy ChangeSet – in a real scenario the AI would generate newContent.
  const changeSet: ChangeSet = {
    files: files.map(path => ({ path, oldHash: "", newContent: readFileSync(path, "utf8") })),
    author: "example@example.com",
  };

  // Evaluate policies.
  const verdict: Verdict = await policyEngine.evaluate(changeSet);
  if (!verdict.allowed) {
    console.error("Policy denied changes:", verdict.reasons);
    return;
  }

  // Apply the changes safely.
  const applyResult: ApplyResult = await fsGuard.applyChangeSet(changeSet);
  if (applyResult.applied) {
    console.log("Changes applied successfully.");
  } else {
    console.error("Failed to apply changes:", applyResult.errors);
  }
}

main().catch(err => console.error(err));
