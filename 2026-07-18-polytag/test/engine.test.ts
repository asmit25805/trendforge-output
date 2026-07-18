import { Engine } from '../src/engine/engine';
import { GatewayRouter } from '../src/gateway/router';
import { PolicyEngine } from '../src/store/knowledgeStore';
import { TaskRouter } from '../src/store/knowledgeStore';
import { KnowledgeStore } from '../src/store/knowledgeStore';
import { AuditLogger } from '../src/store/knowledgeStore';
import { RuntimeAdapter } from '../src/runtime/runtimeAdapter';
import {
  EventPayload,
  Platform,
  ExecutionContext,
  TaskDefinition,
  ProjectRef,
  ApprovalPayload,
  PolicyDecision,
  AuditRecord,
} from '../src/types';

describe('Engine', () => {
  const mockRouter = {
    emitApprovalRequest: jest.fn(),
    sendMessage: jest.fn(),
  } as unknown as GatewayRouter;

  const mockPolicyEngine = {
    evaluate: jest.fn(),
  } as unknown as PolicyEngine;

  const mockTaskRouter = {
    selectRuntime: jest.fn(),
  } as unknown as TaskRouter;

  const mockKnowledgeStore = {
    getFacts: jest.fn(),
    appendFact: jest.fn(),
  } as unknown as KnowledgeStore;

  const mockAuditLogger = {
    getRecord: jest.fn(),
    insertRecord: jest.fn(),
  } as unknown as AuditLogger;

  const mockRuntime: RuntimeAdapter = {
    supportsCapability: jest.fn(),
    execute: jest.fn(),
  };

  const baseEvent: EventPayload = {
    platform: Platform.Slack,
    channelId: 'C123',
    threadId: null,
    userId: 'U456',
    text: 'Explain the project status',
    timestamp: Date.now(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    // Default mocks
    mockAuditLogger.getRecord.mockResolvedValue(undefined);
    mockKnowledgeStore.getFacts.mockResolvedValue([]);
    mockPolicyEngine.evaluate.mockResolvedValue({
      allow: true,
      requiresApproval: false,
      reason: '',
    } as PolicyDecision);
    mockTaskRouter.selectRuntime.mockReturnValue(mockRuntime);
    mockRuntime.execute.mockResolvedValue({
      output: 'Result',
      error: null,
      metadata: { durationMs: 10 },
    });
  });

  test('engine processes a successful task flow', async () => {
    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    await engine.handleEvent(baseEvent);

    expect(mockKnowledgeStore.getFacts).toHaveBeenCalledWith({
      projectId: baseEvent.channelId,
      channelId: baseEvent.channelId,
    });
    expect(mockPolicyEngine.evaluate).toHaveBeenCalled();
    expect(mockTaskRouter.selectRuntime).toHaveBeenCalled();
    expect(mockRuntime.execute).toHaveBeenCalled();
    expect(mockAuditLogger.insertRecord).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'success',
        output: 'Result',
      }),
    );
    expect(mockRouter.sendMessage).toHaveBeenCalled();
  });

  test('engine skips duplicate tasks based on audit log', async () => {
    const duplicateRecord: AuditRecord = {
      runId: 'duplicate-id',
      runtimeId: 'runtime',
      startTime: 0,
      endTime: 0,
      status: 'success',
      output: 'old',
      errorMessage: null,
      approvalId: null,
    };
    mockAuditLogger.getRecord.mockResolvedValue(duplicateRecord);

    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    await engine.handleEvent(baseEvent);

    expect(mockAuditLogger.getRecord).toHaveBeenCalled();
    expect(mockKnowledgeStore.getFacts).not.toHaveBeenCalled();
    expect(mockRouter.sendMessage).not.toHaveBeenCalled();
  });

  test('engine retries on transient runtime errors', async () => {
    const error = new Error('Transient failure');
    mockRuntime.execute
      .mockRejectedValueOnce(error)
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce({
        output: 'Recovered',
        error: null,
        metadata: { durationMs: 5 },
      });

    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    await engine.handleEvent(baseEvent);

    expect(mockRuntime.execute).toHaveBeenCalledTimes(3);
    expect(mockAuditLogger.insertRecord).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'success',
        output: 'Recovered',
      }),
    );
    expect(mockRouter.sendMessage).toHaveBeenCalled();
  });

  test('engine records failure after max retries', async () => {
    const error = new Error('Persistent failure');
    mockRuntime.execute.mockRejectedValue(error);

    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    await engine.handleEvent(baseEvent);

    expect(mockRuntime.execute).toHaveBeenCalledTimes(3);
    expect(mockAuditLogger.insertRecord).toHaveBeenCalledWith(
      expect.objectContaining({
        status: 'error',
        errorMessage: expect.stringContaining('Persistent failure'),
      }),
    );
    expect(mockRouter.sendMessage).toHaveBeenCalled();
  });

  test('engine initiates approval flow when policy requires it', async () => {
    const approvalDecision: PolicyDecision = {
      allow: false,
      requiresApproval: true,
      reason: 'Sensitive operation',
    };
    mockPolicyEngine.evaluate.mockResolvedValue(approvalDecision);

    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    // Start handling event (will pause awaiting approval)
    const handlePromise = engine.handleEvent(baseEvent);

    // Wait a tick to ensure approval request emitted
    await new Promise(process.nextTick);
    expect(mockRouter.emitApprovalRequest).toHaveBeenCalled();

    // Resolve approval manually
    const pending = (engine as any).pendingApprovals;
    const taskId = Object.keys(pending)[0];
    pending[taskId].resolve(true);
    clearTimeout(pending[taskId].timeoutId);

    await handlePromise;

    expect(mockRuntime.execute).toHaveBeenCalled();
    expect(mockAuditLogger.insertRecord).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'success' }),
    );
  });

  test('engine cancels task when approval times out', async () => {
    jest.useFakeTimers();

    const approvalDecision: PolicyDecision = {
      allow: false,
      requiresApproval: true,
      reason: 'Requires manager sign‑off',
    };
    mockPolicyEngine.evaluate.mockResolvedValue(approvalDecision);

    const engine = new Engine(
      mockRouter,
      mockPolicyEngine,
      mockTaskRouter,
      mockKnowledgeStore,
      mockAuditLogger,
      [mockRuntime],
    );

    const handlePromise = engine.handleEvent(baseEvent);
    await new Promise(process.nextTick);
    expect(mockRouter.emitApprovalRequest).toHaveBeenCalled();

    // Fast‑forward timeout (5 min = 300 000 ms)
    jest.advanceTimersByTime(300_000);

    await handlePromise;

    expect(mockRuntime.execute).not.toHaveBeenCalled();
    expect(mockAuditLogger.insertRecord).toHaveBeenCalledWith(
      expect.objectContaining({ status: 'cancelled' }),
    );
    expect(mockRouter.sendMessage).toHaveBeenCalled();

    jest.useRealTimers();
  });
});