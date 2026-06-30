import { GeminiAdapter, HttpError } from "../src/adapter/gemini";
import { CacheManager } from "../src/adapter/gemini";
import {
  NormalizedRequest,
  GeminiPayload,
  GeminiResponse,
  ApiResponse,
} from "../src/types";

describe("GeminiAdapter", () => {
  const mockToken = "mocked-token-123";
  let adapter: GeminiAdapter;

  beforeEach(() => {
    jest.spyOn(CacheManager.prototype, "getToken").mockResolvedValue(mockToken);
    adapter = new GeminiAdapter();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  test("toGeminiPayload maps NormalizedRequest fields correctly", async () => {
    const normalized: NormalizedRequest = {
      id: "req-1",
      model: "gemini-1.5-pro",
      messages: [
        { role: "user", content: "Hello" },
        { role: "assistant", content: "Hi there!" },
      ],
      temperature: 0.6,
      stream: true,
      metadata: {},
    };

    const payload: GeminiPayload = await adapter.toGeminiPayload(normalized);

    expect(payload.model).toBe(normalized.model);
    expect(payload.temperature).toBe(normalized.temperature);
    expect(payload.stream).toBe(normalized.stream);
    expect(payload.prompt?.messages).toEqual(normalized.messages);
    // The adapter should attach the auth token to the payload (e.g., via a header field)
    // Since the token is not part of GeminiPayload definition, we verify that the
    // internal cache was consulted.
    expect(CacheManager.prototype.getToken).toHaveBeenCalled();
  });

  test("toGeminiPayload throws HttpError when model is missing", async () => {
    const normalized: NormalizedRequest = {
      id: "req-2",
      model: "",
      messages: [{ role: "user", content: "Test" }],
      temperature: 0.7,
      stream: false,
      metadata: {},
    };

    await expect(adapter.toGeminiPayload(normalized)).rejects.toMatchObject({
      status: 400,
      code: "invalid_request",
    });
  });

  test("fromGeminiResponse converts successful GeminiResponse to ApiResponse", async () => {
    const geminiResp: GeminiResponse = {
      candidates: [
        {
          content: {
            parts: [{ text: "Hello, world!" }],
          },
          finishReason: "STOP",
        },
      ],
      usageMetadata: {
        promptTokenCount: 5,
        candidatesTokenCount: 7,
        totalTokenCount: 12,
      },
    };

    const apiResp: ApiResponse = await adapter.fromGeminiResponse(geminiResp, {
      id: "req-3",
      stream: false,
    });

    expect(apiResp.id).toBe("req-3");
    expect(apiResp.object).toBe("chat.completion");
    expect(apiResp.choices).toHaveLength(1);
    expect(apiResp.choices[0].message?.content).toBe("Hello, world!");
    expect(apiResp.usage?.promptTokens).toBe(5);
    expect(apiResp.usage?.completionTokens).toBe(7);
    expect(apiResp.usage?.totalTokens).toBe(12);
  });

  test("fromGeminiResponse throws HttpError on upstream authentication failure", async () => {
    const geminiResp: GeminiResponse = {
      // Simulate an upstream error structure; the adapter should detect it.
      error: {
        code: 401,
        message: "Invalid auth token",
      },
    } as any;

    await expect(
      adapter.fromGeminiResponse(geminiResp, { id: "req-4", stream: false })
    ).rejects.toMatchObject({
      status: 502,
      code: "upstream_authentication_failed",
    });
  });

  test("adapter retrieves token from CacheManager only once per request", async () => {
    const normalized: NormalizedRequest = {
      id: "req-5",
      model: "gemini-1.5-pro",
      messages: [{ role: "user", content: "Ping" }],
      temperature: 0.5,
      stream: false,
      metadata: {},
    };

    await adapter.toGeminiPayload(normalized);
    await adapter.toGeminiPayload(normalized);

    // getToken should be called twice because each call creates a new payload.
    // The mock ensures the method is invoked; the exact count verifies caching logic.
    expect(CacheManager.prototype.getToken).toHaveBeenCalledTimes(2);
  });

  test("fromGeminiResponse preserves streaming flag in ApiResponse", async () => {
    const geminiResp: GeminiResponse = {
      candidates: [
        {
          content: {
            parts: [{ text: "Streaming part 1" }],
          },
          finishReason: "STOP",
        },
      ],
    };

    const apiResp: ApiResponse = await adapter.fromGeminiResponse(geminiResp, {
      id: "req-6",
      stream: true,
    });

    expect(apiResp.id).toBe("req-6");
    expect(apiResp.choices[0].delta?.content).toBe("Streaming part 1");
    // When streaming, the response object may omit usage; ensure it is undefined.
    expect(apiResp.usage).toBeUndefined();
  });
});