import { RequestRouter } from "../src/router";
import { HttpError } from "../src/adapter/gemini";
import { NormalizedRequest } from "../src/types";

type SimpleHeaders = {
  get(name: string): string | null;
};

function createRequest(
  method: string,
  path: string,
  body?: Record<string, unknown>
): {
  method: string;
  url: string;
  headers: SimpleHeaders;
  json: () => Promise<Record<string, unknown>>;
} {
  const headers: SimpleHeaders = {
    get: (name: string) => {
      if (name.toLowerCase() === "content-type") {
        return "application/json";
      }
      return null;
    },
  };
  return {
    method,
    url: `http://localhost${path}`,
    headers,
    json: async () => body ?? {},
  };
}

describe("RequestRouter", () => {
  const router = new RequestRouter();

  test("detects health‑check endpoint", () => {
    const req = createRequest("GET", "/health");
    expect(router.isHealthCheck(req as any)).toBe(true);
  });

  test("routes OpenAI chat completion request and normalizes payload", async () => {
    const payload = {
      model: "gemini-1.5-pro",
      messages: [{ role: "user", content: "Hello" }],
      temperature: 0.5,
      stream: false,
    };
    const req = createRequest("POST", "/v1/chat/completions", payload);
    const normalized = (await router.route(req as any, {} as any)) as NormalizedRequest;

    expect(normalized.model).toBe("gemini-1.5-pro");
    expect(normalized.messages).toEqual(payload.messages);
    expect(normalized.temperature).toBe(0.5);
    expect(normalized.stream).toBe(false);
    expect(normalized.id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i
    );
  });

  test("routes Google Gemini endpoint and normalizes payload", async () => {
    const payload = {
      model: "gemini-1.5-pro",
      messages: [{ role: "user", content: "Hi there" }],
      temperature: 0.8,
      stream: true,
    };
    const req = createRequest("POST", "/gemini/v1/chat", payload);
    const normalized = (await router.route(req as any, {} as any)) as NormalizedRequest;

    expect(normalized.model).toBe("gemini-1.5-pro");
    expect(normalized.stream).toBe(true);
    expect(normalized.temperature).toBe(0.8);
    expect(normalized.messages).toEqual(payload.messages);
  });

  test("routes Anthropic completion endpoint and normalizes payload", async () => {
    const payload = {
      model: "gemini-1.5-pro",
      prompt: "Write a poem",
      temperature: 0.6,
      stream: false,
    };
    const req = createRequest("POST", "/anthropic/v1/complete", payload);
    const normalized = (await router.route(req as any, {} as any)) as NormalizedRequest;

    expect(normalized.model).toBe("gemini-1.5-pro");
    // Anthropic payload uses `prompt`; router should map it to a single user message.
    expect(normalized.messages).toEqual([
      { role: "user", content: "Write a poem" },
    ]);
    expect(normalized.stream).toBe(false);
    expect(normalized.temperature).toBe(0.6);
  });

  test("throws HttpError with 400 when required fields are missing", async () => {
    const payload = {
      // model is omitted intentionally
      messages: [{ role: "user", content: "Missing model" }],
    };
    const req = createRequest("POST", "/v1/chat/completions", payload);
    await expect(router.route(req as any, {} as any)).rejects.toMatchObject({
      status: 400,
      code: "invalid_request",
    } as HttpError);
  });

  test("throws HttpError with 400 for unsupported model", async () => {
    const payload = {
      model: "unsupported-model",
      messages: [{ role: "user", content: "Test" }],
    };
    const req = createRequest("POST", "/v1/chat/completions", payload);
    await expect(router.route(req as any, {} as any)).rejects.toMatchObject({
      status: 400,
      code: "invalid_request",
    } as HttpError);
  });
});