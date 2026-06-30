import { GeminiPayload, GeminiResponse } from "../types";
import { FetchTransport } from "./fetch";

/**
 * TransportLayer implementation that uses raw TCP/TLS sockets.
 * It is useful in Cloudflare Workers or Docker environments where the
 * request body may exceed the fetch size limit or when the upstream
 * returns rate‑limit responses (429). The transport retries transient
 * failures with exponential back‑off and falls back to FetchTransport
 * once before propagating an error.
 */
export class SocketTransport {
  /** Maximum number of retry attempts for transient errors. */
  private static readonly MAX_RETRIES = 3;
  /** Base delay in milliseconds for back‑off calculations. */
  private static readonly BASE_DELAY_MS = 100;

  private readonly endpoint: string;
  private readonly fallback: FetchTransport;

  /**
   * @param endpoint Full URL of the Gemini Web endpoint (e.g.
   *   "https://generativelanguage.googleapis.com/v1beta/models/...:generateContent").
   */
  constructor(endpoint: string) {
    if (!endpoint) {
      throw new Error("SocketTransport requires a non‑empty endpoint URL");
    }
    this.endpoint = endpoint;
    this.fallback = new FetchTransport(endpoint);
  }

  /**
   * Sends a GeminiPayload to the configured endpoint using a socket.
   * Retries on transient network errors and on HTTP 429 responses.
   * If socket communication fails completely, a single fetch‑based
   * request is attempted before the error is re‑thrown.
   *
   * @param payload Normalized request payload for Gemini.
   * @returns Parsed GeminiResponse object.
   * @throws Error when all attempts (socket + fallback) fail.
   */
  async send(payload: GeminiPayload): Promise<GeminiResponse> {
    const body = JSON.stringify(payload);
    const url = new URL(this.endpoint);
    const isTls = url.protocol === "https:";
    const port = Number(url.port) || (isTls ? 443 : 80);
    const host = url.hostname;
    const path = url.pathname + url.search;

    for (let attempt = 0; attempt <= SocketTransport.MAX_RETRIES; attempt++) {
      try {
        const response = await this.sendViaSocket({
          host,
          port,
          isTls,
          path,
          body,
        });

        if (response.status >= 200 && response.status < 300) {
          return response.json as GeminiResponse;
        }

        if (this.isTransientStatus(response.status) && attempt < SocketTransport.MAX_RETRIES) {
          await this.delayWithJitter(attempt);
          continue;
        }

        // Permanent HTTP error – surface as a generic error.
        const errMsg = `Gemini upstream error (status ${response.status}): ${response.body}`;
        throw new Error(errMsg);
      } catch (err: unknown) {
        if (this.isTransientError(err) && attempt < SocketTransport.MAX_RETRIES) {
          await this.delayWithJitter(attempt);
          continue;
        }

        // If we exhausted socket retries, try the fetch fallback once.
        if (attempt === SocketTransport.MAX_RETRIES) {
          return this.fallback.send(payload);
        }

        // Otherwise, propagate the error after a delay.
        await this.delayWithJitter(attempt);
      }
    }

    // Should never reach here because the loop either returns or throws.
    throw new Error("SocketTransport exhausted all retries without a response");
  }

  /** No persistent resources are held; method exists for API compatibility. */
  close(): void {
    // Intentionally empty – sockets are created per request and closed automatically.
  }

  /** --------------------------------------------------------------------- */
  /** Internal helpers                                                       */
  /** --------------------------------------------------------------------- */

  private async sendViaSocket(opts: {
    host: string;
    port: number;
    isTls: boolean;
    path: string;
    body: string;
  }): Promise<{ status: number; body: string; json: unknown }> {
    const { host, port, isTls, path, body } = opts;
    const socketModule = isTls ? await import("tls") : await import("net");
    const socket = isTls
      ? socketModule.connect({ host, port, servername: host })
      : socketModule.connect({ host, port });

    return new Promise((resolve, reject) => {
      const requestHeaders = [
        `POST ${path} HTTP/1.1`,
        `Host: ${host}`,
        "Content-Type: application/json",
        `Content-Length: ${Buffer.byteLength(body)}`,
        "Connection: close",
        "",
        "",
      ].join("\r\n");

      const request = requestHeaders + body;

      let responseData = "";
      socket.setEncoding("utf8");

      socket.on("error", (err: Error) => {
        socket.destroy();
        reject(err);
      });

      socket.on("data", (chunk: string) => {
        responseData += chunk;
      });

      socket.on("end", () => {
        try {
          const [rawHeaders, ...rest] = responseData.split("\r\n\r\n");
          const bodyPart = rest.join("\r\n\r\n");
          const statusLine = rawHeaders.split("\r\n")[0];
          const statusMatch = statusLine.match(/^HTTP\/\d\.\d (\d{3})/);
          const status = statusMatch ? parseInt(statusMatch[1], 10) : 0;
          const json = bodyPart ? JSON.parse(bodyPart) : null;
          resolve({ status, body: bodyPart, json });
        } catch (e) {
          reject(e);
        }
      });

      socket.write(request);
    });
  }

  private isTransientError(err: unknown): boolean {
    if (err instanceof Error) {
      // Node.js network error codes are attached to the `code` property.
      const anyErr = err as { code?: string };
      const transientCodes = ["ECONNRESET", "ECONNREFUSED", "ETIMEDOUT", "EPIPE"];
      return anyErr.code !== undefined && transientCodes.includes(anyErr.code);
    }
    return false;
  }

  private isTransientStatus(status: number): boolean {
    return status === 429 || (status >= 500 && status < 600);
  }

  private async delayWithJitter(attempt: number): Promise<void> {
    const base = SocketTransport.BASE_DELAY_MS * Math.pow(2, attempt);
    const jitter = Math.random() * SocketTransport.BASE_DELAY_MS;
    const delay = base + jitter;
    return new Promise((resolve) => setTimeout(resolve, delay));
  }
}