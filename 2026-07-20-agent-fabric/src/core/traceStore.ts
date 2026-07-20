// src/core/traceStore.ts
import { TraceEvent } from "../types";

/**
 * Simple in‑memory store for trace events. In a production build this could be swapped
 * for a SQLite‑backed implementation.
 */
export class TraceStore {
  private events: TraceEvent[] = [];

  /** Add a new trace event to the store */
  add(event: TraceEvent): void {
    this.events.push(event);
  }

  /** Retrieve all stored trace events */
  getAll(): TraceEvent[] {
    return [...this.events];
  }
}
