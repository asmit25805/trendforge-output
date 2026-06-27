import { promises as fs } from "fs";
import { createHash } from "crypto";

import {
  Alert,
  Severity,
  AlertChannelConfig,
  LoopwatchConfig,
} from "../types";

/**
 * Function signature for a channel handler.
 * Must return a promise that resolves when the alert has been sent.
 */
export type AlertHandler = (alert: Alert) => Promise<void>;

interface ThrottleEntry {
  timestamps: number[];
}

/**
 * Dispatches alerts to registered channels, applying per‑alert throttling
 * and retrying transient failures with exponential back‑off.
 *
 * All side‑effects are logged before they are performed.
 */
export class AlertDispatcher {
  private channels: Map<string, AlertHandler> = new Map();
  private throttleMap: Map<string, ThrottleEntry> = new Map();

  /**
   * Registers a new output channel.
   *
   * @param name    Identifier used in Alert.channels (e.g. "slack").
   * @param handler Async function that sends the alert.
   */
  registerChannel(name: string, handler: AlertHandler): void {
    console.info(`[INFO] Registering alert channel "${name}"`);
    this.channels.set(name, handler);
  }

  /**
   * Determines whether an alert identified by `alertKey` should be suppressed.
   *
   * @param alertKey Unique key for throttling (normally alert.alertId).
   * @param limit    Maximum number of alerts allowed in the period.
   * @param periodMs Time window in milliseconds.
   * @returns true if the alert must be throttled, false otherwise.
   */
  throttle(alertKey: string, limit: number, periodMs: number): boolean {
    const now = Date.now();
    const entry = this.throttleMap.get(alertKey) ?? { timestamps: [] };
    // Remove timestamps older than the window.
    entry.timestamps = entry.timestamps.filter((t) => now - t < periodMs);
    if (entry.timestamps.length >= limit) {
      console.warn(
        `[WARN] Throttling alert "${alertKey}" (limit ${limit} per ${periodMs}ms)`,
      );
      this.throttleMap.set(alertKey, entry);
      return true;
    }
    entry.timestamps.push(now);
    this.throttleMap.set(alertKey, entry);
    return false;
  }

  /**
   * Sends an alert to all configured channels.
   *
   * Each channel handler is invoked sequentially with retry logic.
   * The method resolves when all handlers have completed (successfully or after
   * exhausting retries). Failures are logged but do not prevent other channels
   * from being processed.
   *
   * @param alert Alert object to dispatch.
   */
  async dispatch(alert: Alert): Promise<void> {
    const start = Date.now();

    if (this.throttle(alert.alertId, 5, 60_000)) {
      console.info(`[INFO] Alert ${alert.alertId} suppressed by throttle`);
      return;
    }

    console.info(
      `[INFO] Dispatching alert ${alert.alertId} (severity=${alert.severity})`,
    );

    for (const channelName of alert.channels) {
      const handler = this.channels.get(channelName);
      if (!handler) {
        console.warn(
          `[WARN] No handler registered for channel "${channelName}" – skipping`,
        );
        continue;
      }

      await this.sendWithRetry(handler, alert, channelName);
    }

    const duration = Date.now() - start;
    console.info(
      `[INFO] Alert ${alert.alertId} dispatched in ${duration}ms`,
    );
  }

  /**
   * Executes a channel handler with up to three attempts, applying exponential
   * back‑off (100 ms, 200 ms, 400 ms). Transient errors are identified by the
   * presence of a `code` property typical of network failures; all other errors
   * are treated as fatal and abort further retries.
   *
   * @param handler     Channel handler to invoke.
   * @param alert       Alert being sent.
   * @param channelName Name of the channel (for logging).
   */
  private async sendWithRetry(
    handler: AlertHandler,
    alert: Alert,
    channelName: string,
  ): Promise<void> {
    const maxAttempts = 3;
    let attempt = 0;
    let backoff = 100; // ms

    while (attempt < maxAttempts) {
      try {
        console.info(
          `[INFO] Sending alert ${alert.alertId} to channel "${channelName}" (attempt ${attempt + 1})`,
        );
        await handler(alert);
        console.info(
          `[INFO] Alert ${alert.alertId} successfully sent to "${channelName}"`,
        );
        return;
      } catch (err) {
        attempt++;
        const isTransient = this.isTransientError(err);
        console.error(
          `[ERROR] Failed to send alert ${alert.alertId} to "${channelName}" (attempt ${attempt}): ${
            err instanceof Error ? err.message : String(err)
          }`,
        );

        if (!isTransient || attempt >= maxAttempts) {
          console.error(
            `[ERROR] Giving up on alert ${alert.alertId} for channel "${channelName}"`,
          );
          return;
        }

        console.info(
          `[INFO] Retrying alert ${alert.alertId} to "${channelName}" after ${backoff}ms`,
        );
        await this.sleep(backoff);
        backoff *= 2;
      }
    }
  }

  /**
   * Determines whether an error is transient (e.g., network timeout).
   *
   * @param err Error object thrown by a handler.
   * @returns true if the error is considered transient.
   */
  private isTransientError(err: unknown): boolean {
    if (err && typeof err === "object" && "code" in err) {
      const code = (err as any).code;
      return (
        code === "ETIMEDOUT" ||
        code === "ECONNRESET" ||
        code === "EHOSTUNREACH" ||
        code === "ENETUNREACH"
      );
    }
    return false;
  }

  /**
   * Simple promise‑based sleep.
   *
   * @param ms Milliseconds to wait.
   */
  private async sleep(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }
}

/**
 * Example Slack handler implementation.
 *
 * @param webhookUrl Slack incoming webhook URL.
 * @returns AlertHandler that posts the alert body as markdown.
 */
export function createSlackHandler(webhookUrl: string): AlertHandler {
  return async (alert: Alert) => {
    console.info(`[INFO] Posting alert ${alert.alertId} to Slack`);
    const payload = {
      text: `*${alert.title}*\n${alert.body}`,
    };
    const response = await fetch(webhookUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      const err = new Error(`Slack request failed with ${response.status}`);
      // Attach a code property to enable transient detection.
      (err as any).code = "ETIMEDOUT";
      throw err;
    }
    console.info(`[INFO] Slack response status ${response.status}`);
  };
}

/**
 * Example GitHub PR comment handler.
 *
 * @param config Configuration containing repository and auth token.
 * @returns AlertHandler that comments on the latest open PR.
 */
export function createGitHubHandler(config: AlertChannelConfig): AlertHandler {
  return async (alert: Alert) => {
    if (!config.githubRepo || !config.authToken) {
      throw new Error("GitHub handler requires githubRepo and authToken");
    }
    console.info(`[INFO] Posting alert ${alert.alertId} to GitHub`);
    const [owner, repo] = config.githubRepo.split("/");
    const apiUrl = `https://api.github.com/repos/${owner}/${repo}/issues/comments`;
    const response = await fetch(apiUrl, {
      method: "POST",
      headers: {
        Authorization: `token ${config.authToken}`,
        Accept: "application/vnd.github+json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        body: `**${alert.title}**\n${alert.body}`,
      }),
    });
    if (!response.ok) {
      const err = new Error(`GitHub request failed with ${response.status}`);
      (err as any).code = "ETIMEDOUT";
      throw err;
    }
    console.info(`[INFO] GitHub comment created for alert ${alert.alertId}`);
  };
}

/**
 * Utility to generate a deterministic alertId from ruleId and runId.
 *
 * @param ruleId Optional rule identifier.
 * @param runId  Run identifier.
 * @returns Hex string hash.
 */
export function generateAlertId(ruleId: string | undefined, runId: string): string {
  const hash = createHash("sha256");
  hash.update(`${ruleId ?? "none"}:${runId}`);
  return hash.digest("hex");
}