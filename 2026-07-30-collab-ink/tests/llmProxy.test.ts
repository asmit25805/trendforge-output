import { LLMProxy, ProviderEnum, ProviderConfig, LLMRequest, LLMResponse, RETRY_LIMIT } from "../src/llmProxy";
import { Stroke } from "../src/types";

describe("LLMProxy", () => {
  const dummyStroke: Stroke = {
    id: "stroke-1",
    path: [[0, 0], [10, 10]],
    color: "#ff0000",
    width: 2,
    timestamp: Date.now(),
    userId: "user-1",
  };

  const dummyRequest: LLMRequest = {
    sessionId: "session-123",
    strokes: [dummyStroke],
  };

  test("sendRequest returns a response with answer", async () => {
    const proxy = new LLMProxy();
    const response = await proxy.sendRequest(dummyRequest);
    expect(response).toHaveProperty("answer");
    expect(response).toHaveProperty("requestId");
    expect(typeof response.answer).toBe("string");
  });
});
