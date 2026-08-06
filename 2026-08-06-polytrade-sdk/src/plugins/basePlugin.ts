import { z, ZodSchema } from 'zod';
import { EventBus } from '../util/eventBus';
import { RateLimiter } from '../util/rateLimiter';
import { SignatureProvider, KeyType } from '../auth/signatureProvider';
import {
  ExchangeConfig,
  SDKError,
  AuthCredentials,
  UnsubscribeFn,
} from '../types';

/** Mapping of REST endpoint identifiers to HTTP method, path, and optional response schema. */
export type RestEndpointMap = Record<
  string,
  {
    method: 'GET' | 'POST' | 'DELETE' | 'PUT';
    path: string;
    schema?: ZodSchema<any>;
  }
>;

/** Mapping of WebSocket topic identifiers to channel name and optional payload schema. */
export type WsTopicMap = Record<
  string,
  {
    channel: string;
    schema?: ZodSchema<any>;
  }
>;

/**
 * Abstract base class that all exchange plugins must extend.
 * It provides access to shared utilities such as EventBus, RateLimiter, and SignatureProvider.
 */
export abstract class ExchangePlugin {
  protected config: ExchangeConfig;
  protected eventBus: EventBus;
  protected rateLimiter: RateLimiter;
  protected signatureProvider: SignatureProvider;

  constructor(
    config: ExchangeConfig,
    eventBus: EventBus,
    rateLimiter: RateLimiter,
    signatureProvider: SignatureProvider,
  ) {
    this.config = config;
    this.eventBus = eventBus;
    this.rateLimiter = rateLimiter;
    this.signatureProvider = signatureProvider;
  }

  /** Return the REST endpoints implemented by the plugin. */
  abstract getRestEndpoints(): RestEndpointMap;

  /** Return the WebSocket topics implemented by the plugin. */
  abstract getWsTopics(): WsTopicMap;

  /** Subscribe to a WebSocket topic.
   * @returns Unsubscribe function.
   */
  abstract subscribe(topic: string, listener: (payload: any) => void): UnsubscribeFn;
}
