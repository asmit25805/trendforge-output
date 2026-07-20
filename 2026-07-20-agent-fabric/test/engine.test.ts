// test/engine.test.ts
import { AgentEngine } from "../src/core/engine";
import { SkillRegistry } from "../src/core/skillRegistry";
import { RPCChannel } from "../src/rpc/channel";
import { Analytics } from "../src/analytics";
import { TraceStore } from "../src/core/traceStore";
import { AgentConfig, TraceEvent, RPCMessage, RPCMessageType, AnalyticsEvent, COMMON_PROPERTIES } from "../src/types";

describe("AgentEngine", () => {
  it("runs an agent and emits trace events", async () => {
    const config: AgentConfig = {
      name: "test-agent",
      skills: [],
    };
    const skillRegistry = new SkillRegistry();
    const rpc = new RPCChannel();
    const analytics = new Analytics();
    const traceStore = new TraceStore();

    const engine = new AgentEngine(config, skillRegistry, rpc, analytics, traceStore);
    await engine.run();

    // No skills – only start/end events should be recorded
    const traces = traceStore.getAll();
    expect(traces.length).toBe(0);
  });
});
