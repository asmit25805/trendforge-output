// src/types.ts
/**
 * Central type definitions for the Agent Fabric runtime.
 * All core modules import their models from this file to ensure a single source of truth.
 */

import type { JSONSchema7 } from "json-schema";

/**
 * Configuration object used to initialise an agent.
 */
export interface AgentConfig {
  /** Human readable name of the agent */
  name: string;
  /** Optional version string */
  version?: string;
  /** List of skill names that the agent will use */
  skills: string[];
  /** Arbitrary additional configuration */
  [key: string]: any;
}

/**
 * Definition of a skill that can be loaded by the runtime.
 */
export interface SkillDefinition {
  /** Unique name of the skill */
  name: string;
  /** Optional description */
  description?: string;
  /** Optional JSON schema describing the skill's configuration */
  schema?: JSONSchema7;
  /** Function that implements the skill's behaviour */
  execute: (...args: any[]) => any;
}

/**
 * Information stored by the SkillRegistry for a discovered skill.
 */
export interface SkillInfo {
  /** Name of the skill */
  name: string;
  /** Absolute path to the skill's module file */
  path: string;
  /** The loaded skill definition */
  definition: SkillDefinition;
}

/**
 * Event emitted by the engine that can be persisted for deterministic replay.
 */
export interface TraceEvent {
  /** Milliseconds since epoch */
  timestamp: number;
  /** Name of the event */
  event: string;
  /** Optional payload */
  data?: any;
}

/**
 * Record sent to the analytics subsystem.
 */
export interface TelemetryRecord {
  /** Name of the telemetry event */
  event: string;
  /** Arbitrary properties */
  properties: Record<string, any>;
  /** Timestamp of the event */
  timestamp: number;
}

/**
 * Types of RPC messages exchanged between the runtime and UI.
 */
export enum RPCMessageType {
  REQUEST = "request",
  RESPONSE = "response",
  EVENT = "event",
}

/**
 * Generic RPC message structure.
 */
export interface RPCMessage {
  /** Unique identifier for the message */
  id: string;
  /** Message type */
  type: RPCMessageType;
  /** Payload of the message */
  payload: any;
}

/**
 * Payload used when a client asks the engine to run an agent.
 */
export interface RunRequestPayload {
  /** Agent configuration to run */
  config: AgentConfig;
}

/**
 * Event captured by the analytics subsystem.
 */
export interface AnalyticsEvent {
  /** Name of the event */
  name: string;
  /** Arbitrary properties */
  properties: Record<string, any>;
}

/**
 * Common properties merged into every telemetry record.
 */
export const COMMON_PROPERTIES = {
  platform: process.platform,
  nodeVersion: process.version,
  runtime: process.release?.name ?? "node",
};
