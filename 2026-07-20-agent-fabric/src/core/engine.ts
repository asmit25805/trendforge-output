// src/core/engine.ts
import { EventEmitter } from "events";
import { v4 as uuidv4 } from "uuid";
import {
  AgentConfig,
  TraceEvent,
  TelemetryRecord,
  RPCMessage,
  RPCMessageType,
  RunRequestPayload,
  COMMON_PROPERTIES,
} from "../types";
import { SkillRegistry } from "./skillRegistry";
import { RPCChannel } from "../rpc/channel";
import { Analytics } from "../analytics";
import { TraceStore } from "./traceStore";

/**
 * Core engine that runs an agent based on a supplied configuration.
 */
export class AgentEngine extends EventEmitter {
  private config: AgentConfig;
  private skillRegistry: SkillRegistry;
  private rpcChannel: RPCChannel;
  private analytics: Analytics;
  private traceStore: TraceStore;

  constructor(
    config: AgentConfig,
    skillRegistry: SkillRegistry,
    rpcChannel: RPCChannel,
    analytics: Analytics,
    traceStore: TraceStore,
  ) {
    super();
    this.config = config;
    this.skillRegistry = skillRegistry;
    this.rpcChannel = rpcChannel;
    this.analytics = analytics;
    this.traceStore = traceStore;
  }

  /** Run the agent – loads skills, executes them, and emits trace events. */
  async run(): Promise<void> {
    this.emit("start", this.config);
    this.analytics.captureEvent({
      name: "agent_start",
      properties: { ...COMMON_PROPERTIES, agentName: this.config.name },
    });

    for (const skillName of this.config.skills) {
      const skillInfo = this.skillRegistry.getSkillInfo(skillName);
      if (!skillInfo) {
        const err = new Error(`Skill not found: ${skillName}`);
        this.emit("error", err);
        continue;
      }
      const result = await Promise.resolve(skillInfo.definition.execute(this.config));
      const trace: TraceEvent = {
        timestamp: Date.now(),
        event: "skill_executed",
        data: { skill: skillName, result },
      };
      this.traceStore.add(trace);
      this.rpcChannel.send({
        id: uuidv4(),
        type: RPCMessageType.EVENT,
        payload: trace,
      });
    }

    this.emit("end", this.config);
    this.analytics.captureEvent({
      name: "agent_end",
      properties: { ...COMMON_PROPERTIES, agentName: this.config.name },
    });
  }
}

/**
 * Convenience helper that creates an engine and runs it.
 */
export async function runAgent(config: AgentConfig): Promise<void> {
  const skillRegistry = new SkillRegistry();
  const rpcChannel = new RPCChannel();
  const analytics = new Analytics();
  const traceStore = new TraceStore();
  const engine = new AgentEngine(config, skillRegistry, rpcChannel, analytics, traceStore);
  await engine.run();
}
