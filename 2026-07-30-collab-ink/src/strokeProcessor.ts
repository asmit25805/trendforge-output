import { EventEmitter } from "events";
import {
  Stroke,
  SessionId,
  LLMRequest,
  RETRY_LIMIT,
  exponentialBackoff,
} from "./types";
import { LLMProxy } from "./llmProxy";

/**
 * Configuration options for the StrokeProcessor.
 */
export interface StrokeProcessorConfig {
  /** Maximum number of strokes per LLM request batch. */
  maxBatchSize?: number;
  /** Maximum time in ms to wait before flushing a batch. */
  maxBatchMs?: number;
}

/**
 * Handles debouncing, simplifying and batching strokes before forwarding them to an LLM.
 */
export class StrokeProcessor extends EventEmitter {
  private config: StrokeProcessorConfig;
  private batch: Stroke[] = [];
  private timer?: NodeJS.Timeout;
  private llmProxy: LLMProxy;

  constructor(config: StrokeProcessorConfig = {}, llmProxy?: LLMProxy) {
    super();
    this.config = {
      maxBatchSize: 20,
      maxBatchMs: 2000,
      ...config,
    };
    this.llmProxy = llmProxy ?? new LLMProxy();
  }

  /** Add a stroke to the current batch and schedule a flush if needed. */
  addStroke(stroke: Stroke) {
    this.batch.push(stroke);
    if (this.batch.length >= (this.config.maxBatchSize ?? 20)) {
      this.flushBatch();
    } else if (!this.timer) {
      this.timer = setTimeout(() => this.flushBatch(), this.config.maxBatchMs);
    }
  }

  /** Flush the current batch to the LLM and emit a response event. */
  private async flushBatch() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = undefined;
    }
    if (this.batch.length === 0) return;
    const batch = this.batch;
    this.batch = [];
    const request: LLMRequest = {
      sessionId: batch[0].sessionId,
      strokes: batch,
    };
    try {
      const response = await this.llmProxy.sendRequest(request);
      this.emit("llmResponse", response);
    } catch (err) {
      this.emit("error", err);
    }
  }
}
