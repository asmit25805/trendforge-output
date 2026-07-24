import { describe, expect, test, beforeEach, jest } from "@jest/globals";
import { PromptStore } from "../src/store/promptStore.js";
import { PromptMeta } from "../src/types.js";
import * as fs from "fs/promises";
import * as path from "path";

jest.mock("fs/promises");

const mockReaddir = fs.readdir as jest.MockedFunction<typeof fs.readdir>;
const mockReadFile = fs.readFile as jest.MockedFunction<typeof fs.readFile>;

describe("PromptStore", () => {
  const fakeMeta: PromptMeta = {
    id: "test-prompt",
    title: "Test Prompt",
    description: "A prompt used for testing",
    tags: ["test"],
    previewImage: "",
    author: "",
    sourceUrl: "",
  };

  const fakeEdit = { content: "# Test Prompt\n\nSome markdown" };

  beforeEach(() => {
    jest.resetAllMocks();
    mockReaddir.mockResolvedValue([
      { name: "test-prompt", isDirectory: () => true } as any,
    ]);
    mockReadFile.mockImplementation(async (filePath: string) => {
      if (filePath.endsWith("meta.json")) {
        return JSON.stringify(fakeMeta);
      }
      if (filePath.endsWith("prompt.md")) {
        return fakeEdit.content;
      }
      throw new Error("Unexpected file path");
    });
  });

  test("loadAll returns metadata list", async () => {
    const store = new PromptStore();
    const metas = await store.loadAll();
    expect(metas).toHaveLength(1);
    expect(metas[0].id).toBe("test-prompt");
  });

  test("getMeta retrieves cached metadata", async () => {
    const store = new PromptStore();
    await store.loadAll();
    const meta = await store.getMeta("test-prompt");
    expect(meta.title).toBe("Test Prompt");
  });

  test("getEdit retrieves cached edit", async () => {
    const store = new PromptStore();
    await store.loadAll();
    const edit = await store.getEdit("test-prompt");
    expect(edit.content).toContain("Some markdown");
  });
});
