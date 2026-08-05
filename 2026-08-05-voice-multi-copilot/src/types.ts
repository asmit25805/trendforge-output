// src/types.ts
/**
 * Core data models shared across the voice‑multi‑copilot codebase.
 * All interfaces are deliberately simple to keep runtime overhead low.
 */

import { Buffer } from 'buffer';

/* -------------------------------------------------------------------------- */
/*  Enumerations                                                              */
/* -------------------------------------------------------------------------- */
export enum Decision {
  Accept = 'accept',
  Reject = 'reject',
}

export enum TaskStatus {
  Pending = 'pending',
  Running = 'running',
  Completed = 'completed',
  Failed = 'failed',
}

/* -------------------------------------------------------------------------- */
/*  Interfaces                                                               */
/* -------------------------------------------------------------------------- */
export interface AgentProfile {
  id: string;
  name: string;
  description?: string;
}

export interface VoiceSegment {
  id: string;
  timestamp: number;
  audio: Buffer;
  transcript?: string;
}

export interface TalkPayload {
  text: string;
  language?: string;
}

export interface TaskTicket {
  id: string;
  agentId: string;
  payload: TalkPayload;
}

export interface NegotiationResult {
  decision: Decision;
  ticket: TaskTicket | null;
}
