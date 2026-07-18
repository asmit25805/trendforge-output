import { randomUUID } from 'crypto';
import {
  EventPayload,
  ExecutionContext,
  TaskDefinition,
  ProjectRef,
  Platform,
  TargetRef,
  MessageContent,
  ApprovalPayload,
  PolicyDecision,
  AuditRecord,
} from '../types.ts';
import { GatewayRouter } from '../gateway/router.ts';
import { RuntimeAdapter } from '../runtime/runtimeAdapter.ts';
import {
  KnowledgeStore,
  AuditLogger,
  PolicyEngine,
  TaskRouter,
} from '../store/knowledgeStore.ts';

/**
 * Core orchestrator that drives the lifecycle of a task from an incoming event
 * through policy evaluation, optional approval, runtime execution and audit
 * logging.
 */
export class Engine {
  /** Map of pending approval promises keyed by taskId. */
  private readonly pendingApprovals: Map<
    string,
    {
      resolve: (approved: boolean) => void;
      reject: (err: Error) => void;
      timeoutId: NodeJS.Timeout;
    }
  > = new Map();

  /**
   * Construct a new Engine.
   *
   * @param router        Central dispatcher used for sending messages and
   *                      registering task‑target relationships.
   * @param policyEngine  Evaluates policy rules before execution.
   * @param taskRouter    Selects the cheapest capable runtime.
   * @param knowledgeStore Provides knowledge snapshots and fact persistence.
   * @param auditLogger   Persists immutable run records.
   * @param runtimeAdapters Available runtime adapters.
   */
  constructor(
    private readonly router: GatewayRouter,
    private readonly policyEngine: PolicyEngine,
    private readonly taskRouter: TaskRouter,
    private readonly knowledgeStore: KnowledgeStore,
    private readonly auditLogger: AuditLogger,
    private readonly runtimeAdapters: RuntimeAdapter[],
  ) {}

  /**
   * Entry point invoked by {@link GatewayRouter} after deduplication.
   *
   * @param event Normalized platform event.
   */
  public async handleEvent(event: EventPayload): Promise<void> {
    console.log(`Engine: handling event ${event.platform} ${event.channelId}`);

    const context: ExecutionContext = {
      platform: event.platform,
      channelId: event.channelId,
      userId: event.userId,
      timestamp: event.timestamp,
    };

    const taskId = randomUUID();
    const projectRef: ProjectRef = { projectId: event.channelId };
    const task: TaskDefinition = {
      taskId,
      prompt: event.text,
      requiredCapabilities: [], // Filled later by policy if needed
      projectRef,
      knowledgeVersion: 0, // Will be set after snapshot
    };

    // Preserve idempotency – abort if a record already exists.
    const existing = await this.auditLogger.getRecord(taskId);
    if (existing) {
      console.log(`Engine: duplicate task ${taskId} detected, skipping`);
      return;
    }

    // Capture knowledge snapshot and embed version.
    const facts = await this.knowledgeStore.getFacts({
      projectId: projectRef.projectId,
      channelId: event.channelId,
    });
    task.knowledgeVersion = facts.length > 0 ? facts[0].version : 0;

    // Policy evaluation.
    const decision = await this.policyEngine.evaluate(task, context);
    if (!decision.allow && !decision.requiresApproval) {
      await this.failTask(
        task,
        context,
        `Policy denied execution: ${decision.reason}`,
      );
      return;
    }

    // Register target for later response messages.
    const target: TargetRef = {
      platform: event.platform,
      channelId: event.channelId,
      threadId: event.threadId,
    };
    this.router.registerTaskTarget(taskId, target);

    // If approval is required, emit request and await response.
    if (decision.requiresApproval) {
      const approvalPayload: ApprovalPayload = {
        taskId,
        requesterId: event.userId,
        details: decision.reason,
      };
      this.router.emitApprovalRequest(taskId, approvalPayload);
      const approved = await this.waitForApproval(taskId);
      if (!approved) {
        await this.cancelTask(task, context, 'Approval timeout or denial');
        return;
      }
    }

    // Runtime selection.
    const runtime = this.taskRouter.selectRuntime(task, this.runtimeAdapters);
    if (!runtime) {
      await this.failTask(
        task,
        context,
        'No suitable runtime found for required capabilities',
      );
      return;
    }

    // Execute with retry logic.
    const executionResult = await this.executeWithRetries(
      runtime,
      task,
      context,
    );

    // Record audit entry.
    const auditRecord: AuditRecord = {
      runId: task.taskId,
      runtimeId: (runtime as any).name ?? 'unknown',
      startTime: executionResult.startTime,
      endTime: executionResult.endTime,
      status: executionResult.error ? 'error' : 'success',
      output: executionResult.output ?? null,
      errorMessage: executionResult.error?.message ?? null,
      approvalId: null,
    };
    await this.auditLogger.logRun(auditRecord);

    // Send final response back to the originating channel.
    const responseContent: MessageContent = {
      text:
        executionResult.error && executionResult.error.isTransient
          ? 'Temporary failure, please retry later.'
          : executionResult.error
          ? `Error: ${executionResult.error.message}`
          : executionResult.output ?? '',
    };
    await this.router.sendMessage(target, responseContent);
  }

  /**
   * Called by external approval UI to resolve a pending approval.
   *
   * @param taskId   Identifier of the task awaiting approval.
   * @param approved True if the user approved, false otherwise.
   */
  public resolveApproval(taskId: string, approved: boolean): void {
    const pending = this.pendingApprovals.get(taskId);
    if (!pending) {
      console.warn(`Engine: no pending approval for task ${taskId}`);
      return;
    }
    clearTimeout(pending.timeoutId);
    pending.resolve(approved);
    this.pendingApprovals.delete(taskId);
  }

  /** Waits for an approval decision or times out after 5 minutes. */
  private waitForApproval(taskId: string): Promise<boolean> {
    return new Promise<boolean>((resolve, reject) => {
      const timeoutId = setTimeout(() => {
        this.pendingApprovals.delete(taskId);
        resolve(false);
      }, 5 * 60 * 1000); // 5 minutes

      this.pendingApprovals.set(taskId, { resolve, reject, timeoutId });
    });
  }

  /** Executes a task with exponential back‑off retries for transient errors. */
  private async executeWithRetries(
    runtime: RuntimeAdapter,
    task: TaskDefinition,
    context: ExecutionContext,
  ): Promise<{
    startTime: number;
    endTime: number;
    output?: string;
    error?: Error & { isTransient?: boolean };
  }> {
    const maxAttempts = 3;
    let attempt = 0;
    let backoff = 500; // milliseconds

    while (attempt < maxAttempts) {
      attempt += 1;
      const startTime = Date.now();
      try {
        console.log(
          `Engine: executing task ${task.taskId} (attempt ${attempt})`,
        );
        const result = await runtime.execute(task, context);
        const endTime = Date.now();
        return {
          startTime,
          endTime,
          output: result.output,
        };
      } catch (err: any) {
        const endTime = Date.now();
        const isTransient = err.isTransient ?? false;
        console.error(
          `Engine: execution error on attempt ${attempt}: ${err.message}`,
        );
        if (!isTransient || attempt === maxAttempts) {
          return { startTime, endTime, error: err };
        }
        // Transient – wait before retrying.
        await new Promise((res) => setTimeout(res, backoff));
        backoff *= 2;
      }
    }
    // Should never reach here.
    return { startTime: Date.now(), endTime: Date.now() };
  }

  /** Helper to log a cancelled task and notify the user. */
  private async cancelTask(
    task: TaskDefinition,
    context: ExecutionContext,
    reason: string,
  ): Promise<void> {
    console.log(`Engine: cancelling task ${task.taskId} – ${reason}`);
    const auditRecord: AuditRecord = {
      runId: task.taskId,
      runtimeId: '',
      startTime: Date.now(),
      endTime: Date.now(),
      status: 'cancelled',
      output: null,
      errorMessage: reason,
      approvalId: null,
    };
    await this.auditLogger.logRun(auditRecord);
    const target = this.router['taskTargetMap'].get(task.taskId);
    if (target) {
      await this.router.sendMessage(target, { text: `Task cancelled: ${reason}` });
    }
  }

  /** Helper to log a failed task and notify the user. */
  private async failTask(
    task: TaskDefinition,
    context: ExecutionContext,
    errorMessage: string,
  ): Promise<void> {
    console.log(`Engine: failing task ${task.taskId} – ${errorMessage}`);
    const auditRecord: AuditRecord = {
      runId: task.taskId,
      runtimeId: '',
      startTime: Date.now(),
      endTime: Date.now(),
      status: 'error',
      output: null,
      errorMessage,
      approvalId: null,
    };
    await this.auditLogger.logRun(auditRecord);
    const target = this.router['taskTargetMap'].get(task.taskId);
    if (target) {
      await this.router.sendMessage(target, { text: `Error: ${errorMessage}` });
    }
  }
}