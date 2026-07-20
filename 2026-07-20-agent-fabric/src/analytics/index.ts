// src/analytics/index.ts
import { EventEmitter } from "events";
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "fs";
import { resolve, dirname } from "path";
import { AnalyticsEvent, COMMON_PROPERTIES, TelemetryRecord } from "../types";

// Lazy‑load the PostHog client only when telemetry is actually captured.
let PostHog: typeof import("posthog-node").PostHog | undefined;

/**
 * Simple analytics singleton that records events to a local JSON file and, when
 * configured via the `POSTHOG_API_KEY` environment variable, forwards them to
 * PostHog.
 */
export class Analytics extends EventEmitter {
  private filePath: string;

  constructor(filePath: string = resolve(process.cwd(), "analytics.log")) {
    super();
    this.filePath = filePath;
    const dir = dirname(this.filePath);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }
  }

  /** Capture an analytics event. */
  captureEvent(event: AnalyticsEvent): void {
    const record: TelemetryRecord = {
      event: event.name,
      properties: { ...COMMON_PROPERTIES, ...event.properties },
      timestamp: Date.now(),
    };
    // Append to file (JSON lines)
    writeFileSync(this.filePath, JSON.stringify(record) + "\n", { flag: "a" });
    this.emit("captured", record);
    // Forward to PostHog if configured
    const apiKey = process.env.POSTHOG_API_KEY;
    if (apiKey) {
      if (!PostHog) {
        const { PostHog: PH } = require("posthog-node");
        PostHog = new PH(apiKey);
      }
      PostHog?.capture({ distinctId: "agent-fabric", event: event.name, properties: record.properties });
    }
  }
}
