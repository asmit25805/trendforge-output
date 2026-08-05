import { EventEmitter } from 'eventemitter3';
import { Database, verbose } from 'sqlite3';
import { Buffer } from 'buffer';
import {
  VoiceSegment,
  AgentState,
  TaskStatus,
  Decision,
} from '../types';

/**
 * Immutable snapshot of a conversation at a given point in time.
 */
export class ConversationSnapshot {
  private readonly _segments: ReadonlyArray<VoiceSegment>;

  constructor(segments: VoiceSegment[]) {
    // Deep‑clone to guarantee immutability
    this._segments = segments.map((s) => ({
      audio: Buffer.from(s.audio),
      timestamp: s.timestamp,
      speakerId: s.speakerId,
      intent: s.intent,
      vadScore: s.vadScore,
    }));
  }

  /** Returns the captured voice segments in chronological order. */
  get segments(): ReadonlyArray<VoiceSegment> {
    return this._segments;
  }
}

/**
 * Manages the persistent, bidirectional voice conversation.
 * It stores segments in memory for fast access and mirrors them to a
 * SQLite database for crash‑recovery and disk‑based replay.
 */
export class ConversationStream extends EventEmitter {
  private readonly db: Database;
  private readonly inMemory: VoiceSegment[] = [];
  private readonly maxRetries = 3;
  private readonly baseBackoffMs = 200;
  private readonly pruneIntervalMs = 60_000; // every minute
  private pruneTimer?: NodeJS.Timeout;

  /**
   * @param dbPath Path to the SQLite file. Defaults to './conversation.db'.
   */
  constructor(dbPath: string = './conversation.db') {
    super();
    const sqlite = verbose();
    this.db = new sqlite.Database(dbPath, (err) => {
      if (err) {
        this.emit('error', new Error(`Failed to open DB: ${err.message}`));
        throw err;
      }
    });
    this.initializeSchema();
    this.startPruneLoop();
  }

  /** Initialise the SQLite schema used for persisting voice segments. */
  private initializeSchema(): void {
    const sql = `
      CREATE TABLE IF NOT EXISTS segments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        speakerId TEXT,
        intent TEXT,
        vadScore REAL NOT NULL,
        audio BLOB NOT NULL
      );
    `;
    this.db.run(sql, (err) => {
      if (err) {
        this.emit('error', new Error(`Schema init failed: ${err.message}`));
        throw err;
      }
    });
  }

  /** Append a new voice segment to the stream and persist it. */
  async append(segment: VoiceSegment): Promise<void> {
    // Keep a shallow copy in memory for quick access
    this.inMemory.push({
      audio: Buffer.from(segment.audio),
      timestamp: segment.timestamp,
      speakerId: segment.speakerId,
      intent: segment.intent,
      vadScore: segment.vadScore,
    });

    const insertSql = `
      INSERT INTO segments (timestamp, speakerId, intent, vadScore, audio)
      VALUES (?, ?, ?, ?, ?);
    `;
    const params = [
      segment.timestamp,
      segment.speakerId,
      segment.intent,
      segment.vadScore,
      segment.audio,
    ];

    await this.executeWithRetry(() =>
      new Promise<void>((resolve, reject) => {
        this.db.run(insertSql, params, (err) => {
          if (err) reject(err);
          else resolve();
        });
      })
    );

    this.emit('segmentAppended', segment);
  }

  /** Return a snapshot containing all segments up to the supplied timestamp. */
  snapshot(at: number): ConversationSnapshot {
    const relevant = this.inMemory.filter((s) => s.timestamp <= at);
    // Also include persisted segments that may have been pruned from memory
    const persisted = this.loadPersistedUpTo(at);
    const combined = [...relevant, ...persisted].sort(
      (a, b) => a.timestamp - b.timestamp
    );
    return new ConversationSnapshot(combined);
  }

  /** Load persisted segments from the DB that are older than the in‑memory cutoff. */
  private loadPersistedUpTo(cutoff: number): VoiceSegment[] {
    const sql = `
      SELECT timestamp, speakerId, intent, vadScore, audio
      FROM segments
      WHERE timestamp <= ?
      ORDER BY timestamp ASC;
    `;
    const rows: VoiceSegment[] = [];
    // Synchronous read is acceptable for snapshot; wrap in try/catch.
    try {
      const stmt = this.db.prepare(sql);
      stmt.each([cutoff], (err, row) => {
        if (err) {
          this.emit('error', err);
          return;
        }
        rows.push({
          audio: Buffer.from(row.audio),
          timestamp: row.timestamp,
          speakerId: row.speakerId,
          intent: row.intent,
          vadScore: row.vadScore,
        });
      });
      stmt.finalize();
    } catch (e) {
      this.emit('error', e as Error);
    }
    return rows;
  }

  /** Remove segments older than the supplied age (ms) from memory and DB. */
  async pruneOlderThan(ms: number): Promise<void> {
    const cutoff = Date.now() - ms;
    // Prune in‑memory buffer
    while (this.inMemory.length && this.inMemory[0].timestamp < cutoff) {
      this.inMemory.shift();
    }

    const deleteSql = `DELETE FROM segments WHERE timestamp < ?;`;
    await this.executeWithRetry(() =>
      new Promise<void>((resolve, reject) => {
        this.db.run(deleteSql, [cutoff], (err) => {
          if (err) reject(err);
          else resolve();
        });
      })
    );

    this.emit('pruned', cutoff);
  }

  /** Helper that retries a promise‑returning operation with exponential back‑off. */
  private async executeWithRetry<T>(fn: () => Promise<T>): Promise<T> {
    let attempt = 0;
    while (true) {
      try {
        return await fn();
      } catch (err) {
        attempt += 1;
        if (attempt > this.maxRetries) {
          this.emit('error', new Error(`Operation failed after retries: ${(err as Error).message}`));
          throw err;
        }
        const backoff = this.baseBackoffMs * 2 ** (attempt - 1);
        await new Promise((r) => setTimeout(r, backoff));
      }
    }
  }

  /** Periodically prune very old data to bound memory usage. */
  private startPruneLoop(): void {
    this.pruneTimer = setInterval(() => {
      // Keep only the last 5 minutes of history in memory; older data stays on disk.
      this.pruneOlderThan(5 * 60_000).catch(() => {
        // Errors are already emitted via `executeWithRetry`.
      });
    }, this.pruneIntervalMs);
  }

  /** Clean up resources – close DB and stop timers. */
  async shutdown(): Promise<void> {
    if (this.pruneTimer) {
      clearInterval(this.pruneTimer);
    }
    await new Promise<void>((resolve, reject) => {
      this.db.close((err) => {
        if (err) reject(err);
        else resolve();
      });
    });
    this.emit('shutdown');
  }
}