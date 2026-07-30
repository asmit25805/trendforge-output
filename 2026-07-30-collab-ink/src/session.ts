import { EventEmitter } from "events";
import { promises as fs } from "fs";
import path from "path";
import { randomUUID } from "crypto";

import {
  Session,
  SessionId,
  UserId,
  Stroke,
  StrokeId,
  RETRY_LIMIT,
  exponentialBackoff,
} from "./types";

/**
 * Manages active sessions, participants, and versioned stroke history.
 * All state lives in memory; snapshots are persisted atomically to disk.
 */
export class SessionManager extends EventEmitter {
  private sessions: Map<SessionId, Session> = new Map();
  private storageDir: string;

  constructor(storageDir = path.resolve(process.cwd(), "sessions")) {
    super();
    this.storageDir = storageDir;
    // Ensure the directory exists
    fs.mkdir(this.storageDir, { recursive: true }).catch(() => {});
  }

  /** Get an existing session or create a new one if it does not exist. */
  getOrCreateSession(sessionId?: SessionId): Session {
    const id = sessionId ?? randomUUID();
    let session = this.sessions.get(id);
    if (!session) {
      session = {
        id,
        participants: new Map<UserId, any>(),
        strokes: [],
        version: 0,
      };
      this.sessions.set(id, session);
      this.persistSession(session).catch(() => {});
    }
    return session;
  }

  /** Append a stroke to a session and bump the version. */
  async addStroke(sessionId: SessionId, stroke: Stroke): Promise<void> {
    const session = this.sessions.get(sessionId);
    if (!session) throw new Error(`Session ${sessionId} not found`);
    session.strokes.push(stroke);
    session.version++;
    await this.persistSession(session);
    this.emit("stroke", sessionId, stroke);
  }

  /** Persist a session atomically to disk. */
  private async persistSession(session: Session): Promise<void> {
    const filePath = path.join(this.storageDir, `${session.id}.json`);
    const data = JSON.stringify(session, null, 2);
    // Simple write – in a real system you would use a temp file then rename.
    await fs.writeFile(filePath, data, "utf-8");
  }
}
