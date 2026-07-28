import { AgentEngine, TaskSpec, AgentEventType } from "../src/core/agentEngine";
import { ProviderAdapter, ProviderError, ChatResponse } from "../src/providers/providerAdapter";
import { KernelManager, StepResult, KernelError } from "../src/kernel/kernelManager";
import { RunStatus, PermissionProfile } from "../src/core/models";
import { promises as fsPromises } from "fs";

describe("AgentEngine", () => {
  it("should emit planning, execution, and observation events", async () => {
    const provider = new ProviderAdapter({
      type: "openai",
      endpoint: "https://api.openai.com",
      apiKey: "test-key",
      model: "gpt-4",
    });
    const kernel = new KernelManager();
    const engine = new AgentEngine(provider, kernel);

    const events: AgentEventType[] = [];
    engine.on("event", (e) => events.push(e.type));

    const task: TaskSpec = { description: "Echo hello" };
    await engine.run(task);

    expect(events).toEqual([
      AgentEventType.PLANNING,
      AgentEventType.EXECUTION,
      AgentEventType.OBSERVATION,
    ]);
  });
});
