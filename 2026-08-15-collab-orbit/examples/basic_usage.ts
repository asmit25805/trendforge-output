import { CommandRouter, ParsedCommand, CommandHandler } from './src/cli/router';
import { ProviderRegistry, ProviderNotFoundError } from './src/providers/registry';
import {
  WorkspaceManager,
  ConfigError,
  ProviderError,
  ExecutionError,
  NotFoundError,
  Workspace,
} from './src/core/workspace';
import { AgentExecutor, RunStatus } from './src/engine/agent_executor';
import { logger, LogLevel } from './src/utils/logger';
import {
  ScopeKey,
  AgentInput,
  DeployProvider,
  DeployConfig,
  MemoryStore,
  FileStore,
} from './src/types';

/**
 * Initialise the global logger.
 */
logger.setLevel(
  process.env.LOG_LEVEL === 'debug'
    ? LogLevel.Debug
    : process.env.LOG_LEVEL === 'warn'
    ? LogLevel.Warn
    : LogLevel.Info,
);

/**
 * Helper that creates a minimal in‑memory workspace.
 *
 * In a real deployment the WorkspaceManager would provision cloud resources.
 * For the purpose of the example we fall back to a simple in‑memory store
 * when the manager cannot locate an existing workspace.
 */
async function obtainWorkspace(
  tenantId: string,
  wsManager: WorkspaceManager,
): Promise<Workspace> {
  try {
    return wsManager.get(tenantId);
  } catch (err) {
    if (err instanceof NotFoundError) {
      const config = { maxSandboxSize: 128 };
      return wsManager.create(tenantId, config);
    }
    throw err;
  }
}

/**
 * Executes a single agent run inside a newly created workspace.
 *
 * @param tenantId - Identifier of the tenant (organisation or project).
 * @param userId   - Identifier of the user invoking the command.
 * @param prompt   - Text prompt supplied by the user.
 */
async function runAgent(
  tenantId: string,
  userId: string,
  prompt: string,
): Promise<void> {
  const wsManager = new WorkspaceManager();
  const providerRegistry = new ProviderRegistry();

  // Resolve a deployment provider – for the example we assume a provider
  // named "local" is always registered.
  let provider: DeployProvider;
  try {
    provider = providerRegistry.get('local');
  } catch (err) {
    if (err instanceof ProviderNotFoundError) {
      throw new ProviderError('No deployment provider named "local" is registered');
    }
    throw err;
  }

  // Obtain (or create) a workspace for the tenant.
  const workspace = await obtainWorkspace(tenantId, wsManager);

  // Initialise the executor with the workspace's scoped stores.
  const executor = new AgentExecutor(
    workspace.memoryStore as MemoryStore,
    workspace.fileStore as FileStore,
  );

  // Build a deterministic scope key for the user.
  const scope = ScopeKey.fromUser(userId);

  // Assemble the agent input.
  const input: AgentInput = {
    prompt,
    metadata: {
      tenantId,
      userId,
      provider: provider.constructor.name,
    },
  };

  // Run the agent and handle possible outcomes.
  try {
    const result = await executor.run('default-agent', input, scope);
    logger.info('✅ Agent completed successfully');
    logger.info(`Output:\n${result.output}`);

    if (result.generatedFiles.length > 0) {
      logger.info(`🗂️  Generated ${result.generatedFiles.length} file(s)`);
      for (const file of result.generatedFiles) {
        logger.debug(`- ${file.path} (${file.mimeType})`);
      }
    }
  } catch (err) {
    if (err instanceof ExecutionError) {
      logger.error(`❌ Execution failed: ${err.message}`);
    } else if (err instanceof ConfigError) {
      logger.error(`⚙️  Configuration problem: ${err.message}`);
    } else if (err instanceof ProviderError) {
      logger.error(`🚀 Provider error: ${err.message}`);
    } else {
      logger.error(`💥 Unexpected error: ${err instanceof Error ? err.message : String(err)}`);
    }
    process.exit(1);
  }
}

/**
 * Register CLI commands and start the router.
 *
 * The example supports a single sub‑command:
 *
 *   node examples/basic_usage.ts run --tenant=my-org --user=alice --prompt="Hello"
 *
 * All flags are parsed without external dependencies.
 */
function main(): void {
  const router = new CommandRouter();

  const runHandler: CommandHandler = async (args: Record<string, unknown>) => {
    const tenant = typeof args.tenant === 'string' ? args.tenant : undefined;
    const user = typeof args.user === 'string' ? args.user : undefined;
    const prompt = typeof args.prompt === 'string' ? args.prompt : undefined;

    if (!tenant || !user || !prompt) {
      throw new ConfigError('Missing required flags: --tenant, --user, --prompt');
    }

    await runAgent(tenant, user, prompt);
  };

  router.register('run', runHandler);

  const parsed: ParsedCommand = router.parse(process.argv);
  router
    .dispatch(parsed)
    .catch((err) => {
      // Any uncaught error is logged and results in a non‑zero exit code.
      logger.error(`Fatal error: ${err instanceof Error ? err.message : String(err)}`);
      process.exit(1);
    });
}

// Execute when the file is run directly.
if (require.main === module) {
  main();
}