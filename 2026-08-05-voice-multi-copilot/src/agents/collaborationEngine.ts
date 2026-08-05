import { EventEmitter } from 'eventemitter3';
import { Database, verbose } from 'sqlite3';
import {
  AgentProfile,
  AgentState,
  TaskTicket,
  TaskStatus,
  NegotiationResult,
  Decision,
} from '../types';

/**
 * Minimal interface that every agent must implement.
 */
export interface BaseAgent {
  /** Agent's descriptive profile */
  profile: AgentProfile;
  /**
   * Called when the CollaborationEngine receives a voice segment.
   * Should return a NegotiationResult indicating the agent's decision.
   */
  handleSegment(segment: any): Promise<NegotiationResult>;
}

/**
 * Simple registry that keeps track of active agents.
 * Provides methods to register and unregister agents at runtime.
 */
export class AgentRegistry extends EventEmitter {
  private agents: Map<string, BaseAgent> = new Map();

  /** Register a new agent */
  registerAgent(agent: BaseAgent): void {
    this.agents.set(agent.profile.id, agent);
    this.emit('agent-registered', agent);
  }

  /** Unregister an existing agent */
  unregisterAgent(agentId: string): void {
    const removed = this.agents.delete(agentId);
    if (removed) this.emit('agent-unregistered', agentId);
  }

  /** Get a list of all registered agents */
  getAgents(): BaseAgent[] {
    return Array.from(this.agents.values());
  }
}

/**
 * Core engine that coordinates negotiation between agents.
 */
export class CollaborationEngine {
  private registry: AgentRegistry;
  private runtime: any; // RuntimeConnector type is imported lazily to avoid circular deps

  constructor(registry: AgentRegistry, runtime: any) {
    this.registry = registry;
    this.runtime = runtime;
  }

  /**
   * Run negotiation for a given voice segment.
   * Returns the first accepted NegotiationResult or a default rejection.
   */
  async negotiate(segment: any): Promise<NegotiationResult> {
    const agents = this.registry.getAgents();
    for (const agent of agents) {
      const result = await agent.handleSegment(segment);
      if (result.decision === 'accept') {
        // Forward the task ticket to the runtime for execution
        await this.runtime.sendTask(result.ticket);
        return result;
      }
    }
    // No agent accepted the segment
    return { decision: 'reject', ticket: null } as NegotiationResult;
  }
}
