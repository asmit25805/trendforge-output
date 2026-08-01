import { app, BrowserWindow, session, WebContents, nativeImage } from "electron";
import { RenderConfig, RenderConfigSchema } from "../types";
import { z } from "zod";

/**
 * Structured error emitted by {@link BrowserEngine}.
 */
export class EngineError extends Error {
  /** Short identifier for the error type. */
  public readonly code: string;
  /** Indicates whether the daemon can continue after this error. */
  public readonly recoverable: boolean;

  constructor(code: string, message: string, recoverable: boolean = false) {
    super(message);
    this.name = "EngineError";
    this.code = code;
    this.recoverable = recoverable;
    // Preserve proper prototype chain (required when targeting ES5)
    Object.setPrototypeOf(this, EngineError.prototype);
  }
}

/**
 * BrowserEngine is responsible for launching an off‑screen Chromium instance,
 * loading a URL, and providing PNG buffers for each rendered frame.
 */
export class BrowserEngine {
  private window: BrowserWindow | null = null;

  constructor(private readonly config: RenderConfig) {}

  /** Initialise Electron and create the off‑screen window. */
  async init(): Promise<void> {
    await app.whenReady();
    this.window = new BrowserWindow({
      show: false,
      webPreferences: { offscreen: true },
      width: this.config.viewportWidth,
      height: this.config.viewportHeight,
    });
    this.window.webContents.loadURL(this.config.url);
  }

  /** Capture the current frame as a PNG Buffer. */
  async captureFrame(): Promise<Buffer> {
    if (!this.window) {
      throw new EngineError("NOT_INITIALIZED", "Engine has not been initialised", false);
    }
    const image = await this.window.webContents.capturePage();
    return image.toPNG();
  }

  /** Clean up resources. */
  async shutdown(): Promise<void> {
    if (this.window) {
      this.window.close();
      this.window = null;
    }
    await app.quit();
  }
}
