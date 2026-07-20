// examples/simple-agent.ts
import { AgentEngine } from "../src/core/engine";
import { SkillRegistry } from "../src/core/skillRegistry";
import { TraceStore } from "../src/core/traceStore";
import { RPCChannel } from "../src/rpc/channel";
import { Analytics } from "../src/analytics";
import { AgentConfig } from "../src/types";

// Define a simple agent configuration that uses a built‑in example skill.
const config: AgentConfig = {
  name: "simple-agent",
  skills: [], // No external skills for this minimal example
};

const skillRegistry = new SkillRegistry();
const rpcChannel = new RPCChannel();
const analytics = new Analytics();
const traceStore = new TraceStore();

const engine = new AgentEngine(config, skillRegistry, rpcChannel, analytics, traceStore);
engine.run().then(() => {
  console.log("Agent finished execution. Trace events:");
  console.log(traceStore.getAll());
});
