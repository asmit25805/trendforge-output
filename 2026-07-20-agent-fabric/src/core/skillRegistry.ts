// src/core/skillRegistry.ts
import { EventEmitter } from "events";
import { readFileSync, existsSync, statSync } from "fs";
import { resolve, dirname } from "path";
import {
  SkillDefinition,
  SkillInfo,
  JSONSchema7,
  COMMON_PROPERTIES,
} from "../types";

/**
 * Registry responsible for discovering, validating, and lazily loading skill modules.
 */
export class SkillRegistry extends EventEmitter {
  private skills: Map<string, SkillInfo> = new Map();

  /** Register a skill from a given absolute path */
  registerSkill(path: string): void {
    if (!existsSync(path)) {
      throw new Error(`Skill file does not exist: ${path}`);
    }
    const mod = require(path);
    const definition: SkillDefinition = mod.default ?? mod;
    if (!definition || typeof definition.execute !== "function") {
      throw new Error(`Invalid skill definition at ${path}`);
    }
    const name = definition.name ?? basename(path, ".js");
    const info: SkillInfo = { name, path, definition };
    this.skills.set(name, info);
    this.emit("registered", info);
  }

  /** Retrieve information about a registered skill */
  getSkillInfo(name: string): SkillInfo | undefined {
    return this.skills.get(name);
  }

  /** List all registered skill names */
  listSkills(): string[] {
    return Array.from(this.skills.keys());
  }
}
