# Rope‑Meld

## Overview
Rope‑Meld is a high‑performance, rope‑backed piece‑table engine that provides real‑time collaborative markdown editing. It combines a mutable document model with a lightweight CRDT layer, exposing a clean asynchronous façade for JavaScript/React via WebAssembly. The core guarantees **O(log n)** edit operations, deterministic replay of remote edits, and deterministic markdown rendering.

## Features
- **Piece‑table rope**: original buffer + append‑only buffer, balanced rope for fast indexing.
- **CRDT synchronization**: Lamport timestamps + version vectors, causal ordering, automatic conflict resolution.
- **Markdown rendering**: stateless traversal that respects inline attributes (bold, italics, links, etc.).
- **Wasm‑bindgen façade**: `EditorFacade` offers a thin, async‑friendly API for JavaScript/React.

## Installation
```bash
cargo add rope-meld
```

## API Reference
### Core Engine
- `RopePieceTableEngine` – the main piece‑table engine.
- `Piece` – a slice of text belonging to a buffer.
- `RopeNode` – a node in the balanced rope structure.

### Collaboration Layer
- `CRDTSyncEngine` – handles CRDT‑based synchronization.
- `DocumentOperation` – represents an insert or delete operation.
- `VersionVector` – tracks per‑user version counters.

### UI Facade (Wasm)
- `EditorFacade` – exported to JavaScript; provides methods such as `apply_edit`, `get_snapshot`, and `subscribe_changes`.
- `JsEdit` – the shape of an edit coming from the UI (insert or delete).
- `JsSnapshot` – a read‑only view of the current document state.

## Architecture
```
+-------------------+        +-------------------+
|   UI (React)      | <----> |  EditorFacade (Wasm) |
+-------------------+        +-------------------+
          |                               |
          v                               v
+-------------------+        +-------------------+
|  CRDTSyncEngine   | <----> | RopePieceTableEngine |
+-------------------+        +-------------------+
          |                               |
          v                               v
+-------------------+        +-------------------+
|  VersionVector   |        |   Rope (balanced) |
+-------------------+        +-------------------+
```
The UI sends edits to `EditorFacade`, which forwards them to `CRDTSyncEngine`. The sync engine translates edits into `DocumentOperation`s and updates the `RopePieceTableEngine`. The engine maintains a balanced rope of `Piece`s, enabling O(log n) indexing and edits. Changes are propagated back to the UI via callbacks.

## Contributing
Contributions are welcome! Please open issues or pull requests on the repository.
