import { ProviderAdapter, ProviderConfig, ProviderError, ChatResponse } from "../src/providers/providerAdapter";
import axios from "axios";

jest.mock("axios");
const mockedAxios = axios as jest.Mocked<typeof axios>;

describe("ProviderAdapter", () => {
  const config: ProviderConfig = {
    type: "openai",
    endpoint: "https://api.openai.com",
    apiKey: "sk-test-key",
    model: "gpt-4",
  };

  it("should return a plan string on successful response", async () => {
    mockedAxios.post.mockResolvedValue({
      data: { choices: [{ message: { content: "Plan result" } }] },
    } as any);

    const adapter = new ProviderAdapter(config);
    const result = await adapter.plan("Write a poem");
    expect(result).toBe("Plan result");
  });

  it("should throw ProviderError on failed request", async () => {
    mockedAxios.post.mockRejectedValue(new Error("Network error"));
    const adapter = new ProviderAdapter(config);
    await expect(adapter.plan("Fail"))
      .rejects
      .toThrow(ProviderError);
  });
});
