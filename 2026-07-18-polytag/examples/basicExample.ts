import { randomUUID } from 'crypto';
import { GatewayRouter } from '../src/gateway/router.ts';
import { DiscordAdapter } from '../src/channel/discordAdapter.ts';
import { Engine } from '../src/engine/engine.ts';
import {
  KnowledgeStore,
  AuditLogger,
  PolicyEngine,
  TaskRouter,
} from '../src/store/knowledgeStore.ts';
import { RuntimeAdapter } from '../src/runtime/runtimeAdapter.ts';
import {
  EventPayload,
  Platform,
  ExecutionContext,
  TaskDefinition,
  ProjectRef,
  MessageContent,
  TargetRef,
  ApprovalPayload,
  PolicyDecision,
  AuditRecord,
} from '../src/types.ts';

/**
 * Simple RuntimeAdapter that echoes the task prompt.
 * All capabilities are reported as supported.
 */
class EchoRuntime implements RuntimeAdapter {
  supportsCapability(_cap: string): boolean {
    console.log('EchoRuntime: checking capability support');
    return true;
  }

  async execute(
    task: TaskDefinition,
    _context: ExecutionContext,
  ): Promise<{
    output: string;
    error: string | null;
    metadata: { durationMs: number };
  }> {
    console.log(`EchoRuntime: executing task ${task.taskId}`);
    const start = Date.now();
    const output = `Echo response: ${task.prompt}`;
    const duration = Date.now() - start;
    console.log(`EchoRuntime: completed in ${duration}ms`);
    return { output, error: null, metadata: { durationMs: duration } };
  }
}

/**
 * Demonstrates wiring DiscordAdapter, GatewayRouter, and Engine.
 * The example processes a single Discord thread message and logs the
 * result. It can be run with `npx ts-node examples/basicExample.ts`.
 */
async function main(): Promise<void> {
  console.log('basicExample: initializing components');

  // Platform‑specific adapter
  const discordAdapter = new DiscordAdapter();

  // Central router that will forward events to the Engine
  const router = new GatewayRouter([discordAdapter]);

  // Core services
  const knowledgeStore = await KnowledgeStore.getInstance();
  const auditLogger = new AuditLogger();
  const policyEngine = new PolicyEngine();
  const taskRouter = new TaskRouter();

  // Runtime that simply echoes the prompt
  const echoRuntime = new EchoRuntime();

  // Engine orchestrates the full task lifecycle
  const engine = new Engine(
    router,
    policyEngine,
    taskRouter,
    knowledgeStore,
    auditLogger,
    [echoRuntime],
  );

  // Connect router to engine – the router calls `engine.handleEvent`
  // for each deduplicated payload.
  router.setEngine(engine);

  // Simulated incoming Discord event
  const event: EventPayload = {
    platform: Platform.Discord,
    channelId: 'discord-channel-1',
    threadId: null,
    userId: 'user-123',
    text: 'What is the current project status?',
    timestamp: Date.now(),
  };

  console.log('basicExample: sending simulated event to router');
  await router.handleEvent(event);

  console.log('basicExample: processing complete');
}

// Execute the example and handle unexpected errors
main().catch((err: Error) => {
  console.error('basicExample: fatal error', err);
  process.exit(1);
});