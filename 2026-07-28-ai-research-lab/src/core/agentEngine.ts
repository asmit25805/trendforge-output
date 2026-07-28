import { EventEmitter } from "eventemitter3";
import { ProviderAdapter } from "../providers/providerAdapter";
import { KernelManager, StepResult } from "../kernel/kernelManager";
import { Project, RunStatus, PermissionProfile, Artifact, ArtifactKind } from "./models";
import { randomUUID } from "crypto";

export enum AgentEventType {
  PLANNING = "planning",
  EXECUTION = "execution",
  OBSERVATION = "observation",
}

export interface AgentEvent {
  type: AgentEventType;
  payload: any;
}

export interface TaskSpec {
  description: string;
  parameters?: Record<string, any>;
}

export class AgentEngine extends EventEmitter {
  private provider: ProviderAdapter;
  private kernel: KernelManager;

  constructor(provider: ProviderAdapter, kernel: KernelManager) {
    super();
    this.provider = provider;
    this.kernel = kernel;
  }

  async run(task: TaskSpec): Promise<void> {
    this.emit("event", { type: AgentEventType.PLANNING, payload: task } as AgentEvent);
    const plan = await this.provider.plan(task.description);
    this.emit("event", { type: AgentEventType.EXECUTION, payload: plan } as AgentEvent);
    const result: StepResult = await this.kernel.execute(plan);
    this.emit("event", { type: AgentEventType.OBSERVATION, payload: result } as AgentEvent);
  }
}
