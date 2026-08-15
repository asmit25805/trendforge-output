import { CommandRouter } from '../src/cli/router';
import { ProviderRegistry, ProviderNotFoundError } from '../src/providers/registry';
import { ConfigError } from '../src/core/workspace';
import { DeployProvider, DeployConfig } from '../src/types';

describe('CommandRouter', () => {
  const router = new CommandRouter();

  const mockHandler = jest.fn(async (args: Record<string, unknown>) => {
    return `handled ${JSON.stringify(args)}`;
  });

  beforeAll(() => {
    router.register('greet', mockHandler);
  });

  afterEach(() => {
    mockHandler.mockClear();
  });

  test('parses a command with positional arguments', async () => {
    const argv = ['node', 'cli.js', 'greet', 'Alice', '--times=3'];
    const parsed = router.parse(argv);
    expect(parsed.command).toBe('greet');
    expect(parsed.args).toEqual({ _: ['Alice'], times: '3' });
  });

  test('parses boolean shortcut flags correctly', async () => {
    const argv = ['node', 'cli.js', 'greet', '--verbose'];
    const parsed = router.parse(argv);
    expect(parsed.args).toEqual({ _: [], verbose: true });
  });

  test('parses flags with equals syntax', async () => {
    const argv = ['node', 'cli.js', 'greet', '--mode=fast', '--debug'];
    const parsed = router.parse(argv);
    expect(parsed.args).toEqual({ _: [], mode: 'fast', debug: true });
  });

  test('dispatches to the registered handler with parsed arguments', async () => {
    const argv = ['node', 'cli.js', 'greet', '--name=Bob'];
    const parsed = router.parse(argv);
    await router.dispatch(parsed);
    expect(mockHandler).toHaveBeenCalledTimes(1);
    expect(mockHandler).toHaveBeenCalledWith({ _: [], name: 'Bob' });
  });

  test('dispatch throws ConfigError for unknown command', async () => {
    const argv = ['node', 'cli.js', 'unknown'];
    const parsed = router.parse(argv);
    await expect(router.dispatch(parsed)).rejects.toThrow(ConfigError);
  });

  test('registering a duplicate command overwrites the previous handler', async () => {
    const secondHandler = jest.fn(async () => 'second');
    router.register('greet', secondHandler);
    const argv = ['node', 'cli.js', 'greet'];
    const parsed = router.parse(argv);
    await router.dispatch(parsed);
    expect(mockHandler).not.toHaveBeenCalled();
    expect(secondHandler).toHaveBeenCalled();
  });
});

describe('ProviderRegistry', () => {
  const registry = new ProviderRegistry();

  const dummyProvider: DeployProvider = {
    async deploy(config: DeployConfig): Promise<void> {
      // no‑op implementation for testing
    },
    async destroy(id: string): Promise<void> {
      // no‑op implementation for testing
    },
  };

  test('registers and retrieves a provider', () => {
    registry.register('dummy', dummyProvider);
    const retrieved = registry.get('dummy');
    expect(retrieved).toBe(dummyProvider);
  });

  test('list returns all registered provider ids', () => {
    registry.register('another', dummyProvider);
    const ids = registry.list();
    expect(ids).toContain('dummy');
    expect(ids).toContain('another');
  });

  test('get throws ProviderNotFoundError for unknown id', () => {
    expect(() => registry.get('nonexistent')).toThrow(ProviderNotFoundError);
  });
});