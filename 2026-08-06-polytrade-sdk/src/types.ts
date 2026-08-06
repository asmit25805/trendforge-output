import { z } from 'zod';

/**
 * Core SDK error type. All 4xx responses are transformed into this class.
 */
export class SDKError extends Error {
  /** HTTP status code (e.g., 400, 401, 429) */
  readonly status: number;
  /** Exchange‑specific error code if provided */
  readonly code?: string | number;
  /** Additional details supplied by the exchange */
  readonly details?: unknown;

  constructor(message: string, status: number, code?: string | number, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
    Object.setPrototypeOf(this, SDKError.prototype);
  }
}

/** Supported key types for request signing. */
export enum KeyType {
  /** HMAC‑based signing (hex secret). */
  HMAC = 'hmac',
  /** RSA private key (PEM format). */
  RSA = 'rsa',
  /** Ed25519 private key (PEM format). */
  Ed25519 = 'ed25519',
}

/** Authentication credentials supplied by the user. */
export interface AuthCredentials {
  apiKey: string;
  secretKey: string;
  passphrase?: string;
  keyType?: KeyType;
}

/** Parameters required to place an order. */
export interface OrderParams {
  symbol: string;
  side: 'buy' | 'sell';
  type: 'limit' | 'market';
  quantity: number;
  price?: number;
}

/** Response returned after placing an order. */
export interface OrderResponse {
  orderId: string;
  status: string;
  filledQuantity: number;
  remainingQuantity: number;
}

/** Unsubscribe function type returned by EventBus listeners. */
export type UnsubscribeFn = () => void;

/** Configuration for the token‑bucket rate limiter. */
export interface RateLimitConfig {
  /** Maximum number of tokens in the bucket. */
  capacity: number;
  /** Interval in milliseconds after which tokens are refilled. */
  intervalMs: number;
  /** Optional boost factor for VIP users. */
  boostFactor?: number;
}

/** Simplified order model used throughout the SDK. */
export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  type: 'limit' | 'market';
  quantity: number;
  price?: number;
  status: string;
}

/** Exchange configuration passed to plugins. */
export interface ExchangeConfig {
  name: string;
  baseUrl: string;
  wsUrl?: string;
  auth: AuthCredentials;
}
