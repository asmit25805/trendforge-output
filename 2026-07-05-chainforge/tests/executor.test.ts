import { describe, expect, test, beforeEach, jest } from '@jest/globals';
import { CatalogStore } from '../src/catalog/store.ts';
import { ChainExecutor, StepPreview } from '../src/executor/engine.ts';
import {
  ChainDefinition,
  ExecutionResult,
  StepResult,
  ChainRecord,
  ChainVersionRecord,
} from '../src/types.ts';
import { Sandbox } from '../src/executor/engine.ts';

/**
 * Helper to build a minimal chain definition with deterministic step behavior.
 */
function buildChainDef(slug: string, versionSuffix = ''): ChainDefinition {
  return {
    slug,
    title: `Test Chain ${slug}${versionSuffix}`,
    description: 'Chain used for executor unit tests',
    status: 'draft',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    steps: [
      {
        id: `step1${versionSuffix}`,
        type: 'script',
        payload: 'return context.input + 1;',
        inputSchema: {
          type: 'object',
          properties: { input: { type: 'number' } },
          required: ['input'],
        },
        outputSchema: { type: 'number' },
      },
      {
        id: `step2${versionSuffix}`,
        type: 'script',
        payload: 'return context.prev * 2;',
        inputSchema: {
          type: 'object',
          properties: { prev: { type: 'number' } },
          required: ['prev'],
        },
        outputSchema: { type: 'number' },
      },
    ],
  };
}

/**
 * Computes a simple SHA‑256 hash of a JSON‑serializable value.
 * Used to verify deterministic hashing performed by ChainExecutor.
 */
function computeHash(value: unknown): string {
  const { createHash } = await import('crypto');
  return createHash('sha256')
    .update(JSON.stringify(value))
    .digest('hex');
}

describe('ChainExecutor', () => {
  let store: CatalogStore;
  let executor: ChainExecutor;

  beforeEach(() => {
    // Initialise a fresh in‑memory catalog for each test.
    store = new CatalogStore(':memory:');
    executor = new ChainExecutor(store);
  });

  test('preview returns step previews matching the stored definition', async () => {
    const def = buildChainDef('preview-chain');
    const record = await store.createChain(def);
    const previews: StepPreview[] = await executor.preview(record.chainSlug);
    expect(previews).toHaveLength(def.steps.length);
    for (let i = 0; i < def.steps.length; i++) {
      expect(previews[i].id).toBe(def.steps[i].id);
      expect(previews[i].type).toBe(def.steps[i].type);
      expect(previews[i].payload).toBe(def.steps[i].payload);
    }
  });

  test('run executes all steps and returns a deterministic hash', async () => {
    const def = buildChainDef('run-chain');
    const record = await store.createChain(def);
    const inputs = { input: 3 };
    const result: ExecutionResult = await executor.run(record.chainSlug, inputs);
    // Verify that each step produced the expected output.
    expect(result.stepResults).toHaveLength(2);
    const step1Result = result.stepResults[0] as StepResult;
    const step2Result = result.stepResults[1] as StepResult;
    expect(step1Result.output).toBe(4); // 3 + 1
    expect(step2Result.output).toBe(8); // 4 * 2
    // Verify deterministic hash based on step outputs.
    const expectedHash = await computeHash([step1Result.output, step2Result.output]);
    expect(result.hash).toBe(expectedHash);
  });

  test('run throws a 400 error when the chain does not exist', async () => {
    await expect(
      executor.run('nonexistent-chain', { input: 1 })
    ).rejects.toMatchObject({ code: 'CHAIN_NOT_FOUND' });
  });

  test('run retries on transient sandbox error and eventually succeeds', async () => {
    const def = buildChainDef('retry-chain');
    const record = await store.createChain(def);
    const inputs = { input: 5 };

    // Mock Sandbox.execute to fail once with a transient error, then succeed.
    const originalExecute = Sandbox.prototype.execute;
    const transientError = new Error('SQLITE_BUSY simulated');
    (transientError as any).code = 'SQLITE_BUSY';

    const mockExecute = jest
      .fn()
      .mockRejectedValueOnce(transientError)
      .mockImplementation(originalExecute.bind(new Sandbox()));

    jest.spyOn(Sandbox.prototype, 'execute').mockImplementation(mockExecute);

    const result: ExecutionResult = await executor.run(record.chainSlug, inputs);
    expect(result.stepResults).toHaveLength(2);
    // Ensure the mock was called twice (one retry).
    expect(mockExecute).toHaveBeenCalledTimes(2);
    // Restore original implementation for subsequent tests.
    (Sandbox.prototype.execute as any).mockRestore?.();
  });

  test('run aggregates logs from each step into the final result', async () => {
    const def = buildChainDef('log-chain');
    const record = await store.createChain(def);
    const inputs = { input: 2 };

    // Mock Sandbox.execute to return a predictable log entry.
    const fakeLog = 'step executed';
    jest.spyOn(Sandbox.prototype, 'execute').mockImplementation(async () => ({
      output: 3,
      logs: [fakeLog],
      stdout: '',
      stderr: '',
    }));

    const result: ExecutionResult = await executor.run(record.chainSlug, inputs);
    expect(result.logs).toBeDefined();
    expect(Array.isArray(result.logs)).toBe(true);
    // Two steps => two log entries.
    expect(result.logs).toHaveLength(2);
    expect(result.logs.every((l) => l === fakeLog)).toBe(true);
    (Sandbox.prototype.execute as any).mockRestore?.();
  });

  test('run records duration and logs it before returning', async () => {
    const def = buildChainDef('duration-chain');
    const record = await store.createChain(def);
    const inputs = { input: 7 };

    const consoleInfoSpy = jest.spyOn(console, 'info').mockImplementation(() => {});

    const result: ExecutionResult = await executor.run(record.chainSlug, inputs);
    // Verify that a duration log was emitted.
    const durationLog = consoleInfoSpy.mock.calls.find((call) =>
      typeof call[0] === 'string' && call[0].includes('Execution duration')
    );
    expect(durationLog).toBeDefined();

    consoleInfoSpy.mockRestore();
    expect(result).toBeDefined();
  });
});