import BrowserFS from "browserfs";
import { EventEmitter } from "events";
import { SessionOptions, AgentSession, Config, FileChangeEvent } from "../types";
import { VirtualFS } from "../core/virtualFS";

/**
 * Minimal logger that appends messages to a virtual file for later debugging.
 */
class Logger {
  private readonly vfs: VirtualFS;
  private readonly logPath: string = "/codelink-pilot.log";

  constructor(vfs: VirtualFS) {
    this.vfs = vfs;
  }

  async log(message: string): Promise<void> {
    const timestamp = new Date().toISOString();
    const entry = `[${timestamp}] ${message}\n`;
    try {
      const existing = await this.vfs.readFile(this.logPath);
      await this.vfs.writeFile(this.logPath, existing + entry);
    } catch {
      // If the file does not exist, create it.
      await this.vfs.writeFile(this.logPath, entry);
    }
  }
}

/**
 * AgentAdapter manages a WebAssembly PTY process and forwards I/O between the
 * terminal emulator and the virtual filesystem.
 */
export class AgentAdapter {
  private readonly vfs: VirtualFS;
  private readonly logger: Logger;
  private readonly emitter = new EventEmitter();
  private sessionIdCounter = 0;

  constructor(vfs: VirtualFS, private readonly defaultOptions: SessionOptions = {}) {
    this.vfs = vfs;
    this.logger = new Logger(vfs);
  }

  /** Starts a new PTY session and returns its metadata. */
  async startSession(options?: SessionOptions): Promise<AgentSession> {
    const sessionId = `session-${++this.sessionIdCounter}`;
    const session: AgentSession = {
      id: sessionId,
      options: { ...this.defaultOptions, ...options }
    };
    await this.logger.log(`Started session ${sessionId}`);
    // In a real implementation we would spawn a WASM PTY here.
    // For now we simulate the session with an EventEmitter.
    this.emitter.emit("sessionStarted", session);
    return session;
  }

  /** Sends input data to a running session. */
  async sendInput(sessionId: string, data: string): Promise<void> {
    await this.logger.log(`Input to ${sessionId}: ${data}`);
    // Simulate echo output for demonstration purposes.
    this.emitter.emit("output", { sessionId, data });
  }

  /** Registers a callback for PTY output events. */
  onOutput(callback: (sessionId: string, data: string) => void): void {
    this.emitter.on("output", ({ sessionId, data }: { sessionId: string; data: string }) => {
      callback(sessionId, data);
    });
  }
}

/** Re‑export SessionOptions so that the module matches its declared exports. */
export { SessionOptions } from "../types";
