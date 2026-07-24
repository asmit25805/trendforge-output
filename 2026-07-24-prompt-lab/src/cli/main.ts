import { Command } from "commander";
import { readFile, writeFile } from "fs/promises";
import { resolve } from "path";
import { z } from "zod";

import {
  PromptEdit,
  PromptMeta,
  GeneratedCode,
  Bundle,
  PreviewResult,
  GenerationOptions,
} from "../types.js";

import { PromptStore } from "../store/promptStore.js";
import { AIClient, AIClientConfig } from "../ai/aiClient.js";
import { SandboxCompiler } from "../compiler/sandboxCompiler.js";

/**
 * Command‑line interface entry point.
 *
 * Provides commands to list prompts, generate code, and preview bundles.
 */
export async function runCli() {
  const program = new Command();

  program
    .name("prompt-lab")
    .description("CLI for managing Prompt Lab prompts")
    .version("1.0.0");

  program
    .command("list")
    .description("List all available prompts")
    .action(async () => {
      const store = new PromptStore();
      const prompts = await store.loadAll();
      console.log(prompts.map((p) => `${p.id}: ${p.title}`).join("\n"));
    });

  program
    .command("generate <id>")
    .description("Generate code for a prompt using the configured client")
    .option("-p, --provider <provider>", "Provider name", "openai")
    .option("-k, --api-key <key>", "API key for the provider")
    .action(async (id: string, opts) => {
      const store = new PromptStore();
      const meta = await store.getMeta(id);
      const edit = await store.getEdit(id);

      const clientConfig: AIClientConfig = {
        provider: opts.provider as "openai" | "claude",
        apiKey: opts.apiKey,
      };
      const client = new AIClient(clientConfig);
      const generated: GeneratedCode = await client.generate(edit, {} as GenerationOptions);
      await writeFile(resolve("output", `${id}.tsx`), generated.code);
      console.log(`Generated code written to output/${id}.tsx`);
    });

  program
    .command("preview <id>")
    .description("Bundle and preview generated code for a prompt")
    .action(async (id: string) => {
      const store = new PromptStore();
      const edit = await store.getEdit(id);
      const client = new AIClient({ provider: "openai", apiKey: "" });
      const generated = await client.generate(edit, {} as GenerationOptions);
      const compiler = new SandboxCompiler();
      const bundle: Bundle = await compiler.bundle(generated);
      const preview: PreviewResult = await compiler.preview(bundle);
      console.log("Preview URL:", preview.url);
    });

  await program.parseAsync(process.argv);
}
