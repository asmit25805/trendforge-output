// test/skillRegistry.test.ts
import { SkillRegistry } from "../src/core/skillRegistry";
import { SkillDefinition, SkillInfo } from "../src/types";
import { writeFileSync, rmSync, mkdirSync, existsSync } from "fs";
import { join } from "path";
import os from "os";

describe("SkillRegistry", () => {
  const tempDir = join(os.tmpdir(), `skill-registry-test-${Date.now()}`);
  const skillPath = join(tempDir, "exampleSkill.js");

  beforeAll(() => {
    mkdirSync(tempDir, { recursive: true });
    const skillModule = `module.exports = {
      name: "exampleSkill",
      execute: () => "executed",
    };`;
    writeFileSync(skillPath, skillModule);
  });

  afterAll(() => {
    rmSync(tempDir, { recursive: true, force: true });
  });

  it("registers and retrieves a skill", () => {
    const registry = new SkillRegistry();
    registry.registerSkill(skillPath);
    const info = registry.getSkillInfo("exampleSkill");
    expect(info).toBeDefined();
    expect(info?.definition.execute()).toBe("executed");
  });
});
