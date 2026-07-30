import { ProviderEnum, ProviderConfig, LLMRequest, LLMResponse, RETRY_LIMIT, exponentialBackoff } from "./types";
import { setTimeout as delay } from "timers/promises";

/**
 * Simple token‑bucket rate limiter.
 * Allows `maxTokens` operations per `refillIntervalMs`. Tokens are refilled
 * automatically; `acquire` resolves when a token is available.
 */
class RateLimiter {
  private tokens: number;
  private maxTokens: number;
  private refillIntervalMs: number;
  private refillHandle?: NodeJS.Timeout;

  constructor(maxTokens: number, refillIntervalMs: number) {
    this.tokens = maxTokens;
    this.maxTokens = maxTokens;
    this.refillIntervalMs = refillIntervalMs;
    this.refillHandle = setInterval(() => this.refill(), this.refillIntervalMs);
  }

  private refill() {
    this.tokens = this.maxTokens;
  }

  async acquire(): Promise<void> {
    while (this.tokens <= 0) {
      await delay(this.refillIntervalMs);
    }
    this.tokens--;
  }

  stop() {
    if (this.refillHandle) clearInterval(this.refillHandle);
  }
}

/**
 * Proxy that forwards LLMRequests to the configured provider.
 */
export class LLMProxy {
  private provider: ProviderEnum = ProviderEnum.OpenAI; // default
  private config: ProviderConfig | undefined;
  private limiter: RateLimiter;

  constructor(config?: ProviderConfig) {
    this.config = config;
    this.limiter = new RateLimiter(5, 1000); // 5 requests per second
  }

  /** Send a request to the underlying LLM provider with retries. */
  async sendRequest(request: LLMRequest): Promise<LLMResponse> {
    await this.limiter.acquire();
    for (let attempt = 0; attempt <= RETRY_LIMIT; attempt++) {
      try {
        // Placeholder implementation – in a real library you would call the provider SDK.
        const fakeResponse: LLMResponse = {
          answer: `Processed ${request.strokes.length} strokes`,
          requestId: `${Date.now()}-${Math.random()}`,
        };
        return fakeResponse;
      } catch (err) {
        if (attempt === RETRY_LIMIT) throw err;
        await delay(exponentialBackoff(attempt));
      }
    }
    // Unreachable – satisfies TypeScript
    throw new Error("LLM request failed after retries");
  }
}

/**
 * Provider enumeration – extend as needed.
 */
export enum ProviderEnum {
  OpenAI = "openai",
  Anthropic = "anthropic",
  Claude = "claude",
}

/**
 * Optional configuration for a provider.
 */
export interface ProviderConfig {
  apiKey: string;
  /** Base URL for the provider's API */
  baseUrl?: string;
}
