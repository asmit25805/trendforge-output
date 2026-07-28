import { AgentEngine, TaskSpec, AgentEventType, AgentEvent } from "../src/core/agentEngine";
import { ProviderAdapter, ProviderConfig, ProviderError } from "../src/providers/providerAdapter";
import { KernelManager } from "../src/kernel/kernelManager";
import { RunStatus, PermissionProfile } from "../src/core/models";
import path from "path";
import { promises as fs } from "fs";

/** Simple demonstration of the library usage. */
async function main() {
  const providerConfig: ProviderConfig = {
    type: "openai",
    endpoint: "https://api.openai.com",
    apiKey: process.env.OPENAI_API_KEY ?? "",
    model: "gpt-4",
  };

  const provider = new ProviderAdapter(providerConfig);
  const kernel = new KernelManager();
  const engine = new AgentEngine(provider, kernel);

  engine.on("event", (e: AgentEvent) => {
    console.log(`Event: ${e.type}`);
    if (e.type === AgentEventType.OBSERVATION) {
      console.log("Result:", e.payload);
    }
  });

  const task: TaskSpec = { description: "Summarize the file data.txt" };
  await engine.run(task);
}

main().catch((err) => {
  console.error("Error running example:", err);
});
