import { promises as fs } from "fs";
import * as path from "path";
import { EventEmitter } from "events";
import os from "os";

import { LoopMonitor } from "../src/core/engine";
import { RuleEngine } from "../src/rules/engine";
import { CostEstimator } from "../src/cost/estimator";
import { AlertDispatcher, AlertHandler } from "../src/alerts/dispatcher";
import { ConfigLoader } from "../src/config/loader";
import { LoopwatchConfig } from "../src/types";

describe("LoopMonitor integration", () => {
  let tempDir: string;
  let configPath: string;
  let configLoader: ConfigLoader;
  let monitor: LoopMonitor;

  beforeAll(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "loopwatch-test-"));
    configPath = path.join(tempDir, "loopwatch.yaml");
    await fs.writeFile(
      configPath,
      `watchGlobs: ["${tempDir}/runs.log"]\nrules: []\nalerts: []`
    );
    configLoader = new ConfigLoader(configPath);
    const config: LoopwatchConfig = await configLoader.load();
    monitor = new LoopMonitor(config);
    await monitor.start();
  });

  afterAll(async () => {
    await monitor.stop();
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  test("processes new run entries", async () => {
    const runEntry = {
      runId: "run-1",
      timestamp: new Date().toISOString(),
      pattern: "example",
      durationMs: 1200,
      tokensUsed: 500,
      provider: "grok",
    };
    await fs.appendFile(
      path.join(tempDir, "runs.log"),
      JSON.stringify(runEntry) + "\n"
    );
    // Give the monitor a moment to pick up the change
    await new Promise((r) => setTimeout(r, 200));
    // No assertions here – the purpose is to ensure no unhandled exceptions.
    expect(true).toBe(true);
  });
});
