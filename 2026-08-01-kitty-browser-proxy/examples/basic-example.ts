import { randomUUID } from "node:crypto";
import { z } from "zod";
import { SessionManager } from "../src/manager/sessionManager.js";
import { TerminalRenderer } from "../src/client/terminalRenderer.js";
import {
  ErrorReport,
  ErrorReportSchema,
  BrowserSession,
  BrowserSessionSchema,
} from "../src/types.js";

/**
 * Configuration supplied via command‑line arguments.
 *   --url <url>   Target page to browse.
 *   --port <num>  Optional fixed port for the WebSocket data channel.
 */
const ConfigSchema = z.object({
  url: z.string().url(),
  port: z
    .string()
    .optional()
    .transform((val) => (val ? Number(val) : 0))
    .refine((num) => Number.isInteger(num) && num >= 0, {
      message: "Port must be a non‑negative integer",
    })
    .default(0),
});

/**
 * Simple timestamped logger for console output.
 */
function log(message: string): void {
  const now = new Date().toISOString();
  console.log(`[${now}] ${message}`);
}

/**
 * Parses process.argv into a plain object.
 */
function parseArgs(): Record<string, string> {
  const args = process.argv.slice(2);
  const result: Record<string, string> = {};
  for (let i = 0; i < args.length; i += 2) {
    const key = args[i];
    const value = args[i + 1];
    if (!key || !value) break;
    if (key.startsWith("--")) {
      result[key.slice(2)] = value;
    }
  }
  return result;
}

/**
 * Attempts to connect the TerminalRenderer to the given WebSocket URL.
 * Retries up to `maxAttempts` with exponential back‑off.
 */
async function connectWithRetry(
  renderer: TerminalRenderer,
  wsUrl: string,
  maxAttempts = 3,
): Promise<void> {
  let attempt = 0;
  while (attempt < maxAttempts) {
    try {
      await renderer.connect(wsUrl);
      log(`Connected to ${wsUrl}`);
      return;
    } catch (e) {
      attempt += 1;
      const delay = 500 * 2 ** (attempt - 1);
      log(
        `Connection attempt ${attempt} failed – retrying in ${delay}ms`,
      );
      await new Promise((res) => setTimeout(res, delay));
    }
  }
  const err: ErrorReport = {
    code: "RENDERER_CONNECT_FAIL",
    message: `Unable to connect to ${wsUrl} after ${maxAttempts} attempts`,
    recoverable: false,
  };
  renderer.emit("error", err);
  throw err;
}

/**
 * Main entry point for the example script.
 * Demonstrates creating a browsing session and rendering it in a Kitty terminal.
 */
async function main(): Promise<void> {
  const rawArgs = parseArgs();
  const config = ConfigSchema.parse(rawArgs);
  const sessionId = randomUUID();

  log(`Starting Kitty Browser Proxy example`);
  log(`Session ID: ${sessionId}`);
  log(`Target URL: ${config.url}`);

  const manager = new SessionManager();

  // Forward any daemon‑level errors to the console.
  manager.on("error", (report: ErrorReport) => {
    const { code, message, details } = report;
    console.error(`Daemon error [${code}]: ${message}`);
    if (details) console.error(details);
  });

  let sessionHandle: ReturnType<SessionManager["createSession"]>;

  try {
    // Optimistic log before awaiting the async creation.
    log(`Creating session…`);
    sessionHandle = await manager.createSession(sessionId, config.url);
    log(`Session created`);
  } catch (e) {
    const report = ErrorReportSchema.safeParse(e);
    if (report.success) {
      console.error(
        `Failed to create session [${report.data.code}]: ${report.data.message}`,
      );
    } else {
      console.error(`Unexpected error during session creation`, e);
    }
    process.exit(1);
  }

  // Determine the WebSocket port. If the user supplied a port, use it;
  // otherwise rely on the port allocated by the streamer.
  const wsPort =
    config.port > 0
      ? config.port
      : (sessionHandle as any).streamerPort ??
        (sessionHandle as any).port ??
        0;

  if (!wsPort) {
    console.error(`Unable to determine WebSocket port for streaming`);
    await manager.closeSession(sessionId);
    process.exit(1);
  }

  const wsUrl = `ws://127.0.0.1:${wsPort}`;
  const renderer = new TerminalRenderer();

  // Propagate renderer errors to the process exit path.
  renderer.on("error", (report: ErrorReport) => {
    console.error(`Renderer error [${report.code}]: ${report.message}`);
    if (!report.recoverable) {
      // Graceful shutdown on fatal errors.
      shutdown().catch(() => process.exit(1));
    }
  });

  // Handle clean termination on SIGINT / SIGTERM.
  const shutdown = async (): Promise<void> => {
    log(`Shutting down session ${sessionId}`);
    try {
      await manager.closeSession(sessionId);
      log(`Session closed`);
    } catch (e) {
      console.error(`Error while closing session`, e);
    }
    try {
      renderer.emit("close");
    } catch {
      // ignore
    }
    process.exit(0);
  };

  process.once("SIGINT", shutdown);
  process.once("SIGTERM", shutdown);

  try {
    await connectWithRetry(renderer, wsUrl);
  } catch {
    await manager.closeSession(sessionId);
    process.exit(1);
  }

  // Forward terminal input events back to the daemon.
  renderer.on("input", (event) => {
    // The daemon expects a JSON envelope with type "input".
    // SessionManager can route the event based on sessionId.
    const envelope = {
      action: "input",
      payload: {
        sessionId,
        event,
      },
    };
    // Directly write to the daemon socket – reuse the same protocol as CLI.
    const socket = manager.getControlSocket?.();
    if (socket && socket.writable) {
      socket.write(JSON.stringify(envelope) + "\n");
    }
  });

  // Keep the process alive while the renderer is active.
  log(`Rendering started – press Ctrl+C to exit`);
  // The renderer will emit "close" when the WebSocket disconnects.
  renderer.once("close", async () => {
    log(`Renderer closed the connection`);
    await shutdown();
  });
}

// Execute the script.
main().catch((e) => {
  console.error(`Unhandled exception:`, e);
  process.exit(1);
});