import { FrameStreamer } from "../src/stream/frameStreamer.js";
import { ErrorReport, ErrorReportSchema, FramePacket, FramePacketSchema } from "../src/types.js";
import { WebSocket, WebSocketServer } from "ws";

describe("FrameStreamer", () => {
  const TEST_PORT = 18080;
  let streamer: FrameStreamer;
  let wss: WebSocketServer;

  beforeEach(() => {
    streamer = new FrameStreamer();
    wss = new WebSocketServer({ port: TEST_PORT });
  });

  afterEach(async () => {
    await streamer.stop();
    wss.close();
  });

  test("starts WebSocket server and accepts a client connection", async () => {
    await streamer.start(TEST_PORT);
    const client = new WebSocket(`ws://127.0.0.1:${TEST_PORT}`);

    await new Promise<void>((resolve, reject) => {
      client.once("open", () => {
        client.close();
        resolve();
      });
      client.once("error", reject);
    });
  });

  test("broadcasts a PNG buffer to a single connected client", async () => {
    await streamer.start(TEST_PORT);
    const client = new WebSocket(`ws://127.0.0.1:${TEST_PORT}`);

    const pngBuffer = Buffer.from("89504e470d0a1a0a", "hex"); // minimal PNG header

    const received = await new Promise<Buffer>((resolve, reject) => {
      client.once("open", () => {
        client.once("message", (data) => {
          if (typeof data === "string") {
            reject(new Error("Expected binary data"));
          } else {
            resolve(data as Buffer);
          }
        });
        streamer.broadcast(pngBuffer);
      });
      client.once("error", reject);
    });

    expect(Buffer.isBuffer(received)).toBe(true);
    expect(received.length).toBeGreaterThan(0);
  });

  test("broadcasts the same frame to multiple clients", async () => {
    await streamer.start(TEST_PORT);
    const clientA = new WebSocket(`ws://127.0.0.1:${TEST_PORT}`);
    const clientB = new WebSocket(`ws://127.0.0.1:${TEST_PORT}`);

    const pngBuffer = Buffer.from("89504e470d0a1a0a", "hex");

    const waitForMessage = (client: WebSocket) =>
      new Promise<Buffer>((resolve, reject) => {
        client.once("message", (data) => {
          if (typeof data === "string") {
            reject(new Error("Expected binary data"));
          } else {
            resolve(data as Buffer);
          }
        });
        client.once("error", reject);
      });

    await Promise.all([
      new Promise<void>((res, rej) => clientA.once("open", res).once("error", rej)),
      new Promise<void>((res, rej) => clientB.once("open", res).once("error", rej)),
    ]);

    const [msgA, msgB] = await Promise.all([
      waitForMessage(clientA),
      waitForMessage(clientB),
    ]);

    streamer.broadcast(pngBuffer);

    const [resultA, resultB] = await Promise.all([
      waitForMessage(clientA),
      waitForMessage(clientB),
    ]);

    expect(resultA.equals(pngBuffer)).toBe(true);
    expect(resultB.equals(pngBuffer)).toBe(true);
  });

  test("stop shuts down the server and prevents new connections", async () => {
    await streamer.start(TEST_PORT);
    await streamer.stop();

    const client = new WebSocket(`ws://127.0.0.1:${TEST_PORT}`);

    await new Promise<void>((resolve, reject) => {
      client.once("error", () => resolve());
      client.once("open", () => reject(new Error("Connection should not succeed")));
    });
  });

  test("broadcast after stop throws an error and emits an error event", async () => {
    await streamer.start(TEST_PORT);
    await streamer.stop();

    const pngBuffer = Buffer.from("89504e470d0a1a0a", "hex");
    const errorPromise = new Promise<ErrorReport>((resolve) => {
      streamer.once("error", resolve);
    });

    await expect(() => streamer.broadcast(pngBuffer)).rejects.toThrow();

    const emitted = await errorPromise;
    const validated = ErrorReportSchema.parse(emitted);
    expect(validated.recoverable).toBe(false);
    expect(validated.code).toBeDefined();
  });

  test("broadcast with invalid frame data emits a recoverable error", async () => {
    await streamer.start(TEST_PORT);
    const invalidFrame: any = "not-a-buffer";

    const errorPromise = new Promise<ErrorReport>((resolve) => {
      streamer.once("error", resolve);
    });

    // @ts-ignore – intentionally passing wrong type to trigger validation
    streamer.broadcast(invalidFrame);

    const emitted = await errorPromise;
    const validated = ErrorReportSchema.parse(emitted);
    expect(validated.recoverable).toBe(true);
    expect(validated.code).toBe("INVALID_FRAME");
  });
});