/**
 * Shared type definitions for the Polytag project.
 * All core modules import types from this file to ensure consistency.
 */

import { randomUUID } from 'crypto';

/**
 * Supported chat platforms.
 */
export enum Platform {
  Slack = 'slack',
  Discord = 'discord',
  Teams = 'teams',
  Mattermost = 'mattermost',
}

/**
 * Reference to a target location where a message should be sent.
 */
export interface TargetRef {
  /** Platform where the target resides. */
  platform: Platform;
  /** Identifier of the channel (platform‑specific). */
  channelId: string;
  /** Identifier of the thread within the channel, if applicable. */
  threadId?: string | null;
}

/**
 * Content of a message sent back to a platform.
 */
export interface MessageContent {
  /** Plain text body of the message. */
  text: string;
  /** Optional array of attachment URLs or objects. */
  attachments?: Array<{ url: string; title?: string }>;
}

/**
 * Payload emitted by a platform‑specific adapter after parsing an incoming event.
 */
export interface EventPayload {
  /** Origin platform of the event. */
  platform: Platform;
  /** Platform‑specific channel identifier. */
  channelId: string;
  /** Parent thread identifier if the message belongs to a thread. */
  threadId: string | null;
  /** Identifier of the user who authored the message. */
  userId: string;
  /** Raw text content of the incoming message. */
  text: string;
  /** Epoch timestamp in milliseconds. */
  timestamp: number;
}

/**
 * Payload used when an approval request must be presented to a user.
 */
export interface ApprovalPayload {
  /** Unique identifier of the task requiring approval. */
  taskId: string;
  /** Identifier of the user who initiated the request. */
  requesterId: string;
  /** Human‑readable description of why approval is needed. */
  details: string;
}

/**
 * Definition of a task that will be executed by a runtime.
 */
export interface TaskDefinition {
  /** UUID for the run. */
  taskId: string;
  /** Prompt that will be sent to the LLM after knowledge injection. */
  prompt: string;
  /** Capabilities required for the runtime (e.g., network, file_write). */
  requiredCapabilities: string[];
  /** Reference to the project/repository the task is bound to. */
  projectRef: ProjectRef;
  /** Snapshot version of the shared knowledge at task creation time. */
  knowledgeVersion: number;
}

/**
 * Reference to a project or repository.
 */
export interface ProjectRef {
  /** Identifier of the project (could be a repo name or UUID). */
  projectId: string;
}

/**
 * Context passed to runtime adapters and policy engine.
 */
export interface ExecutionContext {
  /** Platform where the request originated. */
  platform: Platform;
  /** Channel identifier of the originating request. */
  channelId: string;
  /** User identifier of the request initiator. */
  userId: string;
  /** Epoch timestamp of the request. */
  timestamp: number;
}

/**
 * Result returned by a RuntimeAdapter after execution.
 */
export interface RuntimeResult {
  /** Full textual output produced by the runtime. */
  output: string;
  /** Optional error message if execution failed. */
  error?: string;
  /** Execution status. */
  status: 'success' | 'error';
}

/**
 * Decision returned by the PolicyEngine.
 */
export interface PolicyDecision {
  /** Whether the task is allowed to proceed without further checks. */
  allow: boolean;
  /** Whether an interactive approval is required before proceeding. */
  requiresApproval: boolean;
  /** Human‑readable reason for the decision. */
  reason: string;
}

/**
 * Single entry stored in the KnowledgeStore.
 */
export interface KnowledgeEntry {
  /** UUID of the fact entry. */
  id: string;
  /** Identifier of the project the fact belongs to. */
  projectId: string;
  /** Identifier of the channel the fact is scoped to. */
  channelId: string;
  /** Monotonically increasing version number per channel. */
  version: number;
  /** Free‑form statement representing the fact. */
  fact: string;
  /** Identifier of the user who added the fact. */
  authorId: string;
  /** Epoch timestamp of creation. */
  createdAt: number;
}

/**
 * Reference used to query the KnowledgeStore.
 */
export interface KnowledgeRef {
  /** Project identifier. */
  projectId: string;
  /** Channel identifier. */
  channelId: string;
}

/**
 * Immutable snapshot of knowledge entries at a specific version.
 */
export class KnowledgeSnapshot {
  /** Version number of the snapshot. */
  public readonly version: number;
  /** Array of knowledge entries included in the snapshot. */
  public readonly entries: KnowledgeEntry[];

  constructor(version: number, entries: KnowledgeEntry[]) {
    this.version = version;
    this.entries = entries;
  }

  /**
   * Retrieve a fact by its UUID.
   * @param id UUID of the fact.
   * @returns Matching KnowledgeEntry or undefined.
   */
  public getFactById(id: string): KnowledgeEntry | undefined {
    return this.entries.find((e) => e.id === id);
  }

  /**
   * Return all facts as plain strings.
   */
  public getAllFacts(): string[] {
    return this.entries.map((e) => e.fact);
  }

  /**
   * Create a new snapshot with an additional entry.
   * The original snapshot remains unchanged (immutability).
   * @param entry New knowledge entry to append.
   * @returns New KnowledgeSnapshot instance.
   */
  public append(entry: KnowledgeEntry): KnowledgeSnapshot {
    const newVersion = this.version + 1;
    const newEntries = [...this.entries, entry];
    return new KnowledgeSnapshot(newVersion, newEntries);
  }
}

/**
 * Record persisted by the AuditLogger for each task run.
 */
export interface AuditRecord {
  /** Identifier of the run (same as taskId). */
  runId: string;
  /** Identifier of the runtime selected for execution. */
  runtimeId: string;
  /** Epoch start time in milliseconds. */
  startTime: number;
  /** Epoch end time in milliseconds. */
  endTime: number;
  /** Overall status of the run. */
  status: 'success' | 'error' | 'cancelled';
  /** Captured output from the runtime, if any. */
  output: string | null;
  /** Error message if the run failed, otherwise null. */
  errorMessage: string | null;
  /** Identifier of the approval request, if one was issued. */
  approvalId: string | null;
}

/**
 * Filter used to query audit records.
 */
export interface AuditFilter {
  /** Optional run identifier to match. */
  runId?: string;
  /** Optional runtime identifier to match. */
  runtimeId?: string;
  /** Optional status to filter by. */
  status?: 'success' | 'error' | 'cancelled';
  /** Optional time range (inclusive). */
  startTime?: number;
  endTime?: number;
}

/**
 * Function signature for a policy rule.
 */
export type PolicyRule = (task: TaskDefinition, ctx: ExecutionContext) => PolicyDecision;

/**
 * Simple capability alias.
 */
export type Capability = string;

/**
 * Validate that an arbitrary object conforms to the EventPayload shape.
 * @param obj Object to validate.
 * @returns True if the object matches EventPayload, false otherwise.
 */
export function isValidEventPayload(obj: any): obj is EventPayload {
  if (typeof obj !== 'object' || obj === null) return false;
  const required = ['platform', 'channelId', 'threadId', 'userId', 'text', 'timestamp'];
  for (const key of required) {
    if (!(key in obj)) return false;
  }
  if (!Object.values(Platform).includes(obj.platform)) return false;
  if (typeof obj.channelId !== 'string') return false;
  if (obj.threadId !== null && typeof obj.threadId !== 'string') return false;
  if (typeof obj.userId !== 'string') return false;
  if (typeof obj.text !== 'string') return false;
  if (typeof obj.timestamp !== 'number') return false;
  return true;
}

/**
 * Generate a RFC‑4122 version 4 UUID.
 * Falls back to a simple random implementation if crypto.randomUUID is unavailable.
 */
export function generateUUID(): string {
  if (typeof randomUUID === 'function') {
    return randomUUID();
  }
  // Fallback: generate 16 random bytes and format as UUID
  const bytes = new Uint8Array(16);
  for (let i = 0; i < 16; i++) {
    bytes[i] = Math.floor(Math.random() * 256);
  }
  // Set version and variant bits
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/**
 * Return the current epoch timestamp in milliseconds.
 */
export function now(): number {
  return Date.now();
}

/**
 * Create a new AuditRecord from execution metadata.
 * @param params Partial fields required to build the record.
 * @returns Fully populated AuditRecord.
 */
export function createAuditRecord(params: {
  runId: string;
  runtimeId: string;
  startTime: number;
  endTime: number;
  status: 'success' | 'error' | 'cancelled';
  output?: string | null;
  errorMessage?: string | null;
  approvalId?: string | null;
}): AuditRecord {
  return {
    runId: params.runId,
    runtimeId: params.runtimeId,
    startTime: params.startTime,
    endTime: params.endTime,
    status: params.status,
    output: params.output ?? null,
    errorMessage: params.errorMessage ?? null,
    approvalId: params.approvalId ?? null,
  };
}

/**
 * Helper to clone a TaskDefinition with a new taskId.
 * Useful for retry logic that preserves other fields.
 * @param task Existing task definition.
 * @returns New TaskDefinition with a fresh UUID.
 */
export function cloneTaskWithNewId(task: TaskDefinition): TaskDefinition {
  return {
    ...task,
    taskId: generateUUID(),
  };
}

/**
 * Serialize a RuntimeResult to JSON for storage or transport.
 * @param result RuntimeResult instance.
 * @returns JSON string.
 */
export function serializeRuntimeResult(result: RuntimeResult): string {
  return JSON.stringify(result);
}

/**
 * Deserialize a RuntimeResult from JSON.
 * @param json JSON string.
 * @returns Parsed RuntimeResult.
 * @throws Error if parsing fails or required fields are missing.
 */
export function deserializeRuntimeResult(json: string): RuntimeResult {
  const obj = JSON.parse(json);
  if (typeof obj !== 'object' || obj === null) {
    throw new Error('Invalid RuntimeResult JSON');
  }
  if (typeof obj.output !== 'string' || typeof obj.status !== 'string') {
    throw new Error('Missing required RuntimeResult fields');
  }
  return {
    output: obj.output,
    error: typeof obj.error === 'string' ? obj.error : undefined,
    status: obj.status as 'success' | 'error',
  };
}

/**
 * Validate that a PolicyDecision object contains consistent fields.
 * @param decision Decision to validate.
 * @returns True if valid, false otherwise.
 */
export function isValidPolicyDecision(decision: any): decision is PolicyDecision {
  if (typeof decision !== 'object' || decision === null) return false;
  if (typeof decision.allow !== 'boolean') return false;
  if (typeof decision.requiresApproval !== 'boolean') return false;
  if (typeof decision.reason !== 'string') return false;
  return true;
}