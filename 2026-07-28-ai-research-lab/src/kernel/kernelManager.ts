import { spawn, ChildProcessWithoutNullStreams } from "child_process";
import { EventEmitter } from "eventemitter3";
import { promises as fs } from "fs";
import path from "path";

import {
  Artifact,
  ArtifactKind,
  compute_sha256,
  _generate_uuid,
  _now_ms,
} from "../core/models";

/** Result of a single kernel execution step. */
export interface StepResult {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  artifacts: Artifact[];
}

/** Represents a running Python sandbox process. */
export type KernelHandle = {
  /** The underlying child process. */
  process: ChildProcessWithoutNullStreams;
  /** Unique identifier for this kernel instance. */
  id: string;
};

export class KernelManager extends EventEmitter {
  private kernels: Map<string, KernelHandle> = new Map();

  /** Execute a plan string inside a sandboxed Python process. */
  async execute(plan: string): Promise<StepResult> {
    const id = _generate_uuid();
    const scriptPath = path.join(__dirname, "../../sandbox", "run.py");
    const proc = spawn("python3", [scriptPath, "--plan", plan]);
    const handle: KernelHandle = { process: proc, id };
    this.kernels.set(id, handle);

    let stdout = "";
    let stderr = "";
    proc.stdout.on("data", (data) => (stdout += data.toString()));
    proc.stderr.on("data", (data) => (stderr += data.toString()));

    const exitCode: number | null = await new Promise((resolve) => {
      proc.on("close", resolve);
    });

    // For simplicity, we treat the entire stdout as a single artifact.
    const artifact: Artifact = {
      id: _generate_uuid(),
      kind: ArtifactKind.TEXT,
      sha256: compute_sha256(stdout),
      createdAt: _now_ms(),
      metadata: { kernelId: id },
    };

    this.kernels.delete(id);
    return { stdout, stderr, exitCode, artifacts: [artifact] };
  }
}
