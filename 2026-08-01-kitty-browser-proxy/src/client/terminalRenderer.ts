import { EventEmitter } from "node:events";
import { WebSocket } from "ws";
import { FramePacket, FramePacketSchema, TerminalEvent, TerminalEventSchema, ErrorReport, ErrorReportSchema } from "../types";
import { z } from "zod";

/**
 * TerminalRenderer runs inside a Kitty‑compatible terminal, receives frame
 * packets over a WebSocket, and renders them using the Kitty graphics protocol.
 */
export class TerminalRenderer extends EventEmitter {
  private ws: WebSocket;

  constructor(private readonly url: string) {
    super();
    this.ws = new WebSocket(this.url);
    this.ws.on("message", (data) => this.handleMessage(data.toString()));
    this.ws.on("error", (err) => this.emit("error", err));
  }

  private handleMessage(raw: string) {
    try {
      const parsed = JSON.parse(raw);
      const packet = FramePacketSchema.parse(parsed);
      this.renderFrame(packet);
    } catch (e) {
      this.emit("error", e);
    }
  }

  /** Render a single frame packet using Kitty graphics protocol. */
  private renderFrame(packet: FramePacket) {
    // For brevity, we simply write the raw PNG to stdout using the Kitty protocol.
    // In a real implementation we would split the PNG into chunks and send the
    // appropriate escape sequences.
    const base64 = packet.pngData.toString("base64");
    const esc = `\x1b_Gf=100;${packet.width}x${packet.height},${base64}\x1b\\`;
    process.stdout.write(esc);
  }

  /** Close the WebSocket connection. */
  close() {
    this.ws.close();
  }
}

/**
 * TerminalEvent describes input events coming from the terminal (e.g., key
 * presses, mouse clicks).  It is exported for completeness but not used in the
 * minimal example.
 */
export interface TerminalEvent {
  type: "key" | "mouse";
  data: any;
}

export const TerminalEventSchema = z.object({
  type: z.enum(["key", "mouse"]),
  data: z.any(),
});
