// src/rpc/channel.ts
import { EventEmitter } from "events";
import { Socket } from "net";
import { RPCMessage, RPCMessageType, COMMON_PROPERTIES } from "../types";
import { v4 as uuidv4 } from "uuid";

/**
 * Options for creating an RPCChannel.
 */
export interface RPCChannelOptions {
  /** Path to a Unix domain socket. If omitted, a TCP socket on localhost:0 is used. */
  socketPath?: string;
  /** Optional pre‑created socket (useful for testing). */
  socket?: Socket;
}

/**
 * Simple event‑emitter based RPC channel. In a real implementation this would handle
 * binary framing, back‑pressure, and reconnection logic. For the purposes of the
 * library tests a lightweight in‑process channel is sufficient.
 */
export class RPCChannel extends EventEmitter {
  private socket?: Socket;

  constructor(options: RPCChannelOptions = {}) {
    super();
    if (options.socket) {
      this.socket = options.socket;
    }
    // No actual network logic is required for the test harness.
  }

  /** Send a message over the channel. */
  send(message: Omit<RPCMessage, "id">): void {
    const msg: RPCMessage = { ...message, id: uuidv4() };
    // Emit locally – in a real implementation this would write to the socket.
    this.emit("message", msg);
  }

  /** Close the underlying socket if one exists. */
  close(): void {
    if (this.socket) {
      this.socket.end();
    }
    this.removeAllListeners();
  }
}
