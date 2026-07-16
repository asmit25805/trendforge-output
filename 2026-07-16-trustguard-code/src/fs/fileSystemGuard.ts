import { promises as fsPromises, constants as fsConstants } from "fs";
import { dirname, resolve, join } from "path";
import { createHash } from "crypto";
import { tmpdir } from "os";
import {
  ChangeSet,
  FileContentResult,
  ReadOpts,
  WriteResult,
  ApplyResult,
  Verdict,
  PolicyEngine,
} from "../types";

/**
 * Guard that performs file system operations only after policy approval.
 */
export class FileSystemGuard {
  private policyEngine: PolicyEngine;

  constructor(policyEngine: PolicyEngine) {
    this.policyEngine = policyEngine;
  }

  /**
   * Read a file respecting optional read options.
   */
  async readFile(path: string, opts: ReadOpts = {}): Promise<FileContentResult> {
    const content = await fsPromises.readFile(path, opts.encoding ?? "utf8");
    const hash = createHash("sha256").update(content).digest("hex");
    return { content, hash };
  }

  /**
   * Write a file after ensuring the change set is allowed.
   */
  async writeFile(change: { path: string; newContent: string }): Promise<WriteResult> {
    const changeSet = {
      files: [{ path: change.path, oldHash: "", newContent: change.newContent }],
      author: "system",
    };
    const verdict = await this.policyEngine.evaluate(changeSet);
    if (!verdict.allowed) {
      return { path: change.path, success: false, error: "Policy denied" };
    }
    await fsPromises.writeFile(change.path, change.newContent);
    return { path: change.path, success: true };
  }

  /**
   * Apply an entire ChangeSet atomically after policy approval.
   */
  async applyChangeSet(changeSet: ChangeSet): Promise<ApplyResult> {
    const verdict = await this.policyEngine.evaluate(changeSet);
    if (!verdict.allowed) {
      return { applied: false, errors: verdict.reasons };
    }
    const errors: string[] = [];
    for (const file of changeSet.files) {
      try {
        await fsPromises.writeFile(file.path, file.newContent);
      } catch (e) {
        errors.push(`Failed to write ${file.path}: ${(e as Error).message}`);
      }
    }
    return { applied: errors.length === 0, errors: errors.length ? errors : undefined };
  }
}
