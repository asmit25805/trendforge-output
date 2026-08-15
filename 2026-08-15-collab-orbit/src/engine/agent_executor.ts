import { createHash, randomUUID } from 'crypto';
import { logger } from '../utils/logger';
import retry from 'p-retry';
import {
  MemoryStore,
  FileStore,
  AgentInput,
  AgentResult,
  MemoryEntry,
  FileEntry,
  ScopeKey,
} from '../types';
import {
  ConfigError,
  ProviderError,
  ExecutionError,
} from '../core/workspace';

/**
 * Possible run states for an agent execution.
 */
export enum RunStatus {
  Pending = 'pending',
  Running = 'running',
  Completed = 'completed',
  Failed = 'failed',
}

/**
 * Executes an agent within a given workspace.
 */
export class AgentExecutor {
  constructor(
    private readonly memoryStore: MemoryStore,
    private readonly fileStore: FileStore,
  ) {}

  /** Run an agent with the supplied input. */
  async run(input: AgentInput): Promise<AgentResult> {
    const runId = randomUUID();
    logger.info(`Starting agent run ${runId}`);

    // Store the prompt in memory for traceability
    const promptEntry: MemoryEntry = {
      key: `prompt:${runId}`,
      value: input.prompt,
      createdAt: Date.now(),
    };
    await this.memoryStore.set(promptEntry);

    // Simulate execution with retry logic (replace with real LLM call as needed)
    const result = await retry(
      async () => {
        if (!input.prompt) {
          throw new ExecutionError('Prompt cannot be empty');
        }
        return { output: `Echo: ${input.prompt}` } as AgentResult;
      },
      { retries: 2 },
    );

    // Store the result in memory
    const resultEntry: MemoryEntry = {
      key: `result:${runId}`,
      value: result,
      createdAt: Date.now(),
    };
    await this.memoryStore.set(resultEntry);

    logger.info(`Agent run ${runId} completed`);
    return result;
  }
}

/**
 * Convenience function to run an agent without manually constructing the executor.
 */
export async function runAgent(
  memoryStore: MemoryStore,
  fileStore: FileStore,
  input: AgentInput,
): Promise<AgentResult> {
  const executor = new AgentExecutor(memoryStore, fileStore);
  return executor.run(input);
}
