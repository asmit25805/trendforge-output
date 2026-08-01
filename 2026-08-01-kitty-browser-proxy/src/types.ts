import { z } from "zod";

/**
 * Represents a single frame captured from an off‑screen Chromium window.
 */
export interface FramePacket {
  /** Unique identifier of the session the frame belongs to. */
  sessionId: string;
  /** Epoch milliseconds when the frame was captured. */
  timestamp: number;
  /** Raw PNG bytes containing the frame image. */
  pngData: Buffer;
  /** Pixel width of the captured frame. */
  width: number;
  /** Pixel height of the captured frame. */
  height: number;
}

export const FramePacketSchema = z.object({
  sessionId: z.string(),
  timestamp: z.number().int(),
  pngData: z.instanceof(Buffer),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
});

/**
 * Configuration used by the BrowserEngine to render a page.
 */
export interface RenderConfig {
  /** URL to load in the off‑screen browser. */
  url: string;
  /** Desired viewport width in pixels. */
  viewportWidth: number;
  /** Desired viewport height in pixels. */
  viewportHeight: number;
}

export const RenderConfigSchema = z.object({
  url: z.string().url(),
  viewportWidth: z.number().int().positive(),
  viewportHeight: z.number().int().positive(),
});

/**
 * Represents a browser session managed by the daemon.
 */
export interface BrowserSession {
  /** Unique identifier for the session. */
  id: string;
  /** Configuration used for rendering. */
  config: RenderConfig;
}

export const BrowserSessionSchema = z.object({
  id: z.string().uuid(),
  config: RenderConfigSchema,
});

/**
 * Structured error report sent over the wire.
 */
export interface ErrorReport {
  /** Short error code. */
  code: string;
  /** Human readable message. */
  message: string;
  /** Optional stack trace for debugging. */
  stack?: string;
}

export const ErrorReportSchema = z.object({
  code: z.string(),
  message: z.string(),
  stack: z.string().optional(),
});
