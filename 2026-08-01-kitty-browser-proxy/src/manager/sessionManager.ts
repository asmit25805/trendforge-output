import { EventEmitter } from "node:events";
import { randomUUID } from "node:crypto";
import { BrowserEngine } from "../engine/browserEngine";
import { FrameStreamer } from "../stream/frameStreamer";
import { BrowserSession, BrowserSessionSchema, RenderConfig, RenderConfigSchema, ErrorReport, ErrorReportSchema } from "../types";
import { z } from "zod";

/**
 * Public handle returned to callers for interacting with a session.
 */
export interface SessionHandle {
  /** Unique identifier of the session. */
  id: string;
  /** Close the session and release resources. */
  close(): Promise<void>;
}

/**
 * SessionManager creates and tracks BrowserEngine instances, wiring them to a
 * FrameStreamer so that captured frames are sent to clients.
 */
export class SessionManager extends EventEmitter {
  private sessions: Map<string, { engine: BrowserEngine; streamer: FrameStreamer }> = new Map();

  constructor(private readonly defaultConfig: RenderConfig) {
    super();
  }

  /** Create a new browser session. */
  async createSession(config?: Partial<RenderConfig>): Promise<SessionHandle> {
    const finalConfig = { ...this.defaultConfig, ...config } as RenderConfig;
    // Validate config using Zod
    RenderConfigSchema.parse(finalConfig);

    const id = randomUUID();
    const session: BrowserSession = { id, config: finalConfig };
    BrowserSessionSchema.parse(session);

    const engine = new BrowserEngine(finalConfig);
    await engine.init();
    const streamer = new FrameStreamer();

    // Periodically capture frames and broadcast
    const interval = setInterval(async () => {
      try {
        const png = await engine.captureFrame();
        const packet = {
          sessionId: id,
          timestamp: Date.now(),
          pngData: png,
          width: finalConfig.viewportWidth,
          height: finalConfig.viewportHeight,
        };
        streamer.broadcast(packet);
      } catch (e) {
        this.emit("error", e);
      }
    }, 1000 / 30); // 30 FPS

    this.sessions.set(id, { engine, streamer });

    const handle: SessionHandle = {
      id,
      async close() {
        clearInterval(interval);
        await engine.shutdown();
        await streamer.close();
        this.sessions.delete(id);
      },
    };
    return handle;
  }
}
