import { Command } from "commander";
import { createConnection, Socket } from "net";
import { randomUUID } from "crypto";
import { z } from "zod";
import { BrowserSession, BrowserSessionSchema, ErrorReport, ErrorReportSchema, RenderConfig, RenderConfigSchema } from "../types";

/**
 * Path to the daemon's Unix domain socket. The daemon creates this socket on
 * startup; the CLI must connect to it to request a new session.
 */
const SOCKET_PATH = "/tmp/kitty-browser-proxy.sock";

const program = new Command();

program
  .name("kitty-browser-proxy")
  .description("CLI for creating a browser session that streams to a Kitty terminal")
  .option("-u, --url <url>", "Target URL to load", "https://example.com")
  .option("-w, --width <px>", "Viewport width in pixels", "800")
  .option("-h, --height <px>", "Viewport height in pixels", "600")
  .action(async (opts) => {
    const config = {
      url: opts.url,
      viewportWidth: Number(opts.width),
      viewportHeight: Number(opts.height),
    } as RenderConfig;
    // Validate config
    RenderConfigSchema.parse(config);

    const sessionId = randomUUID();
    const session: BrowserSession = { id: sessionId, config };
    BrowserSessionSchema.parse(session);

    const client = createConnection(SOCKET_PATH, () => {
      client.write(JSON.stringify(session));
    });

    client.on("data", (data) => {
      const report = JSON.parse(data.toString());
      console.log("Daemon response:", report);
      client.end();
    });

    client.on("error", (err) => {
      console.error("Failed to communicate with daemon:", err.message);
      process.exit(1);
    });
  });

program.parseAsync(process.argv);
