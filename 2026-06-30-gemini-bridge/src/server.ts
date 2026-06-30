import { RequestRouter } from "./router";
import { GeminiAdapter, HttpError } from "./adapter/gemini";
import { SocketTransport } from "./transport/socket";
import { StreamProcessor } from "./stream/processor";
import {
  NormalizedRequest,
  ApiResponse,
  ApiChunk,
  GeminiResponse,
  RequestContext,
} from "./types";

/**
 * Contextual information for a single request lifecycle.
 */
interface InternalRequestContext extends RequestContext {
  requestId: string;
  startTime: number;
}

/**
 * Creates a JSON response with appropriate headers.
 */
function jsonResponse(
  status: number,
  body: Record<string, unknown>
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

/**
 * Formats an OpenAI‑compatible SSE data line.
 */
function formatSse(data: string): string {
  return `data: ${data}\n\n`;
}

/**
 * Top‑level request handler exported for Workers or Express wrappers.
 *
 * @param request Incoming HTTP request.
 * @returns HTTP response ready to be sent to the client.
 */
export async function handleRequest(request: Request): Promise<Response> {
  const ctx: InternalRequestContext = {
    requestId: crypto.randomUUID(),
    startTime: Date.now(),
    // The RequestContext interface may contain additional fields; they are
    // populated here if needed by downstream components.
  };

  const router = new RequestRouter();
  try {
    // Fast‑path health‑check handling.
    if (router.isHealthCheck(request)) {
      return jsonResponse(200, { status: "ok", timestamp: Date.now() });
    }

    // Route and normalize the incoming request.
    const normalized: NormalizedRequest = await router.route(request, ctx);

    // Prepare the Gemini adapter and transport.
    const adapter = new GeminiAdapter();
    const payload = await adapter.toGeminiPayload(normalized);

    const endpoint = process.env.GEMINI_ENDPOINT;
    if (!endpoint) {
      throw new HttpError(
        502,
        "upstream_authentication_failed",
        "Gemini endpoint not configured"
      );
    }
    const transport = new SocketTransport(endpoint);

    // Send the request to Gemini.
    const geminiResp: GeminiResponse = await transport.send(payload);

    // Streaming response handling.
    if (normalized.stream) {
      const processor = new StreamProcessor();

      // Assume GeminiResponse contains a `stream` property when streaming.
      const rawStream = (geminiResp as any).stream as ReadableStream;
      if (!rawStream) {
        throw new HttpError(
          502,
          "upstream_error",
          "Expected streaming response but none received"
        );
      }

      const sseStream = new ReadableStream({
        async start(controller) {
          try {
            for await (const chunk of processor.process(rawStream)) {
              const json = JSON.stringify(chunk);
              controller.enqueue(new TextEncoder().encode(formatSse(json)));
            }
            // Flush any pending data after the upstream stream ends.
            const pending = processor.flushPending();
            if (pending) {
              const json = JSON.stringify(pending);
              controller.enqueue(new TextEncoder().encode(formatSse(json)));
            }
            // Signal end of SSE stream.
            controller.close();
          } catch (err) {
            // Propagate error to the client as a final SSE error event.
            const message =
              err instanceof HttpError
                ? err.body.error.message
                : "internal server error";
            const code =
              err instanceof HttpError ? err.body.error.code : "internal_error";
            const errorChunk = {
              error: { code, message },
            };
            controller.enqueue(
              new TextEncoder().encode(formatSse(JSON.stringify(errorChunk)))
            );
            controller.close();
          }
        },
        cancel() {
          // Ensure any underlying resources are released.
          transport.close();
        },
      });

      return new Response(sseStream, {
        status: 200,
        headers: {
          "Content-Type": "text/event-stream; charset=utf-8",
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
        },
      });
    }

    // Non‑streaming path: decode Gemini response to unified API response.
    const apiResp: ApiResponse = adapter.fromGeminiResponse(geminiResp);
    return jsonResponse(200, apiResp);
  } catch (err) {
    // Unified error handling – always return OpenAI‑compatible JSON.
    if (err instanceof HttpError) {
      return jsonResponse(err.status, err.body);
    }

    // Unexpected errors are logged and transformed into a generic 500 response.
    console.error("Unhandled error:", err);
    const genericError = {
      error: {
        code: "internal_error",
        message: "internal server error",
      },
    };
    return jsonResponse(500, genericError);
  } finally {
    // Optional: log request duration for observability.
    const duration = Date.now() - ctx.startTime;
    console.info(
      `Request ${ctx.requestId} completed in ${duration}ms`
    );
  }
}