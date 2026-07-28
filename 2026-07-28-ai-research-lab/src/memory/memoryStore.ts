import { EventEmitter } from "eventemitter3";
import {
  Artifact,
  ArtifactKind,
  compute_sha256,
  _generate_uuid,
  _now_ms,
} from "../core/models";

/** In‑memory store for immutable artifacts produced by the sandboxed kernel. */
export class MemoryStore extends EventEmitter {
  private artifacts: Map<string, Artifact> = new Map();

  /** Store a new artifact and emit an event. */
  addArtifact(data: string | Buffer, kind: ArtifactKind, metadata: Record<string, any> = {}): Artifact {
    const id = _generate_uuid();
    const sha256 = compute_sha256(data);
    const artifact: Artifact = {
      id,
      kind,
      sha256,
      createdAt: _now_ms(),
      metadata,
    };
    this.artifacts.set(id, artifact);
    this.emit("artifact", artifact);
    return artifact;
  }

  /** Retrieve an artifact by its UUID. */
  getArtifact(id: string): Artifact | undefined {
    return this.artifacts.get(id);
  }
}
