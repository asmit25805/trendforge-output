import { BrowserEngine } from "../src/engine/browserEngine.js";
import {
  BrowserSession,
  BrowserSessionSchema,
  ErrorReport,
  ErrorReportSchema,
  RenderConfig,
  RenderConfigSchema,
} from "../src/types.js";
import { jest } from "@jest/globals";

jest.mock("electron", () => {
  const EventEmitter = require("node:events");
  class FakeWebContents extends EventEmitter {
    loadURL(url: string) {
      if (!url.startsWith("http")) {
        this.emit("did-fail-load", new Error("Invalid URL"));
        return Promise.reject(new Error("Invalid URL"));
      }
      this.emit("did-finish-load");
      return Promise.resolve();
    }
    capturePage(rect?: any) {
      const png = Buffer.from("89504e470d0a1a0a", "hex"); // minimal PNG header
      return Promise.resolve(png);
    }
  }
  class FakeBrowserWindow extends EventEmitter {
    webContents = new FakeWebContents();
    constructor(opts: any) {
      super();
      if (opts && opts.show === false) {
        // simulate off‑screen window creation
      }
    }
    loadURL(url: string) {
      return this.webContents.loadURL(url);
    }
    capturePage(rect?: any) {
      return this.webContents.capturePage(rect);
    }
    destroy() {
      this.emit("closed");
    }
  }
  const app = new EventEmitter();
  app.whenReady = () => Promise.resolve();
  return { app, BrowserWindow: FakeBrowserWindow };
});

describe("BrowserEngine", () => {
  const partition = `test-partition-${Date.now()}`;
  let engine: BrowserEngine;

  beforeEach(() => {
    engine = new BrowserEngine();
  });

  afterEach(async () => {
    // Ensure any created windows are cleaned up
    if ((engine as any).window) {
      await (engine as any).window.destroy();
    }
  });

  test("initializes successfully with a valid partition", async () => {
    await expect(engine.init(partition)).resolves.toBeUndefined();
    // @ts-ignore – internal property used for verification only
    expect((engine as any).window).toBeDefined();
  });

  test("fails initialization when Electron cannot be required", async () => {
    jest.resetModules();
    jest.doMock("electron", () => {
      throw new Error("Electron not found");
    });
    const FaultyEngine = (await import("../src/engine/browserEngine.js")).BrowserEngine;
    const faulty = new FaultyEngine();
    await expect(faulty.init()).rejects.toMatchObject({
      code: "ELECTRON_INIT_FAIL",
    });
  });

  test("loadUrl resolves for a well‑formed HTTP URL", async () => {
    await engine.init();
    await expect(engine.loadUrl("http://example.org")).resolves.toBeUndefined();
  });

  test("loadUrl rejects for an invalid URL scheme", async () => {
    await engine.init();
    await expect(engine.loadUrl("ftp://invalid")).rejects.toMatchObject({
      code: "NAVIGATION_ERROR",
    });
  });

  test("captureFrame returns a PNG buffer after navigation", async () => {
    await engine.init();
    await engine.loadUrl("http://example.org");
    const frame = await engine.captureFrame();
    expect(Buffer.isBuffer(frame)).toBe(true);
    // Minimal PNG header check
    expect(frame.slice(0, 8).toString("hex")).toBe("89504e470d0a1a0a");
  });

  test("captureFrame propagates error when engine is not initialized", async () => {
    await expect(engine.captureFrame()).rejects.toMatchObject({
      code: "ENGINE_NOT_READY",
    });
  });
});