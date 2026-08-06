import { z } from 'zod';
import { SDKError, UnsubscribeFn } from '../types';

/** Simple publish/subscribe event bus. */
export class EventBus {
  private listeners: Map<string, Set<(payload: unknown) => void>> = new Map();

  /**
   * Register a listener for a specific event.
   * @returns a function that can be called to unsubscribe the listener.
   */
  on(event: string, listener: (payload: unknown) => void): UnsubscribeFn {
    const schema = z.string().min(1, 'Event name must be a non‑empty string');
    schema.parse(event);
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(listener);
    return () => {
      this.listeners.get(event)!.delete(listener);
    };
  }

  /** Emit an event to all registered listeners. */
  emit(event: string, payload: unknown): void {
    const schema = z.string().min(1);
    schema.parse(event);
    const listeners = this.listeners.get(event);
    if (listeners) {
      for (const listener of listeners) {
        try {
          listener(payload);
        } catch (err) {
          // Swallow listener errors to avoid breaking other listeners.
        }
      }
    }
  }
}
