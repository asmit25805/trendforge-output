import { User, RETRY_LIMIT, exponentialBackoff } from "./types";
import { decode as jwtDecode, JwtPayload } from "jsonwebtoken";
import fetch from "node-fetch";

/**
 * Error thrown when authentication fails.
 */
export class AuthError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthError";
  }
}

/**
 * Options for constructing an AuthMiddleware instance.
 */
export interface AuthMiddlewareConfig {
  /** Base URL of the external authentication service (e.g., https://auth.example.com). */
  authBaseUrl: string;
  /** Optional timeout in milliseconds for HTTP requests to the auth service. */
  timeoutMs?: number;
}

/**
 * Express middleware that validates JWTs against an external auth service.
 */
export class AuthMiddleware {
  private baseUrl: string;
  private timeoutMs: number;

  constructor(config: AuthMiddlewareConfig) {
    this.baseUrl = config.authBaseUrl;
    this.timeoutMs = config.timeoutMs ?? 3000;
  }

  /** Express middleware function */
  async middleware(req: any, res: any, next: any) {
    const authHeader = req.headers["authorization"] as string | undefined;
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return next(new AuthError("Missing or malformed Authorization header"));
    }
    const token = authHeader.slice(7);
    try {
      const payload = jwtDecode(token) as JwtPayload;
      // Optionally verify with external service – simple health‑check placeholder
      const response = await fetch(`${this.baseUrl}/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
        timeout: this.timeoutMs,
      });
      if (!response.ok) throw new AuthError("Token verification failed");
      const user: User = { id: payload.sub as string, name: payload.name as string, payload };
      (req as any).user = user;
      next();
    } catch (err) {
      next(err instanceof AuthError ? err : new AuthError("Invalid token"));
    }
  }
}
