import { readFile } from 'fs/promises';
import { join } from 'path';
import { Database, verbose } from 'sqlite3';
import { promisify } from 'util';
import { createHash } from 'crypto';
import {
  ChainDefinition,
  ChainRecord,
  ChainVersionRecord,
  ExecutionResult,
  StepResult,
  RateLimits,
  SessionToken,
} from '../types.ts';
import { CatalogStore, ListFilter } from '../catalog/store.ts';
import { ChainExecutor, Sandbox } from '../executor/engine.ts';

/**
 * Runs a command based on CLI arguments.
 */
export async function runCommand(args: string[]): Promise<void> {
  const dbPath = join(process.cwd(), 'chainforge.db');
  const store = new CatalogStore(dbPath);
  const sandbox = new Sandbox(); // Assuming Sandbox has a parameter‑less constructor.
  const executor = new ChainExecutor(store, sandbox);

  const [command, ...rest] = args;
  switch (command) {
    case 'run':
      await runChain(rest, executor);
      break;
    case 'publish':
      await publishChain(rest, store);
      break;
    case 'list':
      await listChains(store);
      break;
    default:
      console.error(`Unknown command: ${command}`);
      process.exit(1);
  }
}

async function runChain(params: string[], executor: ChainExecutor): Promise<void> {
  const [slugVersion] = params;
  if (!slugVersion) {
    console.error('Usage: chainforge run <slug>@<version>');
    process.exit(1);
  }
  const [slug, version] = slugVersion.split('@');
  const result: ExecutionResult = await executor.execute(slug, version);
  console.log(JSON.stringify(result, null, 2));
}

async function publishChain(params: string[], store: CatalogStore): Promise<void> {
  const [filePath] = params;
  if (!filePath) {
    console.error('Usage: chainforge publish <path-to-chain.json>');
    process.exit(1);
  }
  const content = await readFile(filePath, 'utf-8');
  const definition: ChainDefinition = JSON.parse(content);
  const hash = createHash('sha256').update(JSON.stringify(definition)).digest('hex');
  const chainRecord: ChainRecord = {
    slug: definition.slug,
    title: definition.title,
    description: definition.description ?? '',
  };
  await store.addChain(chainRecord);
  const versionRecord: ChainVersionRecord = {
    chainSlug: definition.slug,
    versionHash: hash,
    definition,
    createdAt: new Date().toISOString(),
  };
  await store.addChainVersion(versionRecord);
  console.log(`Published ${definition.slug}@${hash}`);
}

async function listChains(store: CatalogStore): Promise<void> {
  const chains = await store.listChains();
  for (const chain of chains) {
    console.log(`${chain.slug}: ${chain.title}`);
  }
}

/**
 * Entry point for the CLI when executed via `node dist/cli/main.js`.
 */
if (import.meta.url === `file://${process.argv[1]}`) {
  const args = process.argv.slice(2);
  runCommand(args).catch((err) => {
    console.error('Fatal error:', err);
    process.exit(1);
  });
}
