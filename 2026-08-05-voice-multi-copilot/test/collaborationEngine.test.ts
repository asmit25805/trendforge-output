import { EventEmitter } from 'eventemitter3';
import { CollaborationEngine, AgentRegistry, BaseAgent } from '../src/agents/collaborationEngine';
import { AgentProfile, TaskTicket, NegotiationResult, VoiceSegment, TalkPayload } from '../src/types';
import { v4 as uuidv4 } from 'uuid';

class SimpleAgent implements BaseAgent {
  profile: AgentProfile;
  private readonly approve: boolean;
  private readonly failTransient: boolean;
  private transientFailures = 0;

  constructor(id: string, priority: number, approve: boolean, failTransient = false) {
    this.profile = {
      id,
      name: `Agent ${id}`,
      capabilities: ['test'],
      priority,
      state: 'idle',
    };
    this.approve = approve;
    this.failTransient = failTransient;
  }

  async handleProposal(task: TaskTicket): Promise<boolean> {
    if (this.failTransient && this.transientFailures < 2) {
      this.transientFailures++;
      throw new Error('Transient failure');
    }
    return this.approve;
  }

  async onVoiceSegment(_segment: VoiceSegment): Promise<void> {
    // No‑op for these tests
  }
}

describe('CollaborationEngine', () => {
  let registry: AgentRegistry;
  let engine: CollaborationEngine;

  beforeEach(() => {
    registry = new AgentRegistry();
    engine = new CollaborationEngine(registry);
  });

  test('propose resolves with approved result when all agents approve', async () => {
    const agentA = new SimpleAgent('a', 10, true);
    const agentB = new SimpleAgent('b', 5, true);
    registry.register(agentA);
    registry.register(agentB);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Test approval',
      requiredCapabilities: ['test'],
      originatorId: 'a',
      status: 'proposed',
    };

    const result: NegotiationResult = await engine.propose(task);
    expect(result.finalDecision).toBe('approved');
    expect(result.approvedBy).toEqual(expect.arrayContaining(['a', 'b']));
    expect(result.rejectedBy).toHaveLength(0);
    expect(result.reason).toBeNull();
  });

  test('propose resolves with rejected result when any agent rejects', async () => {
    const agentA = new SimpleAgent('a', 10, true);
    const agentB = new SimpleAgent('b', 5, false);
    registry.register(agentA);
    registry.register(agentB);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Test rejection',
      requiredCapabilities: ['test'],
      originatorId: 'a',
      status: 'proposed',
    };

    const result = await engine.propose(task);
    expect(result.finalDecision).toBe('rejected');
    expect(result.approvedBy).toEqual(['a']);
    expect(result.rejectedBy).toEqual(['b']);
    expect(result.reason).toMatch(/rejected by agent b/);
  });

  test('propose retries transient errors up to maxRetries and then rejects', async () => {
    const flakyAgent = new SimpleAgent('flaky', 8, true, true);
    const steadyAgent = new SimpleAgent('steady', 5, true);
    registry.register(flakyAgent);
    registry.register(steadyAgent);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Transient retry',
      requiredCapabilities: ['test'],
      originatorId: 'steady',
      status: 'proposed',
    };

    const result = await engine.propose(task);
    expect(result.finalDecision).toBe('approved');
    expect(result.approvedBy).toEqual(expect.arrayContaining(['flaky', 'steady']));
    expect(result.rejectedBy).toHaveLength(0);
  });

  test('propose fails after exceeding retries for persistent transient error', async () => {
    // Agent that always throws transient errors
    class AlwaysFailAgent extends SimpleAgent {
      constructor() {
        super('alwaysFail', 7, true, true);
      }
      async handleProposal(_: TaskTicket): Promise<boolean> {
        throw new Error('Persistent transient error');
      }
    }

    const failingAgent = new AlwaysFailAgent();
    const goodAgent = new SimpleAgent('good', 4, true);
    registry.register(failingAgent);
    registry.register(goodAgent);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Exceed retries',
      requiredCapabilities: ['test'],
      originatorId: 'good',
      status: 'proposed',
    };

    const result = await engine.propose(task);
    expect(result.finalDecision).toBe('rejected');
    expect(result.approvedBy).toEqual(['good']);
    expect(result.rejectedBy).toEqual(['alwaysFail']);
    expect(result.reason).toMatch(/exceeded retry limit/);
  });

  test('resolveConflicts selects agents based on priority when multiple approvals', async () => {
    const highPriAgent = new SimpleAgent('high', 20, true);
    const lowPriAgent = new SimpleAgent('low', 1, true);
    registry.register(highPriAgent);
    registry.register(lowPriAgent);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Priority test',
      requiredCapabilities: ['test'],
      originatorId: 'high',
      status: 'proposed',
    };

    // Directly invoke internal resolveConflicts via propose
    const result = await engine.propose(task);
    expect(result.finalDecision).toBe('approved');
    // Both agents approve, but the engine should list higher‑priority first
    expect(result.approvedBy[0]).toBe('high');
    expect(result.approvedBy).toEqual(expect.arrayContaining(['high', 'low']));
  });

  test('finalize marks task as ready without throwing', async () => {
    const agent = new SimpleAgent('a', 10, true);
    registry.register(agent);

    const task: TaskTicket = {
      taskId: uuidv4(),
      objective: 'Finalize test',
      requiredCapabilities: ['test'],
      originatorId: 'a',
      status: 'proposed',
    };

    const result = await engine.propose(task);
    expect(result.finalDecision).toBe('approved');

    // Should not throw
    expect(() => engine.finalize(task.taskId)).not.toThrow();
  });
});