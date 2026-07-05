import { Database, verbose } from 'sqlite3';
import { promisify } from 'util';
import { createHash, randomBytes, createHmac } from 'crypto';
import { SessionToken } from '../types.ts';

/**
 * Simple redirect response containing the URL the client should visit.
 */
export interface RedirectResponse {
  /** URL to which the client must be redirected. */
  url: string;
}

/**
 * AuthManager handles the GitHub OAuth flow, CSRF nonce storage, and JWT session creation.
 *
 * All side‑effects are logged before they occur. Methods are idempotent where possible.
 */
export class AuthManager {
  private db: Database;
  private runAsync: (sql: string, params?: unknown[]) => Promise<void>;
  private getAsync: (sql: string, params?: unknown[]) => Promise<any>;

  /** Maximum number of retry attempts for transient operations. */
  private static readonly MAX_RETRIES = 3;

  /** Base delay (ms) for exponential back‑off between retries. */
  private static readonly BASE_DELAY_MS = 150;

  /** JWT expiration interval (ms). */
  private static readonly JWT_TTL_MS = 60 * 60 * 1000; // 1 hour

  /**
   * Constructs an AuthManager backed by a SQLite database.
   *
   * @param dbPath Path to the SQLite file; defaults to in‑memory.
   */
  constructor(dbPath: string = ':memory:') {
    const sqlite3 = verbose();
    this.db = new sqlite3.Database(dbPath, (err) => {
      if (err) {
        console.error(`[AuthManager][init] DB open error: ${err.message}`);
        throw err;
      }
    });

    this.runAsync = promisify(this.db.run).bind(this.db);
    this.getAsync = promisify(this.db.get).bind(this.db);

    this.initializeSchema()
      .then(() => console.info('[AuthManager][init] Schema ready'))
      .catch((e) => {
        console.error(`[AuthManager][init] Schema error: ${e.message}`);
        throw e;
      });
  }

  /** Ensure required tables exist. */
  private async initializeSchema(): Promise<void> {
    const schema = `
      CREATE TABLE IF NOT EXISTS oauth_nonces (
        nonce TEXT PRIMARY KEY,
        createdAt TEXT NOT NULL,
        expiresAt TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS oauth_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        userId TEXT NOT NULL,
        action TEXT NOT NULL,
        timestamp TEXT NOT NULL
      );
    `;
    await this.execWithRetry(schema);
  }

  /** Execute a SQL statement with retry on transient SQLite errors. */
  private async execWithRetry(sql: string, params: unknown[] = []): Promise<void> {
    let attempt = 0;
    while (true) {
      try {
        await new Promise<void>((resolve, reject) => {
          this.db.run(sql, params, (err) => (err ? reject(err) : resolve()));
        });
        return;
      } catch (err: any) {
        const transient = ['SQLITE_BUSY', 'SQLITE_LOCKED'].some((code) =>
          err.message.includes(code)
        );
        if (!transient || ++attempt >= AuthManager.MAX_RETRIES) {
          console.error(`[AuthManager][execWithRetry] Fatal error: ${err.message}`);
          throw err;
        }
        const delay = AuthManager.BASE_DELAY_MS * 2 ** (attempt - 1);
        console.warn(`[AuthManager][execWithRetry] Transient error (${err.message}), retry ${attempt}/${AuthManager.MAX_RETRIES} after ${delay}ms`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  /** Store a newly generated nonce with a short expiration (10 minutes). */
  private async storeNonce(nonce: string): Promise<void> {
    const now = new Date();
    const expires = new Date(now.getTime() + 10 * 60 * 1000);
    const sql = `INSERT INTO oauth_nonces (nonce, createdAt, expiresAt) VALUES (?, ?, ?)`;
    await this.execWithRetry(sql, [nonce, now.toISOString(), expires.toISOString()]);
    console.info(`[AuthManager][storeNonce] Stored nonce ${nonce}`);
  }

  /** Validate a nonce and delete it atomically. Returns the associated creation time if valid. */
  private async validateAndConsumeNonce(nonce: string): Promise<Date> {
    const sqlSelect = `SELECT createdAt, expiresAt FROM oauth_nonces WHERE nonce = ?`;
    const row = await this.getAsync(sqlSelect, [nonce]);
    if (!row) {
      console.warn(`[AuthManager][validateNonce] Missing nonce ${nonce}`);
      throw new Error('Invalid CSRF nonce');
    }

    const now = new Date();
    const expiresAt = new Date(row.expiresAt);
    if (now > expiresAt) {
      console.warn(`[AuthManager][validateNonce] Expired nonce ${nonce}`);
      await this.execWithRetry(`DELETE FROM oauth_nonces WHERE nonce = ?`, [nonce]);
      throw new Error('CSRF nonce expired');
    }

    await this.execWithRetry(`DELETE FROM oauth_nonces WHERE nonce = ?`, [nonce]);
    console.info(`[AuthManager][validateNonce] Consumed nonce ${nonce}`);
    return new Date(row.createdAt);
  }

  /**
   * Initiates the GitHub OAuth flow.
   *
   * @param state Optional opaque state supplied by the caller; will be ignored in favor of a CSRF nonce.
   * @returns RedirectResponse containing the GitHub authorization URL.
   */
  async startOAuth(state?: string): Promise<RedirectResponse> {
    console.info('[AuthManager][startOAuth] Generating CSRF nonce');
    const nonce = randomBytes(24).toString('hex');
    await this.storeNonce(nonce);

    const clientId = process.env.GITHUB_CLIENT_ID;
    const redirectUri = process.env.GITHUB_OAUTH_CALLBACK;
    if (!clientId || !redirectUri) {
      console.error('[AuthManager][startOAuth] Missing GITHUB_CLIENT_ID or GITHUB_OAUTH_CALLBACK');
      throw new Error('OAuth configuration missing');
    }

    const url = new URL('https://github.com/login/oauth/authorize');
    url.searchParams.set('client_id', clientId);
    url.searchParams.set('redirect_uri', redirectUri);
    url.searchParams.set('state', nonce);
    url.searchParams.set('allow_signup', 'true');

    console.info(`[AuthManager][startOAuth] Redirect URL prepared ${url.toString()}`);
    return { url: url.toString() };
  }

  /**
   * Completes the OAuth flow by exchanging the code for a token, fetching the user, and issuing a JWT.
   *
   * @param callbackParams URLSearchParams received from GitHub callback.
   * @returns SessionToken containing a signed JWT and expiration.
   */
  async finishOAuth(callbackParams: URLSearchParams): Promise<SessionToken> {
    const code = callbackParams.get('code');
    const nonce = callbackParams.get('state');

    if (!code || !nonce) {
      console.warn('[AuthManager][finishOAuth] Missing code or state in callback');
      throw new Error('Invalid OAuth callback parameters');
    }

    // Validate CSRF nonce first
    await this.validateAndConsumeNonce(nonce);

    const clientId = process.env.GITHUB_CLIENT_ID;
    const clientSecret = process.env.GITHUB_CLIENT_SECRET;
    if (!clientId || !clientSecret) {
      console.error('[AuthManager][finishOAuth] Missing client credentials');
      throw new Error('OAuth configuration missing');
    }

    // Exchange code for access token with retry
    const token = await this.retryAsync(async () => {
      const resp = await fetch('https://github.com/login/oauth/access_token', {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          client_id: clientId,
          client_secret: clientSecret,
          code,
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        console.error(`[AuthManager][finishOAuth] Token exchange failed: ${resp.status} ${txt}`);
        throw new Error('Failed to exchange code for token');
      }
      const data = (await resp.json()) as { access_token?: string; error?: string };
      if (data.error || !data.access_token) {
        console.error(`[AuthManager][finishOAuth] Token response error: ${JSON.stringify(data)}`);
        throw new Error('Invalid token response');
      }
      return data.access_token;
    });

    // Fetch user profile
    const userLogin = await this.retryAsync(async () => {
      const resp = await fetch('https://api.github.com/user', {
        headers: {
          Authorization: `token ${token}`,
          Accept: 'application/vnd.github.v3+json',
          'User-Agent': 'chainforge-auth',
        },
      });
      if (!resp.ok) {
        console.error(`[AuthManager][finishOAuth] User fetch failed: ${resp.status}`);
        throw new Error('Failed to fetch user profile');
      }
      const data = (await resp.json()) as { login?: string };
      if (!data.login) {
        console.error(`[AuthManager][finishOAuth] Missing login in user data`);
        throw new Error('Invalid user data');
      }
      return data.login;
    });

    // Create JWT
    const nowSec = Math.floor(Date.now() / 1000);
    const expSec = nowSec + Math.floor(AuthManager.JWT_TTL_MS / 1000);
    const header = Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url');
    const payload = Buffer.from(
      JSON.stringify({ sub: userLogin, iat: nowSec, exp: expSec })
    ).toString('base64url');
    const secret = process.env.JWT_SECRET;
    if (!secret) {
      console.error('[AuthManager][finishOAuth] Missing JWT_SECRET');
      throw new Error('JWT configuration missing');
    }
    const signature = createHmac('sha256', secret)
      .update(`${header}.${payload}`)
      .digest('base64url');
    const jwt = `${header}.${payload}.${signature}`;

    // Record successful login
    await this.recordRun(userLogin, 'login');

    console.info(`[AuthManager][finishOAuth] Issued JWT for ${userLogin}`);
    return {
      jwt,
      expiresAt: Date.now() + AuthManager.JWT_TTL_MS,
      userId: userLogin,
    };
  }

  /** Record an OAuth‑related action in the run history table. */
  private async recordRun(userId: string, action: string): Promise<void> {
    const sql = `INSERT INTO oauth_runs (userId, action, timestamp) VALUES (?, ?, ?)`;
    const now = new Date().toISOString();
    await this.execWithRetry(sql, [userId, action, now]);
    console.info(`[AuthManager][recordRun] Recorded ${action} for ${userId}`);
  }

  /**
   * Generic retry wrapper for async functions that may fail transiently (e.g., network errors).
   *
   * @param fn Async function to execute.
   * @returns Resolved value of the function.
   */
  private async retryAsync<T>(fn: () => Promise<T>): Promise<T> {
    let attempt = 0;
    while (true) {
      try {
        return await fn();
      } catch (err: any) {
        const transient = err.name === 'FetchError' || err.message.includes('network');
        if (!transient || ++attempt >= AuthManager.MAX_RETRIES) {
          console.error(`[AuthManager][retryAsync] Fatal error after ${attempt} attempts: ${err.message}`);
          throw err;
        }
        const delay = AuthManager.BASE_DELAY_MS * 2 ** (attempt - 1);
        console.warn(`[AuthManager][retryAsync] Transient error (${err.message}), retry ${attempt}/${AuthManager.MAX_RETRIES} after ${delay}ms`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }
}