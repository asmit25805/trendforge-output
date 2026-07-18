import { PolicyEngine } from '../src/store/knowledgeStore.ts';
import {
  TaskDefinition,
  ExecutionContext,
  PolicyDecision,
  PolicyRule,
  Platform,
  ProjectRef,
} from '../src/types.ts';

describe('PolicyEngine', () => {
  const baseContext: ExecutionContext = {
    platform: Platform.Slack,
    channelId: 'C123',
    userId: 'U456',
    timestamp: Date.now(),
  };

  const baseTask: TaskDefinition = {
    taskId: 'task-1',
    prompt: 'Summarize the channel discussion',
    requiredCapabilities: [],
    projectRef: { projectId: 'proj-1' },
    knowledgeVersion: 0,
  };

  class AllowAllRule implements PolicyRule {
    evaluate(_task: TaskDefinition, _ctx: ExecutionContext): PolicyDecision {
      return { allow: true, requiresApproval: false, reason: 'allow all' };
    }
  }

  class ApprovalRequiredRule implements PolicyRule {
    evaluate(_task: TaskDefinition, _ctx: ExecutionContext): PolicyDecision {
      return {
        allow: true,
        requiresApproval: true,
        reason: 'requires manager approval',
      };
    }
  }

  class DenyAllRule implements PolicyRule {
    evaluate(_task: TaskDefinition, _ctx: ExecutionContext): PolicyDecision {
      return { allow: false, requiresApproval: false, reason: 'policy deny' };
    }
  }

  class CapabilityRule implements PolicyRule {
    private readonly requiredCap: string;
    constructor(requiredCap: string) {
      this.requiredCap = requiredCap;
    }
    evaluate(task: TaskDefinition, _ctx: ExecutionContext): PolicyDecision {
      const hasCap = task.requiredCapabilities.includes(this.requiredCap);
      return {
        allow: hasCap,
        requiresApproval: false,
        reason: hasCap ? 'capability satisfied' : 'missing capability',
      };
    }
  }

  test('allows task when no rules are registered', async () => {
    const engine = new PolicyEngine();
    const decision = await engine.evaluate(baseTask, baseContext);
    expect(decision).toMatchObject({
      allow: true,
      requiresApproval: false,
    });
  });

  test('requires approval when a rule signals approval', async () => {
    const engine = new PolicyEngine();
    engine.registerRule(new ApprovalRequiredRule());
    const decision = await engine.evaluate(baseTask, baseContext);
    expect(decision).toMatchObject({
      allow: true,
      requiresApproval: true,
      reason: expect.stringContaining('approval'),
    });
  });

  test('denies task when a rule denies', async () => {
    const engine = new PolicyEngine();
    engine.registerRule(new DenyAllRule());
    const decision = await engine.evaluate(baseTask, baseContext);
    expect(decision).toMatchObject({
      allow: false,
      requiresApproval: false,
      reason: expect.stringContaining('deny'),
    });
  });

  test('combines multiple rules: denial overrides approval', async () => {
    const engine = new PolicyEngine();
    engine.registerRule(new ApprovalRequiredRule());
    engine.registerRule(new DenyAllRule());
    const decision = await engine.evaluate(baseTask, baseContext);
    expect(decision.allow).toBe(false);
    expect(decision.requiresApproval).toBe(false);
    expect(decision.reason).toContain('deny');
  });

  test('capability rule blocks execution when required capability missing', async () => {
    const engine = new PolicyEngine();
    engine.registerRule(new CapabilityRule('network'));
    const taskWithoutCap = { ...baseTask, requiredCapabilities: [] };
    const decision = await engine.evaluate(taskWithoutCap, baseContext);
    expect(decision.allow).toBe(false);
    expect(decision.reason).toContain('missing capability');
  });

  test('capability rule allows execution when capability present', async () => {
    const engine = new PolicyEngine();
    engine.registerRule(new CapabilityRule('network'));
    const taskWithCap = {
      ...baseTask,
      requiredCapabilities: ['network'],
    };
    const decision = await engine.evaluate(taskWithCap, baseContext);
    expect(decision.allow).toBe(true);
    expect(decision.reason).toContain('satisfied');
  });

  test('registerRule affects subsequent evaluations', async () => {
    const engine = new PolicyEngine();
    // First evaluation with no rules
    const first = await engine.evaluate(baseTask, baseContext);
    expect(first.allow).toBe(true);

    // Register a denying rule
    engine.registerRule(new DenyAllRule());

    const second = await engine.evaluate(baseTask, baseContext);
    expect(second.allow).toBe(false);
    expect(second.reason).toContain('deny');
  });
});