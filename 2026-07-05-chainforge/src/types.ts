import { createHash, createHmac } from 'crypto';

/**
 * Represents the lifecycle state of a chain.
 */
export type ChainStatus = 'draft' | 'published' | 'archived';

/**
 * Core metadata for a chain entry in the catalog.
 */
export interface ChainRecord {
  /** URL‑safe identifier, unique across the catalog. */
  slug: string;
  /** Human readable name. */
  title: string;
  /** Short marketing copy. */
  description: string;
  /** Lifecycle state. */
  status: ChainStatus;
  /** ISO‑8601 timestamp of the first version stored. */
  createdAt: string;
  /** ISO‑8601 timestamp of the last modification. */
  updatedAt: string;
}

/**
 * Execution modality for a step.
 */
export type StepType = 'prompt' | 'tool' | 'script';

/**
 * JSON Schema definition used for input and output validation.
 */
export type JSONSchema = Record<string, unknown>;

/**
 * Definition of a single step inside a chain.
 */
export interface StepDefinition {
  /** Stable identifier within the chain. */
  id: string;
  /** Execution modality. */
  type: StepType;
  /** Raw prompt text, tool spec, or JavaScript source. */
  payload: string;
  /** Expected input shape. */
  inputSchema: JSONSchema;
  /** Expected output shape. */
  outputSchema: JSONSchema;
}

/**
 * Immutable version record for a chain.
 */
export interface ChainVersionRecord {
  /** Foreign key to the parent chain. */
  chainSlug: string;
  /** Semantic version or SHA‑256 digest. */
  version: string;
  /** Ordered list of step payloads. */
  steps: StepDefinition[];
  /** SHA‑256 of the JSON representation for deduplication. */
  checksum: string;
  /** ISO‑8601 timestamp when the version was published; null for drafts. */
  publishedAt: string | null;
}

/**
 * Result of a single step execution inside the sandbox.
 */
export interface StepResult {
  /** Identifier of the step that produced this result. */
  stepId: string;
  /** Deterministic hash of the step output. */
  hash: string;
  /** Captured stdout from the sandbox. */
  stdout: string;
  /** Captured stderr from the sandbox. */
  stderr: string;
  /** Arbitrary JSON payload returned by the step. */
  output: unknown;
}

/**
 * Aggregated result of a full chain execution.
 */
export interface ExecutionResult {
  /** Deterministic hash of the entire run (e.g., Merkle root of step hashes). */
  runHash: string;
  /** Ordered list of step results. */
  steps: StepResult[];
  /** Overall execution logs (concatenated stdout/stderr). */
  logs: string;
  /** Optional human‑readable stdout of the final step. */
  finalStdout?: string;
}

/**
 * Per‑origin or per‑user rate‑limit configuration.
 */
export interface RateLimits {
  /** Maximum number of submissions allowed per hour. */
  hourlyCap: number;
  /** Maximum number of submissions allowed per day. */
  dailyCap: number;
}

/**
 * JWT‑based session token issued after successful OAuth flow.
 */
export interface SessionToken {
  /** Signed JWT string. */
  jwt: string;
  /** Epoch milliseconds when the token expires. */
  expiresAt: number;
  /** GitHub login identifier of the user. */
  userId: string;
}

/**
 * Payload stored inside the JWT.
 */
interface JwtPayload {
  sub: string; // userId
  iat: number; // issued at (seconds)
  exp: number; // expires at (seconds)
}

/**
 * Enumerates machine‑readable error codes returned by the API.
 */
export const enum ErrorCode {
  InvalidSignature = 'INVALID_SIGNATURE',
  DuplicateFingerprint = 'DUPLICATE_FINGERPRINT',
  ValidationFailed = 'VALIDATION_FAILED',
  RateLimitExceeded = 'RATE_LIMIT_EXCEEDED',
  TransientFailure = 'TRANSIENT_FAILURE',
}

/**
 * Compute a SHA‑256 hex digest of any JSON‑serializable value.
 *
 * @param data - The value to hash; will be JSON‑stringified.
 * @returns Hexadecimal SHA‑256 digest.
 */
export function computeChecksum(data: unknown): string {
  const json = JSON.stringify(data);
  const hash = createHash('sha256');
  hash.update(json);
  return hash.digest('hex');
}

/**
 * Validate that an object conforms to the {@link ChainRecord} shape.
 *
 * @param obj - Candidate object.
 * @returns True if the object matches the interface; otherwise false.
 */
export function isValidChainRecord(obj: unknown): obj is ChainRecord {
  if (typeof obj !== 'object' || obj === null) return false;
  const rec = obj as Partial<ChainRecord>;
  return (
    typeof rec.slug === 'string' &&
    typeof rec.title === 'string' &&
    typeof rec.description === 'string' &&
    (rec.status === 'draft' ||
      rec.status === 'published' ||
      rec.status === 'archived') &&
    typeof rec.createdAt === 'string' &&
    typeof rec.updatedAt === 'string'
  );
}

/**
 * Validate that an object conforms to the {@link ChainVersionRecord} shape.
 *
 * @param obj - Candidate object.
 * @returns True if the object matches the interface; otherwise false.
 */
export function isValidChainVersionRecord(obj: unknown): obj is ChainVersionRecord {
  if (typeof obj !== 'object' || obj === null) return false;
  const rec = obj as Partial<ChainVersionRecord>;
  if (
    typeof rec.chainSlug !== 'string' ||
    typeof rec.version !== 'string' ||
    !Array.isArray(rec.steps) ||
    typeof rec.checksum !== 'string' ||
    (rec.publishedAt !== null && typeof rec.publishedAt !== 'string')
  ) {
    return false;
  }
  return rec.steps.every(isValidStepDefinition);
}

/**
 * Validate that an object conforms to the {@link StepDefinition} shape.
 *
 * @param obj - Candidate object.
 * @returns True if the object matches the interface; otherwise false.
 */
export function isValidStepDefinition(obj: unknown): obj is StepDefinition {
  if (typeof obj !== 'object' || obj === null) return false;
  const step = obj as Partial<StepDefinition>;
  return (
    typeof step.id === 'string' &&
    (step.type === 'prompt' ||
      step.type === 'tool' ||
      step.type === 'script') &&
    typeof step.payload === 'string' &&
    typeof step.inputSchema === 'object' &&
    step.inputSchema !== null &&
    typeof step.outputSchema === 'object' &&
    step.outputSchema !== null
  );
}

/**
 * Generate a signed JWT session token.
 *
 * @param payload - Minimal JWT payload containing the user identifier.
 * @param secret - Server‑side secret used for HMAC signing.
 * @param expiresInSec - Expiration interval in seconds.
 * @returns A {@link SessionToken} ready for cookie storage.
 */
export function generateSessionToken(
  payload: { userId: string },
  secret: string,
  expiresInSec: number
): SessionToken {
  const iat = Math.floor(Date.now() / 1000);
  const exp = iat + expiresInSec;
  const jwtPayload: JwtPayload = {
    sub: payload.userId,
    iat,
    exp,
  };
  const base64 = (obj: unknown) =>
    Buffer.from(JSON.stringify(obj)).toString('base64url');
  const header = base64({ alg: 'HS256', typ: 'JWT' });
  const body = base64(jwtPayload);
  const signature = createHmac('sha256', secret)
    .update(`${header}.${body}`)
    .digest('base64url');
  const jwt = `${header}.${body}.${signature}`;
  return {
    jwt,
    expiresAt: exp * 1000,
    userId: payload.userId,
  };
}

/**
 * Verify a JWT session token and extract its payload.
 *
 * @param token - JWT string to verify.
 * @param secret - Server‑side secret used for HMAC verification.
 * @returns The decoded {@link JwtPayload} if verification succeeds.
 * @throws Will throw an error with {@link ErrorCode.InvalidSignature} if verification fails.
 */
export function verifySessionToken(token: string, secret: string): JwtPayload {
  const [headerB64, bodyB64, sigB64] = token.split('.');
  if (!headerB64 || !bodyB64 || !sigB64) {
    throw new Error(ErrorCode.InvalidSignature);
  }
  const expectedSig = createHmac('sha256', secret)
    .update(`${headerB64}.${bodyB64}`)
    .digest('base64url');
  if (expectedSig !== sigB64) {
    throw new Error(ErrorCode.InvalidSignature);
  }
  const payloadJson = Buffer.from(bodyB64, 'base64url').toString('utf8');
  const payload = JSON.parse(payloadJson) as JwtPayload;
  const now = Math.floor(Date.now() / 1000);
  if (payload.exp < now) {
    throw new Error(ErrorCode.InvalidSignature);
  }
  return payload;
}

/**
 * Compute a deterministic hash for an execution result.
 *
 * The hash is derived from the ordered list of step hashes using a Merkle‑style
 * concatenation and SHA‑256.
 *
 * @param steps - Ordered step results.
 * @returns Hexadecimal SHA‑256 digest representing the full run.
 */
export function computeRunHash(steps: StepResult[]): string {
  const combined = steps.map((s) => s.hash).join('');
  const hash = createHash('sha256');
  hash.update(combined);
  return hash.digest('hex');
}

/**
 * Create an {@link ExecutionResult} from raw step results.
 *
 * @param steps - Ordered step results produced by the sandbox.
 * @returns Fully populated execution result with deterministic run hash and aggregated logs.
 */
export function buildExecutionResult(steps: StepResult[]): ExecutionResult {
  const logs = steps.map((s) => `${s.stdout}\n${s.stderr}`).join('\n');
  const runHash = computeRunHash(steps);
  const finalStdout = steps.length > 0 ? steps[steps.length - 1].stdout : undefined;
  return {
    runHash,
    steps,
    logs,
    finalStdout,
  };
}

/**
 * Simple in‑memory rate‑limit tracker used by {@link RateLimiter}.
 *
 * The implementation is deliberately lightweight; production deployments should
 * replace it with a distributed KV store (e.g., Cloudflare KV) to survive restarts.
 */
export class InMemoryRateTracker {
  private hourly: Map<string, { count: number; reset: number }> = new Map();
  private daily: Map<string, { count: number; reset: number }> = new Map();

  /**
   * Check whether a fingerprint is within the configured limits.
   *
   * @param fp - Fingerprint string (e.g., SHA‑256 of a chain payload).
   * @param limits - Rate limit configuration.
   * @returns True if the fingerprint is allowed; otherwise false.
   */
  public check(fp: string, limits: RateLimits): boolean {
    const now = Date.now();
    const hourWindow = 60 * 60 * 1000;
    const dayWindow = 24 * 60 * 60 * 1000;

    const hourEntry = this.hourly.get(fp);
    if (!hourEntry || now > hourEntry.reset) {
      this.hourly.set(fp, { count: 1, reset: now + hourWindow });
    } else if (hourEntry.count < limits.hourlyCap) {
      hourEntry.count += 1;
    } else {
      return false;
    }

    const dayEntry = this.daily.get(fp);
    if (!dayEntry || now > dayEntry.reset) {
      this.daily.set(fp, { count: 1, reset: now + dayWindow });
    } else if (dayEntry.count < limits.dailyCap) {
      dayEntry.count += 1;
    } else {
      return false;
    }

    return true;
  }

  /**
   * Increment counters for a fingerprint without checking limits.
   *
   * @param fp - Fingerprint string.
   */
  public record(fp: string): void {
    const now = Date.now();
    const hourWindow = 60 * 60 * 1000;
    const dayWindow = 24 * 60 * 60 * 1000;

    const hourEntry = this.hourly.get(fp);
    if (!hourEntry || now > hourEntry.reset) {
      this.hourly.set(fp, { count: 1, reset: now + hourWindow });
    } else {
      hourEntry.count += 1;
    }

    const dayEntry = this.daily.get(fp);
    if (!dayEntry || now > dayEntry.reset) {
      this.daily.set(fp, { count: 1, reset: now + dayWindow });
    } else {
      dayEntry.count += 1;
    }
  }
}

/**
 * Helper to safely parse JSON with a deterministic error code.
 *
 * @param raw - Raw JSON string.
 * @returns Parsed object.
 * @throws Will throw an error with {@link ErrorCode.ValidationFailed} on parse error.
 */
export function safeParseJson<T = unknown>(raw: string): T {
  try {
    return JSON.parse(raw) as T;
  } catch {
    const err = new Error('Invalid JSON payload');
    (err as any).code = ErrorCode.ValidationFailed;
    throw err;
  }
}

/**
 * Validate that a chain definition contains a non‑empty slug and at least one step.
 *
 * @param chain - Chain definition to validate.
 * @throws Will throw an error with {@link ErrorCode.ValidationFailed} if validation fails.
 */
export function validateChainDefinition(chain: {
  slug: string;
  steps: StepDefinition[];
}): void {
  if (typeof chain.slug !== 'string' || chain.slug.trim() === '') {
    const err = new Error('Chain slug must be a non‑empty string');
    (err as any).code = ErrorCode.ValidationFailed;
    throw err;
  }
  if (!Array.isArray(chain.steps) || chain.steps.length === 0) {
    const err = new Error('Chain must contain at least one step');
    (err as any).code = ErrorCode.ValidationFailed;
    throw err;
  }
  for (const step of chain.steps) {
    if (!isValidStepDefinition(step)) {
      const err = new Error(`Invalid step definition: ${step.id}`);
      (err as any).code = ErrorCode.ValidationFailed;
      throw err;
    }
  }
}

/**
 * Exported collection of all public types for convenient import elsewhere.
 */
export const Types = {
  ChainRecord,
  ChainVersionRecord,
  StepDefinition,
  StepResult,
  ExecutionResult,
  RateLimits,
  SessionToken,
  ErrorCode,
  InMemoryRateTracker,
};