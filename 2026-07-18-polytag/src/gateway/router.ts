import { EventPayload, Platform, TargetRef, MessageContent, ApprovalPayload, ExecutionContext } from '../types.ts';
import { Engine } from '../engine/engine.ts';
import { AuditLogger } from '../store/knowledgeStore.ts';

/**
 * Minimal interface for platform adapters.
 */
interface ChannelAdapter {
  /** Platform identifier that this adapter handles (e.g., 'slack', 'discord'). */
  readonly platform: string;
  /** Convert a raw webhook/event into a normalized {@link EventPayload}. */
  parseIncoming(raw: any): EventPayload;
  /** Send a message or interactive card back to the originating platform. */
  sendMessage(target: TargetRef, content: MessageContent): Promise<void>;
}

/**
 * Central dispatcher that normalizes incoming platform events,
 * deduplicates them, and forwards them to the {@link Engine}.
 */
export class GatewayRouter {
  private readonly adapters: ChannelAdapter[];
  private engine!: Engine;
  private readonly processedSet: Set<string>;
  private readonly auditLogger: AuditLogger;

  /**
   * @param adapters Array of platform‑specific adapters.
   */
  constructor(adapters: ChannelAdapter[]) {
    this.adapters = adapters;
    this.processedSet = new Set<string>();
    this.auditLogger = new AuditLogger();
  }

  /**
   * Associate the {@link Engine} that will handle deduplicated events.
   */
  public setEngine(engine: Engine): void {
    this.engine = engine;
  }

  /**
   * Emit an interactive approval request on the originating platform.
   *
   * @param taskId Identifier of the task awaiting approval.
   * @param details Payload containing target reference and message content.
   */
  public async emitApprovalRequest(taskId: string, details: ApprovalPayload): Promise<void> {
    const adapter = this.adapters.find(a => a.platform === details.platform);
    if (!adapter) {
      console.error(`GatewayRouter: No adapter found for platform ${details.platform} while emitting approval`);
      return;
    }
    console.log(`GatewayRouter: Emitting approval request for task ${taskId} on ${details.platform}`);
    await adapter.sendMessage(details.target, details.content);
  }

  /**
   * Validate, deduplicate, and route an incoming event to the {@link Engine}.
   *
   * @param event Normalized event payload produced by a {@link ChannelAdapter}.
   */
  public async handleEvent(event: EventPayload): Promise<void> {
    const startTime = Date.now();
    console.log(`GatewayRouter: Received event ${event.platform} ${event.channelId} ${event.userId}`);

    // Basic validation
    if (!event.platform || !event.channelId || !event.userId || !event.text) {
      console.error('GatewayRouter: Invalid event payload, missing required fields');
      await this.sendErrorMessage(event, 'Malformed request: missing required fields.');
      return;
    }

    // Deduplication key
    const dedupKey = `${event.platform}|${event.channelId}|${event.threadId ?? ''}|${event.userId}|${event.timestamp}`;
    if (this.processedSet.has(dedupKey)) {
      console.log('GatewayRouter: Duplicate event detected, skipping processing');
      return;
    }
    this.processedSet.add(dedupKey);

    // Retry logic for transient errors
    const maxAttempts = 3;
    let attempt = 0;
    let lastError: Error | null = null;

    while (attempt < maxAttempts) {
      try {
        console.log(`GatewayRouter: Processing attempt ${attempt + 1} for event`);
        await this.engine.handleEvent(event);
        const duration = Date.now() - startTime;
        console.log(`GatewayRouter: Event processed successfully in ${duration}ms`);
        await this.auditLogger.logRun({
          runId: event.timestamp.toString(),
          runtimeId: 'router',
          startTime,
          endTime: Date.now(),
          status: 'success',
          output: null,
          errorMessage: null,
          approvalId: null,
        });
        return;
      } catch (err) {
        const error = err as Error & { transient?: boolean };
        console.error(`GatewayRouter: Error during processing: ${error.message}`);
        lastError = error;
        if (!error.transient) {
          // Fatal error – log and notify user
          await this.handleFatalError(event, error);
          return;
        }
        // Transient error – exponential back‑off
        const backoff = 100 * Math.pow(2, attempt);
        console.log(`GatewayRouter: Transient error, retrying after ${backoff}ms`);
        await new Promise(res => setTimeout(res, backoff));
        attempt += 1;
      }
    }

    // All retries exhausted
    console.error('GatewayRouter: All retry attempts failed');
    await this.sendErrorMessage(event, 'Temporary failure, please retry later.');
    await this.auditLogger.logRun({
      runId: event.timestamp.toString(),
      runtimeId: 'router',
      startTime,
      endTime: Date.now(),
      status: 'error',
      output: null,
      errorMessage: lastError?.message ?? 'Unknown error',
      approvalId: null,
    });
  }

  /** Send a concise error message back to the user on the originating platform. */
  private async sendErrorMessage(event: EventPayload, message: string): Promise<void> {
    const adapter = this.adapters.find(a => a.platform === event.platform);
    if (!adapter) {
      console.error(`GatewayRouter: No adapter to send error message for platform ${event.platform}`);
      return;
    }
    const target: TargetRef = {
      channelId: event.channelId,
      threadId: event.threadId ?? undefined,
    };
    const content: MessageContent = { text: message };
    await adapter.sendMessage(target, content);
  }

  /** Handle non‑transient (fatal) errors: log and inform the user. */
  private async handleFatalError(event: EventPayload, error: Error): Promise<void> {
    console.error(`GatewayRouter: Fatal error for event ${event.timestamp}: ${error.message}`);
    await this.sendErrorMessage(event, `Error: ${error.message}`);
    await this.auditLogger.logRun({
      runId: event.timestamp.toString(),
      runtimeId: 'router',
      startTime: Date.now(),
      endTime: Date.now(),
      status: 'cancelled',
      output: null,
      errorMessage: error.message,
      approvalId: null,
    });
  }
}