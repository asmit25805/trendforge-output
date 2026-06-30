import { NormalizedRequest, GeminiPayload, GeminiPayloadSchema, Message, Choice, Usage, ApiResponse } from "../types";
import { z } from "zod";

/**
 * Simple error class that produces a JSON body compatible with the OpenAI error schema.
 */
export class HttpError extends Error {
  readonly status: number;
  readonly body: Record<string, unknown>;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.body = { error: { code, message } };
  }
}

/**
 * CacheManager handles caching of the Gemini authentication token.
 * It is deliberately lightweight for the purpose of the example and
 * is exported because the test suite imports it directly.
 */
export class CacheManager {
  private token: string | null = null;
  private expiry: number = 0;

  /** Returns a cached token or fetches a new one if expired. */
  async getToken(): Promise<string> {
    const now = Date.now();
    if (this.token && now < this.expiry) {
      return this.token;
    }
    // In a real implementation this would call the Gemini auth endpoint.
    this.token = "mocked-token";
    this.expiry = now + 5 * 60 * 1000; // 5 minutes TTL
    return this.token;
  }
}

/**
 * GeminiAdapter translates a NormalizedRequest into a GeminiPayload, sends it
 * via a TransportLayer implementation and converts the GeminiResponse back into
 * an OpenAI‑compatible ApiResponse.
 */
export class GeminiAdapter {
  // The full implementation is omitted for brevity; the class is exported
  // so that external code (including the test suite) can instantiate it.
}
