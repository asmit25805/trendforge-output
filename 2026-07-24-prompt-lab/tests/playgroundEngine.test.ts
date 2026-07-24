import { describe, expect, test, beforeEach, jest } from "@jest/globals";
import { PlaygroundEngine } from "../src/engine/playgroundEngine.js";
import { PromptStore } from "../src/store/promptStore.js";
import { AIClient } from "../src/ai/aiClient.js";
import { SandboxCompiler } from "../src/compiler/sandboxCompiler.js";
import { PromptEdit, PromptMeta, GeneratedCode, Bundle, PreviewResult } from "../src/types.js";

jest.mock("../src/store/promptStore.js");
jest.mock("../src/ai/aiClient.js");
jest.mock("../src/compiler/sandboxCompiler.js");

const MockPromptStore = PromptStore as jest.MockedClass<typeof PromptStore>;
const MockAIClient = AIClient as jest.MockedClass<typeof AIClient>;
const MockSandboxCompiler = SandboxCompiler as jest.MockedClass<typeof SandboxCompiler>;

describe("PlaygroundEngine", () => {
  let engine: PlaygroundEngine;
  const fakeEdit: PromptEdit = { content: "# Example" };
  const fakeGenerated: GeneratedCode = { code: "export const Component = () => <div/>", path: "tmp/file.tsx" };
  const fakeBundle: Bundle = { code: "bundle code", path: "tmp/bundle.js" };
  const fakePreview: PreviewResult = { url: "http://localhost/preview" };

  beforeEach(() => {
    MockPromptStore.prototype.getEdit.mockResolvedValue(fakeEdit);
    MockAIClient.prototype.generate.mockResolvedValue(fakeGenerated);
    MockSandboxCompiler.prototype.bundle.mockResolvedValue(fakeBundle);
    MockSandboxCompiler.prototype.preview.mockResolvedValue(fakePreview);
    const store = new PromptStore();
    const client = new AIClient({ provider: "openai", apiKey: "test" });
    const compiler = new SandboxCompiler();
    engine = new PlaygroundEngine(store, client, compiler);
  });

  test("run executes full pipeline and returns preview", async () => {
    const result = await engine.run("example-id");
    expect(result.url).toBe(fakePreview.url);
    expect(MockPromptStore.prototype.getEdit).toHaveBeenCalledWith("example-id");
    expect(MockAIClient.prototype.generate).toHaveBeenCalled();
    expect(MockSandboxCompiler.prototype.bundle).toHaveBeenCalled();
    expect(MockSandboxCompiler.prototype.preview).toHaveBeenCalled();
  });
});
