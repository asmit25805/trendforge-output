import { z } from 'zod';
import { RateLimitConfig, SDKError } from '../types';

/**
 * TokenBucket implements a classic token‑bucket rate‑limiter.
 *
 * Tokens are refilled over time according to the configured capacity and interval.
 * A VIP boost factor can increase both the bucket size and the refill rate.
 */
export class TokenBucket {
  private capacity: number;
  private tokens: number;
  private intervalMs: number;
  private lastRefill: number;
  private boostFactor: number;

  constructor(config: RateLimitConfig) {
    const schema = z.object({
      capacity: z.number().positive(),
      intervalMs: z.number().positive(),
      boostFactor: z.number().positive().optional(),
    });
    const parsed = schema.parse(config);
    this.boostFactor = parsed.boostFactor ?? 1;
    this.capacity = parsed.capacity * this.boostFactor;
    this.tokens = this.capacity;
    this.intervalMs = parsed.intervalMs;
    this.lastRefill = Date.now();
  }

  private refill(): void {
    const now = Date.now();
    const elapsed = now - this.lastRefill;
    const tokensToAdd = Math.floor((elapsed / this.intervalMs) * this.capacity);
    if (tokensToAdd > 0) {
      this.tokens = Math.min(this.tokens + tokensToAdd, this.capacity);
      this.lastRefill = now;
    }
  }

  /**
   * Attempt to consume a number of tokens.
   * @returns true if enough tokens were available, false otherwise.
   */
  public consume(count = 1): boolean {
    this.refill();
    if (this.tokens >= count) {
      this.tokens -= count;
      return true;
    }
    return false;
  }
}

/**
 * RateLimiter wraps a TokenBucket and provides a convenient async API.
 */
export class RateLimiter {
  private bucket: TokenBucket;

  constructor(config: RateLimitConfig) {
    this.bucket = new TokenBucket(config);
  }

  /**
   * Schedule a function to run if the rate limit permits.
   * @throws SDKError when the bucket has no tokens.
   */
  public async schedule<T>(fn: () => Promise<T>): Promise<T> {
    if (!this.bucket.consume()) {
      throw new SDKError('Rate limit exceeded', 429);
    }
    return fn();
  }
}
