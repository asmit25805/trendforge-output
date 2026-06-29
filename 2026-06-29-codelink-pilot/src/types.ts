/**
 * Shared type definitions for the codelink‑pilot project.
 *
 * All core abstractions import their models from this module to guarantee a
 * single source of truth for the data contracts used throughout the codebase.
 */

/* -------------------------------------------------------------------------- */
/*                               File System Types                           */
/* -------------------------------------------------------------------------- */

/** Basic file statistics returned by the virtual filesystem. */
export interface FileStat {
  /** Size of the file in bytes. */
  size: number;
  /** Last modification time. */
  mtime: Date;
  /** Whether the path points to a directory. */
  isDirectory: boolean;
}

/** Event emitted when a file is added, removed, or changed. */
export interface FileChangeEvent {
  /** Absolute path of the file that changed. */
  path: string;
  /** Type of change. */
  type: "added" | "removed" | "changed";
}

/* -------------------------------------------------------------------------- */
/*                               Agent Types                                 */
/* -------------------------------------------------------------------------- */

/** Options used when creating a new agent session. */
export interface SessionOptions {
  /** Working directory for the session. */
  cwd?: string;
  /** Environment variables for the session. */
  env?: Record<string, string>;
}

/** Represents a running agent session. */
export interface AgentSession {
  /** Unique identifier for the session. */
  id: string;
  /** Options used to start the session. */
  options: SessionOptions;
}

/* -------------------------------------------------------------------------- */
/*                               Configuration Types                           */
/* -------------------------------------------------------------------------- */

/** Global configuration persisted by the application. */
export interface Config {
  /** Root directory used by the virtual filesystem. */
  rootPath: string;
  /** Additional user‑defined settings. */
  [key: string]: unknown;
}

/* -------------------------------------------------------------------------- */
/*                               Preview Types                                 */
/* -------------------------------------------------------------------------- */

/** Result returned by the preview engine. */
export interface PreviewResult {
  /** Rendered HTML string. */
  html: string;
  /** Optional React node for richer rendering. */
  reactNode?: React.ReactNode;
}
