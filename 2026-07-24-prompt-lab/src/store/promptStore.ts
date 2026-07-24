import { promises as fs } from "fs";
import { join, resolve } from "path";

import {
  PromptMeta,
  PromptMetaSchema,
  PromptEdit,
} from "../types.js";

/**
 * PromptStore loads, validates, and caches prompt metadata and markdown files.
 *
 * It scans the `prompts` directory, parses each `meta.json` and `prompt.md`,
 * and keeps an in‑memory index for fast lookup and search.
 */
export class PromptStore {
  private cache: Map<string, { meta: PromptMeta; edit: PromptEdit }> = new Map();
  private promptsDir = resolve("src", "prompts");

  /** Load all prompts from the filesystem and cache them. */
  async loadAll(): Promise<PromptMeta[]> {
    const dirs = await fs.readdir(this.promptsDir, { withFileTypes: true });
    const metaList: PromptMeta[] = [];
    for (const dirent of dirs) {
      if (!dirent.isDirectory()) continue;
      const metaPath = join(this.promptsDir, dirent.name, "meta.json");
      const mdPath = join(this.promptsDir, dirent.name, "prompt.md");
      const [metaRaw, editRaw] = await Promise.all([
        fs.readFile(metaPath, "utf-8"),
        fs.readFile(mdPath, "utf-8"),
      ]);
      const meta = PromptMetaSchema.parse(JSON.parse(metaRaw));
      const edit: PromptEdit = { content: editRaw };
      this.cache.set(meta.id, { meta, edit });
      metaList.push(meta);
    }
    return metaList;
  }

  /** Retrieve metadata for a specific prompt by its identifier. */
  async getMeta(id: string): Promise<PromptMeta> {
    const cached = this.cache.get(id);
    if (cached) return cached.meta;
    await this.loadAll();
    const entry = this.cache.get(id);
    if (!entry) throw new Error(`Prompt with id "${id}" not found`);
    return entry.meta;
  }

  /** Retrieve the editable markdown for a specific prompt. */
  async getEdit(id: string): Promise<PromptEdit> {
    const cached = this.cache.get(id);
    if (cached) return cached.edit;
    await this.loadAll();
    const entry = this.cache.get(id);
    if (!entry) throw new Error(`Prompt with id "${id}" not found`);
    return entry.edit;
  }
}
