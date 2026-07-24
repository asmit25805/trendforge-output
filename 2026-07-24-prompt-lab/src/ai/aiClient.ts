import { GeneratedCode, GeneratedCodeSchema, GenerationOptions } from "../types.js";
import { z } from "zod";

/**
 * Configuration options for the client that communicates with a language model provider.
 */
export interface AIClientConfig {
  /** Provider name – currently supports "openai" and "claude". */
  provider: "openai" | "claude";
  /** API key for the selected provider. */
  apiKey: string;
  /** Optional model identifier (e.g., "gpt-4o"). */
  model?: string;
}

/**
 * Client responsible for sending prompt edits to a language‑model service and
 * receiving generated TypeScript/React code.
 */
export class AIClient {
  private config: AIClientConfig;

  constructor(config: AIClientConfig) {
    this.config = config;
  }

  /**
   * Generate code based on a prompt edit.
   *
   * @param edit The edited markdown content.
   * @param options Additional generation options.
   * @returns An object containing the generated source code.
   */
  async generate(edit: { content: string }, options: GenerationOptions): Promise<GeneratedCode> {
    // In a real implementation this would call the external service.
    // Here we provide a deterministic placeholder for testing purposes.
    const placeholder = `export const Component = () => <div>${edit.content}</div>`;
    const parsed = GeneratedCodeSchema.parse({ code: placeholder });
    return parsed;
  }
}
