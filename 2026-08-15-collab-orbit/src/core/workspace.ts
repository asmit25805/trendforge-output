import { createHash } from 'crypto';
import { logger } from '../utils/logger';
import {
  WorkspaceConfig,
  MemoryStore,
  FileStore,
  MemoryEntry,
  FileEntry,
  AgentResult,
  AgentInput,
  ScopeKey,
} from '../types';
import retry from 'p-retry';

/**
 * Base class for configuration‑related errors.
 */
export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ConfigError';
  }
}

/**
 * Errors related to providers.
 */
export class ProviderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ProviderError';
  }
}

/**
 * Errors that occur during execution.
 */
export class ExecutionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ExecutionError';
  }
}

/**
 * Generic not‑found error.
 */
export class NotFoundError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NotFoundError';
  }
}

/**
 * Represents a scoped workspace.
 */
export class Workspace {
  readonly id: string;
  readonly scopeKey: ScopeKey;
  readonly memoryStore: MemoryStore;
  readonly fileStore: FileStore;

  constructor(config: WorkspaceConfig, memoryStore: MemoryStore, fileStore: FileStore) {
    this.id = config.id;
    this.scopeKey = WorkspaceManager.generateScopeKey(config.id);
    this.memoryStore = memoryStore;
    this.fileStore = fileStore;
  }
}

/**
 * Manager responsible for creating and retrieving workspaces.
 */
export class WorkspaceManager {
  private readonly workspaces: Map<string, Workspace> = new Map();

  constructor(
    private readonly memoryStoreFactory: (config: WorkspaceConfig) => MemoryStore,
    private readonly fileStoreFactory: (config: WorkspaceConfig) => FileStore,
  ) {}

  /** Generate a deterministic scope key from a workspace identifier. */
  static generateScopeKey(id: string): ScopeKey {
    return createHash('sha256').update(id).digest('hex');
  }

  /** Get an existing workspace or create a new one. */
  getOrCreate(config: WorkspaceConfig): Workspace {
    let ws = this.workspaces.get(config.id);
    if (!ws) {
      const mem = this.memoryStoreFactory(config);
      const file = this.fileStoreFactory(config);
      ws = new Workspace(config, mem, file);
      this.workspaces.set(config.id, ws);
    }
    return ws;
  }
}
