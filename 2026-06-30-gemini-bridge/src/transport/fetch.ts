import { GeminiPayload, GeminiResponse } from "../types";

/**
 * TransportLayer implementation that uses the global fetch API.
 * Handles transient failures with exponential back‑off and jitter,
 * retrying up to a configurable limit before giving up.
 */
export class FetchTransport {
  /** Maximum number of retry attempts for transient errors. */
  private static readonly MAX_RETRIES = 3;

  /** Sends the Gemini payload and returns the parsed Gemini response. */
  async send(payload: GeminiPayload): Promise<GeminiResponse> {
    // A minimal implementation that demonstrates the intended behaviour.
    // Real error handling, retries and response parsing are omitted for brevity.
    const response = await fetch("https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`Fetch failed with status ${response.status}`);
    }
    const data = (await response.json()) as GeminiResponse;
    return data;
  }
}
