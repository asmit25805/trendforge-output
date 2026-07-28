export enum RunStatus {
  PENDING = "pending",
  RUNNING = "running",
  COMPLETED = "completed",
  FAILED = "failed",
}

export enum PermissionProfile {
  ASK = "ask",
  AUTO = "auto",
  FULL = "full",
}

export enum ArtifactKind {
  FILE = "file",
  TEXT = "text",
  BINARY = "binary",
}

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  sha256: string;
  createdAt: number;
  metadata: Record<string, any>;
}

export interface Project {
  id: string;
  name: string;
  createdAt: number;
}

/** Compute SHA‑256 hash of a string or Buffer. */
export function compute_sha256(data: Buffer | string): string {
  const crypto = require("crypto");
  const hash = crypto.createHash("sha256");
  hash.update(data);
  return hash.digest("hex");
}

/** Generate a UUID v4 string. */
export function _generate_uuid(): string {
  const { randomUUID } = require("crypto");
  return randomUUID();
}

/** Return current epoch time in milliseconds. */
export function _now_ms(): number {
  return Date.now();
}
