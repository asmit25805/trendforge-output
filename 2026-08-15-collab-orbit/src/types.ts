import { createHash } from 'crypto';

/**
 * Represents a parsed command line invocation.
 */
export interface ParsedCommand {
  /** Primary command name (e.g., "agent") */
  command: string;
  /** Positional arguments after the command */
  args: string[];
  /** Flag values parsed from "--flag=value" or "--flag" */
  flags: Record<string, any>;
  /** Original argv slice for debugging */
  raw: string[];
}

/**
 * Handler signature for a command.
 */
export type CommandHandler = (cmd: ParsedCommand) => Promise<unknown>;

/**
 * Configuration for a deployment provider.
 */
export interface DeployConfig {
  /** Provider‑specific configuration object */
  [key: string]: unknown;
}

/**
 * Interface that a deployment provider must implement.
 */
export interface DeployProvider {
  /** Unique identifier of the provider */
  id: string;
  /** Deploy method */
  deploy(config: DeployConfig): Promise<void>;
}

/**
 * Workspace configuration.
 */
export interface WorkspaceConfig {
  /** Unique identifier for the workspace */
  id: string;
  /** Optional TTL in seconds */
  ttl?: number;
}

/**
 * Memory entry stored in a workspace.
 */
export interface MemoryEntry {
  /** Key of the entry */
  key: string;
  /** Value stored */
  value: unknown;
  /** Timestamp of creation */
  createdAt: number;
}

/**
 * File entry stored in a workspace.
 */
export interface FileEntry {
  /** Path relative to the workspace root */
  path: string;
  /** File contents */
  content: Buffer;
}

/**
 * Store interfaces.
 */
export interface MemoryStore {
  get(key: string): Promise<MemoryEntry | undefined>;
  set(entry: MemoryEntry): Promise<void>;
  delete(key: string): Promise<void>;
}

export interface FileStore {
  read(path: string): Promise<FileEntry | undefined>;
  write(entry: FileEntry): Promise<void>;
  delete(path: string): Promise<void>;
}

/**
 * Input supplied to an agent.
 */
export interface AgentInput {
  /** Prompt or instruction */
  prompt: string;
  /** Optional context */
  context?: Record<string, unknown>;
}

/**
 * Result returned by an agent.
 */
export interface AgentResult {
  /** Final output */
  output: string;
  /** Optional metadata */
  metadata?: Record<string, unknown>;
}

/**
 * Scoped key used to isolate resources.
 */
export type ScopeKey = string;
