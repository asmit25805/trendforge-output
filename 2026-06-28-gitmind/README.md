# gitmind

## Overview

**gitmind** is a git‑backed, language‑agnostic knowledge engine that lets large language models (LLMs) and human users collaboratively edit markdown documents. The system stores every change as a git commit, recomputes backlink graphs on demand, and synchronizes edits in real time using a CRDT (Yrs). All external interactions happen over a gRPC Model Context Protocol (MCP), making the engine usable from any language that supports protobuf.

### Features

- **Git as source of truth** – every document version is a git commit; history, branching, and rollback are native.
- **Real‑time collaboration** – Yrs CRDT merges concurrent edits without conflicts.
- **Backlink graph** – outgoing links are parsed from markdown, backlinks are lazily computed and cached.
- **Skill bundles** – reusable pieces of functionality can be packaged and shared.

## Installation

```bash
cargo add gitmind
```

## Quick Start

```rust
use gitmind::engine::{Engine, EngineConfig};
use gitmind::store::KnowledgeStore;
use gitmind::mcp::MCPServer;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialise the knowledge store (backed by a git repository).
    let store = KnowledgeStore::open("./my_repo")?;

    // Create the engine.
    let engine = Engine::new(EngineConfig::default(), store).await?;

    // Start the MCP server on port 50051.
    let mcp = MCPServer::new(engine.clone());
    tokio::spawn(async move { mcp.serve("0.0.0.0:50051").await });

    // Example: create a document.
    let doc = engine.create_document("notes/hello.md", "# Hello World\n").await?;
    println!("Created document with id {}", doc.id);

    Ok(())
}
```

## Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   KnowledgeStore  |<------>|      Engine       |<------>|   MCP Server      |
+-------------------+        +-------------------+        +-------------------+
        |                               |
        |                               |
        v                               v
+-------------------+        +-------------------+
|   Collaboration   |        |  Skill Registry   |
|   Session (CRDT)  |        +-------------------+
+-------------------+
```

*The diagram shows the main components and their interactions. The `KnowledgeStore` provides persistent git‑backed storage, the `Engine` orchestrates operations, the `MCP Server` exposes a gRPC API, the `Collaboration Session` handles real‑time CRDT merging, and the `Skill Registry` manages reusable skill bundles.*

## API Reference

### Engine
- `Engine::new(config: EngineConfig, store: KnowledgeStore) -> Result<Self, EngineError>`
- `Engine::create_document(path: &str, content: &str) -> Result<Document, EngineError>`
- `Engine::apply_change(doc_id: &str, change: DocumentChange) -> Result<ApplyResult, EngineError>`

### KnowledgeStore
- `KnowledgeStore::open(path: impl AsRef<Path>) -> Result<Self, StoreError>`
- `KnowledgeStore::get_document(id: &str) -> Result<Document, StoreError>`
- `KnowledgeStore::list_links(doc_id: &str) -> Result<Vec<Link>, StoreError>`

### MCP Server
- `MCPServer::new(engine: Engine) -> Self`
- `MCPServer::serve(addr: &str) -> Result<(), McpError>`

### CollaborationSession
- `CollaborationSession::new(doc_id: &str) -> Self`
- `CollaborationSession::apply_op(op: CrdtOp) -> Result<(), CollabError>`

### SkillRegistry
- `SkillRegistry::load_bundle(path: &Path) -> Result<SkillBundle, RegistryError>`
- `SkillRegistry::list_bundles() -> Vec<SkillBundle>`

## Contributing

Contributions are welcome! Please open issues or pull requests on the repository:

https://github.com/asmit25805/gitmind

## License

This project is dual‑licensed under the MIT and Apache‑2.0 licenses.
