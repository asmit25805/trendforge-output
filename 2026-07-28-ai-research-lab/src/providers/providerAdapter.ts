import { AxiosInstance, AxiosResponse } from "axios";
import axios from "axios";
import Ajv, { ValidateFunction } from "ajv";
import { randomUUID } from "crypto";
import { EventEmitter } from "eventemitter3";
import {
  RunStatus,
  PermissionProfile,
  Artifact,
  ArtifactKind,
} from "../core/models";

/** Configuration options for a provider. */
export interface ProviderConfig {
  /** Provider type, e.g., "openai". */
  type: string;
  /** Base endpoint URL for the provider API. */
  endpoint: string;
  /** API key or token used for authentication. */
  apiKey: string;
  /** Model name to be used for completions. */
  model: string;
  /** Optional request timeout in milliseconds. */
  timeoutMs?: number;
}

export class ProviderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProviderError";
  }
}

export interface ChatResponse {
  role: string;
  content: string;
}

export class ProviderAdapter extends EventEmitter {
  private config: ProviderConfig;
  private http: AxiosInstance;
  private validator: ValidateFunction;

  constructor(config: ProviderConfig) {
    super();
    this.config = config;
    this.http = axios.create({ baseURL: config.endpoint, timeout: config.timeoutMs ?? 60000 });
    const ajv = new Ajv();
    // Simple schema for demonstration; real schema would be more detailed.
    const schema = {
      type: "object",
      properties: { role: { type: "string" }, content: { type: "string" } },
      required: ["role", "content"],
    };
    this.validator = ajv.compile(schema);
  }

  async plan(prompt: string): Promise<string> {
    try {
      const response: AxiosResponse = await this.http.post("/v1/chat/completions", {
        model: this.config.model,
        messages: [{ role: "user", content: prompt }],
      }, {
        headers: { Authorization: `Bearer ${this.config.apiKey}` },
      });
      const data = response.data as any;
      const choice = data.choices?.[0]?.message?.content;
      if (!choice) throw new ProviderError("Empty response from provider");
      return choice;
    } catch (err: any) {
      throw new ProviderError(err.message ?? "Provider request failed");
    }
  }
}
