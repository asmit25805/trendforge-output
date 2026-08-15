import { AgentExecutor, RunStatus } from '../src/engine/agent_executor';
import { ScopeKey } from '../src/core/workspace';
import {
  MemoryStore,
  FileStore,
  MemoryEntry,
  FileEntry,
  AgentInput,
  AgentResult,
  ExecutionError,
} from '../src/types';
import { jest } from '@jest/globals';

class InMemoryMemoryStore implements MemoryStore {
  private readonly store = new Map<string, MemoryEntry>();

  async get(key: string): Promise<MemoryEntry | undefined> {
    return this.store.get(key);
  }

  async set(entry: MemoryEntry): Promise<void> {
    this.store.set(entry.key, entry);
  }

  async delete(key: string): Promise<void> {
    this.store.delete(key);
  }
}

class InMemoryFileStore implements FileStore {
  private readonly files = new Map<string, FileEntry>();

  async get(path: string): Promise<FileEntry | undefined> {
    return this.files.get(path);
  }

  async set(entry: FileEntry): Promise<void> {
    this.files.set(entry.path, entry);
  }

  async delete(path: string): Promise<void> {
    this.files.delete(path);
  }
}

describe('AgentExecutor', () => {
  let memoryStore: InMemoryMemoryStore;
  let fileStore: InMemoryFileStore;
  let executor: AgentExecutor;
  const scope = ScopeKey.fromUser('test-user');

  beforeEach(() => {
    memoryStore = new InMemoryMemoryStore();
    fileStore = new InMemoryFileStore();
    executor = new AgentExecutor(memoryStore, fileStore);
  });

  test('run stores output in memory and returns proper result', async () => {
    const mockOutput = 'generated response';
    const executeSpy = jest
      .spyOn<any, any>(executor as any, 'executeWithRetry')
      .mockResolvedValue(mockOutput);

    const input: AgentInput = { prompt: 'hello', metadata: {} };
    const result: AgentResult = await executor.run('dummy-agent', input, scope);

    expect(result.output).toBe(mockOutput);
    expect(result.updatedMemory).toHaveLength(1);
    const storedKey = `${scope.toString()}:lastOutput`;
    const storedEntry = await memoryStore.get(storedKey);
    expect(storedEntry).toBeDefined();
    expect(storedEntry?.value).toBe(mockOutput);
    expect(executeSpy).toHaveBeenCalledTimes(1);
  });

  test('run propagates ExecutionError on fatal failure', async () => {
    const fatalError = new ExecutionError('fatal failure');
    jest
      .spyOn<any, any>(executor as any, 'executeWithRetry')
      .mockRejectedValue(fatalError);

    const input: AgentInput = { prompt: 'fail', metadata: {} };
    await expect(
      executor.run('faulty-agent', input, scope),
    ).rejects.toThrow(ExecutionError);
  });

  test('run retries on transient errors and eventually succeeds', async () => {
    const transientError = new Error('transient network glitch');
    const mockOutput = 'recovered output';
    const execMock = jest
      .spyOn<any, any>(executor as any, 'executeWithRetry')
      .mockRejectedValueOnce(transientError)
      .mockRejectedValueOnce(transientError)
      .mockResolvedValueOnce(mockOutput);

    const input: AgentInput = { prompt: 'retry-test', metadata: {} };
    const result = await executor.run('retry-agent', input, scope);

    expect(result.output).toBe(mockOutput);
    expect(execMock).toHaveBeenCalledTimes(3);
  });

  test('cancel aborts a running execution and sets status to Cancelled', async () => {
    // Simulate a long‑running execution that respects abort signal
    jest
      .spyOn<any, any>(executor as any, 'executeWithRetry')
      .mockImplementation(
        async (
          _agentId: string,
          _input: AgentInput,
          _scope: ScopeKey,
          signal: AbortSignal,
        ): Promise<string> => {
          return new Promise<string>((_, reject) => {
            signal.addEventListener('abort', () => {
              reject(new ExecutionError('aborted by cancel'));
            });
          });
        },
      );

    const runPromise = executor.run('slow-agent', { prompt: 'wait', metadata: {} }, scope);
    // Extract the internal runId from the executor's private map
    const runId = Array.from((executor as any).runs.keys())[0];
    expect((executor as any).runs.get(runId).status).toBe(RunStatus.Running);

    executor.cancel(runId);
    await expect(runPromise).rejects.toThrow(ExecutionError);
    expect((executor as any).runs.get(runId).status).toBe(RunStatus.Cancelled);
  });

  test('status reports correct run state throughout lifecycle', async () => {
    const resolveSignal = new AbortController();
    jest
      .spyOn<any, any>(executor as any, 'executeWithRetry')
      .mockImplementation(
        async (
          _agentId: string,
          _input: AgentInput,
          _scope: ScopeKey,
          _signal: AbortSignal,
        ): Promise<string> => {
          return new Promise<string>((resolve) => {
            setTimeout(() => resolve('final output'), 10);
          });
        },
      );

    const runPromise = executor.run('status-agent', { prompt: 'status', metadata: {} }, scope);
    const runId = Array.from((executor as any).runs.keys())[0];

    // Immediately after start it should be Running
    expect(executor.status(runId)).toBe(RunStatus.Running);

    const result = await runPromise;
    expect(result.output).toBe('final output');
    // After completion the status should be Completed
    expect(executor.status(runId)).toBe(RunStatus.Completed);
  });
});