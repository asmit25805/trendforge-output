import { Database, verbose } from 'sqlite3';
import { promisify } from 'util';
import { RateLimits } from './types.ts';

/**
 * Persistent rate‑limiter that tracks fingerprint usage over time.
 *
 * All public methods are async and log their intent before performing any
 * side‑effects. Transient SQLite errors are retried up to three times with
 * exponential back‑off.
 */
export class RateLimiter {
  private db: Database;
  private runAsync: (sql: string, params?: unknown[]) => Promise<void>;
  private getAsync: (sql: string, params?: unknown[]) => Promise<any>;
  private allAsync: (sql: string, params?: unknown[]) => Promise<any[]>;

  /** Maximum number of retry attempts for transient SQLite operations. */
  private static readonly MAX_RETRIES = 3;
  /** Base delay (ms) for exponential back‑off between retries. */
  private static readonly BASE_DELAY_MS = 120;

  /**
   * Initialise a new RateLimiter backed by a SQLite database.
   *
   * @param dbPath Path to the SQLite file; defaults to in‑memory.
   */
  constructor(dbPath: string = ':memory:') {
    const sqlite3 = verbose();
    this.db = new sqlite3.Database(dbPath, (err) => {
      if (err) {
        console.error(`[RateLimiter][init] DB open error: ${err.message}`);
        throw err;
      }
    });

    this.runAsync = promisify(this.db.run).bind(this.db);
    this.getAsync = promisify(this.db.get).bind(this.db);
    this.allAsync = promisify(this.db.all).bind(this.db);

    this.initializeSchema()
      .then(() => console.info('[RateLimiter][init] Schema ready'))
      .catch((e) => {
        console.error(`[RateLimiter][init] Schema error: ${e.message}`);
        throw e;
      });
  }

  /** Ensure the usage table exists. */
  private async initializeSchema(): Promise<void> {
    const schema = `
      CREATE TABLE IF NOT EXISTS rate_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint TEXT NOT NULL,
        ts INTEGER NOT NULL
      );
      CREATE INDEX IF NOT EXISTS idx_fingerprint_ts ON rate_usage (fingerprint, ts);
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
        if (!transient || ++attempt >= RateLimiter.MAX_RETRIES) {
          console.error(`[RateLimiter][execWithRetry] Fatal error: ${err.message}`);
          throw err;
        }
        const delay = RateLimiter.BASE_DELAY_MS * 2 ** (attempt - 1);
        console.warn(`[RateLimiter][execWithRetry] Transient error (${err.message}), retry ${attempt}/${RateLimiter.MAX_RETRIES} after ${delay}ms`);
        await new Promise((r) => setTimeout(r, delay));
      }
    }
  }

  /**
   * Check whether a fingerprint is still under the provided hourly and daily caps.
   *
   * @param fp   Fingerprint to check (e.g., SHA‑256 of payload).
   * @param caps Rate limits to enforce.
   * @returns    `true` if the fingerprint is below both caps, otherwise `false`.
   */
  async checkFingerprint(fp: string, caps: RateLimits): Promise<boolean> {
    console.info(`[RateLimiter][checkFingerprint] Checking fp=${fp} against caps=${JSON.stringify(caps)}`);
    const now = Date.now();
    const hourAgo = now - 60 * 60 * 1000;
    const dayAgo = now - 24 * 60 * 60 * 1000;

    const hourCount = await this.countSince(fp, hourAgo);
    const dayCount = await this.countSince(fp, dayAgo);

    const underHour = hourCount < caps.hourlyCap;
    const underDay = dayCount < caps.dailyCap;

    console.info(`[RateLimiter][checkFingerprint] fp=${fp} hourCount=${hourCount} dayCount=${dayCount} -> ${underHour && underDay}`);
    return underHour && underDay;
  }

  /** Record a usage of the given fingerprint. */
  async recordUse(fp: string): Promise<void> {
    console.info(`[RateLimiter][recordUse] Recording usage for fp=${fp}`);
    const now = Date.now();
    const sql = `INSERT INTO rate_usage (fingerprint, ts) VALUES (?, ?)`;
    await this.execWithRetry(sql, [fp, now]);
    // Optional cleanup of stale rows to keep the table bounded.
    await this.cleanupOldEntries(now);
  }

  /** Count usage rows for a fingerprint since a given timestamp. */
  private async countSince(fp: string, sinceMs: number): Promise<number> {
    const sql = `SELECT COUNT(*) as cnt FROM rate_usage WHERE fingerprint = ? AND ts >= ?`;
    const row = await this.getAsync(sql, [fp, sinceMs]);
    return row?.cnt ?? 0;
  }

  /** Remove entries older than 24 hours to prevent unbounded growth. */
  private async cleanupOldEntries(currentMs: number): Promise<void> {
    const cutoff = currentMs - 24 * 60 * 60 * 1000;
    const sql = `DELETE FROM rate_usage WHERE ts < ?`;
    await this.execWithRetry(sql, [cutoff]);
    console.debug(`[RateLimiter][cleanupOldEntries] Removed entries older than ${new Date(cutoff).toISOString()}`);
  }
}