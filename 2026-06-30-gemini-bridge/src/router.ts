import { NormalizedRequest, NormalizedRequestSchema } from "./types";
import { ZodError } from "zod";

/**
 * Represents an HTTP error with a JSON body conforming to the OpenAI error schema.
 */
class HttpError extends Error {
  readonly status: number;
  readonly body: Record<string, unknown>;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.body = { error: { code, message } };
  }
}

/**
 * RequestRouter inspects incoming HTTP requests, validates payloads,
 * normalizes them into a unified NormalizedRequest, and detects health‑check endpoints.
 */
export class RequestRouter {
  /**
   * Determines whether the request targets a health‑check endpoint.
   * Recognized paths: /health, /healthz (case‑insensitive).
   */
  static isHealthCheck(req: Request): boolean {
    const url = new URL(req.url);
    const path = url.pathname.toLowerCase();
    return path === "/health" || path === "/healthz";
  }

  /**
   * Parses, validates, and normalizes the request body according to the API flavour.
   * Supported flavours:
   *   - OpenAI:   POST /v1/chat/completions
   *   - Google:   POST /gemini/v1/chat
   *   - Anthropic:POST /anthropic/v1/complete
   *
   * @throws HttpError with status 400 for validation problems.
   */
  static async route(req: Request): Promise<NormalizedRequest> {
    const url = new URL(req.url);
    const path = url.pathname;

    // Only POST is allowed for chat endpoints.
    if (req.method !== "POST") {
      throw new HttpError(405, "invalid_request", "Only POST method is allowed");
    }

    // Extract raw JSON payload.
    let rawBody: unknown;
    try {
      rawBody = await req.clone().json();
    } catch (e) {
      throw new HttpError(400, "invalid_request", "Request body must be valid JSON");
    }

    // Normalise according to the endpoint.
    let normalized: unknown;
    if (path.startsWith("/v1/chat/completions")) {
      normalized = RequestRouter.mapOpenAI(rawBody);
    } else if (path.startsWith("/gemini/v1/chat")) {
      normalized = RequestRouter.mapGoogle(rawBody);
    } else if (path.startsWith("/anthropic/v1/complete")) {
      normalized = RequestRouter.mapAnthropic(rawBody);
    } else {
      throw new HttpError(404, "invalid_request", `Unsupported endpoint: ${path}`);
    }

    // Validate the NormalizedRequest schema.
    try {
      return NormalizedRequestSchema.parse(normalized);
    } catch (e) {
      if (e instanceof ZodError) {
        const first = e.errors[0];
        const msg = first?.message ?? "Invalid request payload";
        throw new HttpError(400, "invalid_request", msg);
      }
      throw new HttpError(400, "invalid_request", "Invalid request payload");
    }
  }

  /**
   * Maps an OpenAI‑style payload to the internal NormalizedRequest shape.
   */
  private static mapOpenAI(payload: unknown): Partial<NormalizedRequest> {
    if (typeof payload !== "object" || payload === null) {
      throw new HttpError(400, "invalid_request", "Payload must be an object");
    }
    const p = payload as Record<string, any>;

    // OpenAI may omit an explicit id; generate a UUID if missing.
    const id = typeof p.id === "string" ? p.id : RequestRouter.generateUUID();

    return {
      id,
      model: p.model,
      messages: p.messages,
      temperature: p.temperature ?? 0.7,
      stream: Boolean(p.stream),
      metadata: p.metadata,
    };
  }

  /**
   * Maps a Google‑style payload to the internal NormalizedRequest shape.
   * Google Gemini expects `model` and `messages` (same as OpenAI) but may use `temperature` under `generationConfig`.
   */
  private static mapGoogle(payload: unknown): Partial<NormalizedRequest> {
    if (typeof payload !== "object" || payload === null) {
      throw new HttpError(400, "invalid_request", "Payload must be an object");
    }
    const p = payload as Record<string, any>;

    const id = typeof p.id === "string" ? p.id : RequestRouter.generateUUID();

    // Temperature may be nested.
    const temperature =
      typeof p.generationConfig?.temperature === "number"
        ? p.generationConfig.temperature
        : p.temperature ?? 0.7;

    return {
      id,
      model: p.model,
      messages: p.messages,
      temperature,
      stream: Boolean(p.stream),
      metadata: p.metadata,
    };
  }

  /**
   * Maps an Anthropic‑style payload to the internal NormalizedRequest shape.
   * Anthropic uses `prompt` (array of strings) instead of `messages`.
   */
  private static mapAnthropic(payload: unknown): Partial<NormalizedRequest> {
    if (typeof payload !== "object" || payload === null) {
      throw new HttpError(400, "invalid_request", "Payload must be an object");
    }
    const p = payload as Record<string, any>;

    const id = typeof p.id === "string" ? p.id : RequestRouter.generateUUID();

    // Convert Anthropic's prompt array into OpenAI‑style messages.
    const rawPrompt: unknown = p.prompt;
    if (!Array.isArray(rawPrompt)) {
      throw new HttpError(400, "invalid_request", "Anthropic prompt must be an array");
    }

    const messages = rawPrompt.map((segment: any, idx: number) => ({
      role: "user" as const,
      content: typeof segment === "string" ? segment : JSON.stringify(segment),
    }));

    const temperature = typeof p.temperature === "number" ? p.temperature : 0.7;

    return {
      id,
      model: p.model,
      messages,
      temperature,
      stream: Boolean(p.stream),
      metadata: p.metadata,
    };
  }

  /**
   * Generates a RFC‑4122 version‑4 UUID.
   */
  private static generateUUID(): string {
    // Use crypto API if available (Node >=15, Cloudflare Workers).
    const cryptoObj = (globalThis as any).crypto ?? (require("crypto") as any);
    const bytes = new Uint8Array(16);
    cryptoObj.getRandomValues(bytes);
    // Set version and variant bits.
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes).map((b) => b.toString(16).padStart(2, "0"));
    return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex
      .slice(6, 8)
      .join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10, 16).join("")}`;
  }
}

/**
 * Helper to convert a thrown HttpError into a Response object.
 * Used by the top‑level server middleware.
 */
export function errorResponse(err: unknown): Response {
  if (err instanceof HttpError) {
    return new Response(JSON.stringify(err.body), {
      status: err.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  // Unexpected errors become 500.
  const generic = {
    error: { code: "internal_error", message: "internal server error" },
  };
  return new Response(JSON.stringify(generic), {
    status: 500,
    headers: { "Content-Type": "application/json" },
  });
}