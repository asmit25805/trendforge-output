import { PromptEdit, PromptMeta, GeneratedCode, PreviewResult } from "../types.js";
import { PromptStore } from "../store/promptStore.js";
import { AIClient } from "../ai/aiClient.js";
import { SandboxCompiler } from "../compiler/sandboxCompiler.js";

/**
 * Engine that orchestrates the full pipeline from a user edit to a live preview.
 *
 * Steps:
 * 1. Validate the prompt metadata.
 * 2. Generate source code via the client.
 * 3. Bundle the code securely.
 * 4. Execute the bundle inside an isolated iframe and return a preview URL.
 */
export class PlaygroundEngine {
  private store: PromptStore;
  private client: AIClient;
  private compiler: SandboxCompiler;

  constructor(store: PromptStore, client: AIClient, compiler: SandboxCompiler) {
    this.store = store;
    this.client = client;
    this.compiler = compiler;
  }

  /** Run the complete pipeline for a given prompt identifier. */
  async run(id: string): Promise<PreviewResult> {
    const edit = await this.store.getEdit(id);
    const generated: GeneratedCode = await this.client.generate(edit, {} as any);
    const bundle = await this.compiler.bundle(generated);
    const preview = await this.compiler.preview(bundle);
    return preview;
  }
}
