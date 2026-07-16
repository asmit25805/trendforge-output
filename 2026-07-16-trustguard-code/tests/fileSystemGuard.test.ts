import { promises as fsPromises, constants as fsConstants } from "fs";
import { join, resolve } from "path";
import { tmpdir } from "os";
import { rmSync, mkdirSync, writeFileSync } from "fs";
import { FileSystemGuard } from "../src/fs/fileSystemGuard";
import { PolicyEngine, defaultPolicySet } from "../src/core/policyEngine";
import { Policy, ChangeSet, Verdict, FileContentResult, WriteResult, ApplyResult } from "../src/types";

describe("FileSystemGuard", () => {
  const tempDir = join(tmpdir(), "trustguard-test");
  beforeAll(() => {
    mkdirSync(tempDir, { recursive: true });
  });
  afterAll(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("writes a file only when policy allows", async () => {
    const engine = new PolicyEngine(defaultPolicySet);
    const guard = new FileSystemGuard(engine);
    const filePath = join(tempDir, "test.txt");
    const result = await guard.writeFile({ path: filePath, newContent: "data" });
    expect(result.success).toBe(true);
    const content = await fsPromises.readFile(filePath, "utf8");
    expect(content).toBe("data");
  });
});
