import { execFile } from "child_process";
import { promises as fsPromises } from "fs";
import { resolve, dirname, join } from "path";
import { tmpdir } from "os";
import { promisify } from "util";
import globModule from "glob";
import { createHash } from "crypto";
import {
  ChangeSet,
  Policy,
  Verdict,
  FileContentResult,
  WriteResult,
  ApplyResult,
  ReadOpts,
} from "../types";

const glob = promisify(globModule);

/**
 * Simple search engine that resolves file paths using glob patterns.
 */
export class SearchEngine {
  /**
   * Search for files matching the given glob pattern.
   */
  async search(pattern: string, cwd: string = process.cwd()): Promise<string[]> {
    const absolutePattern = resolve(cwd, pattern);
    return await glob(absolutePattern, { nodir: true });
  }
}
