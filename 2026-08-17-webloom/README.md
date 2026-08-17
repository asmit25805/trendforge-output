Overview
========

WebLoom is an on‑demand, AI‑friendly headless browser that streams a semantic DOM tree instead of raw pixels. By delivering a compact JSON‑Lines representation of the page structure, WebLoom reduces memory usage and latency for large language model (LLM) agents that need to reason about web content. The engine supports both Chrome DevTools Protocol (CDP) and WebDriver BiDi, offering seamless compatibility with existing automation tools while exposing a unified internal command model.

Features
========

* **Lazy semantic rendering** – Only the DOM fragments requested by the client are computed, avoiding full page layout and paint.
* **LLM‑ready JSON stream** – A compact, line‑delimited JSON format that can be consumed directly by language models.
* **Dual protocol support** – Native handling of CDP and WebDriver BiDi messages through a single `ProtocolAdapter`.
* **Per‑session resource policies** – Fine‑grained memory, CPU, and scheme restrictions enforced by `SessionManager`.
* **Graceful shutdown** – Engine can terminate cleanly, waiting for active sessions to finish.
* **Robust error handling** – Fatal errors abort the process with clear logs; recoverable errors are reported to clients with structured error objects.
* **Back‑pressure aware streaming** – `SemanticStreamer` throttles output when the consumer is slow.

Installation
============

WebLoom is published on crates.io. Add it to your Cargo project with:

```bash
cargo add webloom
```

The crate requires Rust 1.70 or newer and depends on `tokio`, `hyper`, `serde`, and `parking_lot`. After adding the dependency, run `cargo build` to compile the library and its examples.

Quickstart
==========

The following example creates a browser engine, opens a session, navigates to a page, extracts a CSS selector, and streams the resulting DOM fragment to stdout.

```rust
use std::net::SocketAddr;
use webloom::{
    BrowserEngine, EngineConfig, SessionRequest, SessionId,
    Renderer, CssSelector, SemanticStreamer,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // 1. Configure and start the engine
    let config = EngineConfig {
        listen_addr: "127.0.0.1:9222".parse()?,
        default_policy: Default::default(),
        log_level: LogLevel::Info,
    };
    let engine = BrowserEngine::run(config).await?;

    // 2. Create a new session
    let session_req = SessionRequest {
        id: SessionId::new(),
        policy: Default::default(),
    };
    let handle = engine.spawn_session(session_req).await?;

    // 3. Render a page
    let renderer = handle.renderer();
    let snapshot = renderer.render("https://example.org".parse()?).await?;
    println!("Fetched {}", snapshot.url);

    // 4. Extract a fragment
    let selector = CssSelector::new("h1")?;
    let fragment = renderer.extract(selector).await?;
    println!("Found {} nodes", fragment.nodes.len());

    // 5. Stream the fragment as JSON lines
    let mut streamer = SemanticStreamer::new();
    streamer.register_callback(Box::new(|frag| {
        println!("{}", serde_json::to_string(&frag).unwrap());
    }));
    streamer.push(fragment).await?;
    streamer.close().await?;

    // 6. Shut down the engine
    engine.shutdown().await?;
    Ok(())
}
```

Expected output (truncated for brevity):

```
Fetched https://example.org/
Found 1 nodes
{"node_id":42,"node_type":"Element","tag_name":"h1","attributes":{},"children":[],"text_content":"Welcome"}
```

Architecture
============

The core components are arranged in a linear flow, as illustrated below.

```
┌──────────────────┐
│   BrowserEngine    │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│   SessionManager   │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│      Renderer      │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│  ProtocolAdapter   │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│  SemanticStreamer  │
└──────────────────┘
```

API Reference
=============

All public types live in the `webloom` crate root. The signatures below use Rust syntax and are fully documented in the source.

BrowserEngine
-------------

```rust
pub struct BrowserEngine;
```

* `run(config: EngineConfig) -> Result<BrowserEngine, EngineError>`
  * Boots the engine with the supplied configuration and blocks until termination. Returns an instance that can be used to manage sessions.

* `shutdown(&self) -> Result<(), EngineError>`
  * Initiates an orderly shutdown, waiting for all active sessions to finish before returning.

* `spawn_session(&self, req: SessionRequest) -> Result<SessionHandle, EngineError>`
  * Creates a new isolated browsing session based on the request. The returned handle gives access to the session’s `Renderer`.

SessionManager
--------------

```rust
pub struct SessionManager;
```

* `create(id: SessionId, policy: ResourcePolicy) -> Result<SessionHandle, SessionError>`
  * Allocates a new session with its own owner‑local store and applies the provided resource policy.

* `close(&self, id: SessionId) -> Result<(), SessionError>`
  * Tears down the session identified by `id` and releases all associated resources.

* `apply_policy(&self, id: SessionId, policy: ResourcePolicy) -> Result<(), SessionError>`
  * Updates the resource limits for an existing session on the fly.

Renderer
--------

```rust
pub struct Renderer;
```

* `render(&self, url: Url) -> Result<PageSnapshot, RenderError>`
  * Fetches the page at `url`, parses resources, and builds a minimal layout sufficient for on‑demand DOM extraction.

* `extract(&self, selector: CssSelector) -> Result<DomFragment, RenderError>`
  * Evaluates the CSS selector against the current layout tree without performing a full paint. Returns a `DomFragment` containing matching nodes.

* `stream_dom(&self, handle: StreamHandle) -> Result<(), StreamError>`
  * Pushes incremental DOM events to the consumer identified by `handle`. The stream respects back‑pressure signals from `SemanticStreamer`.

ProtocolAdapter
----------------

```rust
pub struct ProtocolAdapter;
```

* `handle_cdp(&self, msg: CdpMessage) -> Result<CdpResponse, ProtocolError>`
  * Routes a CDP command to the appropriate engine component and returns the corresponding response.

* `handle_wd(&self, msg: WebDriverMessage) -> Result<WebDriverResponse, ProtocolError>`
  * Handles a WebDriver Classic or BiDi message, providing compatibility with existing automation tools.

* `emit_event(&self, event: EngineEvent) -> Result<(), ProtocolError>`
  * Forwards internal engine events (e.g., session created, resource fetched) to all connected clients.

SemanticStreamer
----------------

```rust
pub struct SemanticStreamer;
```

* `push(&mut self, fragment: DomFragment) -> Result<(), StreamError>`
  * Enqueues a DOM fragment for transmission. If the consumer is slow, the method applies throttling based on internal back‑pressure metrics.

* `close(&mut self) -> Result<(), StreamError>`
  * Finalizes the stream, flushes remaining buffers, and releases resources.

* `register_callback(&mut self, cb: Box<dyn Fn(&DomFragment) + Send + Sync>)`
  * Registers a user‑provided hook that is invoked for each fragment before it is sent. Useful for logging or custom transformation.

Data Models
-----------

* `EngineConfig` – Configuration for the engine (listen address, default policy, log level).
* `SessionRequest` – Parameters required to create a new session (`SessionId`, `ResourcePolicy`).
* `SessionHandle` – Opaque handle exposing a `Renderer` tied to a specific session.
* `PageSnapshot` – Captures the URL, root `DomNode`, fetched resources, and timestamp of a rendered page.
* `DomNode` – Represents a node in the lazy semantic tree (id, type, tag name, attributes, children, optional text).
* `DomFragment` – Collection of `DomNode` objects that match a selector.
* `ResourcePolicy` – Limits for memory, CPU, allowed schemes, and third‑party request blocking.
* `CssSelector` – Wrapper around a validated CSS selector string.
* `StreamHandle` – Identifier for a consumer of incremental DOM events.
* `EngineError`, `SessionError`, `RenderError`, `ProtocolError`, `StreamError` – Structured error types containing a human‑readable `message` and a machine‑readable `code` enum.

Contributing
============

Contributions are welcome. Follow these steps to submit a change:

1. **Fork** the repository at `github.com/asmit25805/webloom`.
2. **Create** a new branch for your feature or bug fix.
3. **Write** tests in `tests/` that cover the new behavior. Each test file must contain at least six test functions with descriptive names and real assertions.
4. **Run** the full test suite locally with `cargo test`. The CI workflow will also run `cargo clippy` and `cargo test` on every push.
5. **Commit** your changes with clear messages.
6. **Open** a pull request targeting the `main` branch. The CI pipeline will verify formatting, linting, and test success before the PR can be merged.

Please ensure that new code adheres to the project's coding standards:

* Use `parking_lot` primitives for synchronization.
* Keep public APIs documented with a single‑line doc comment.
* Avoid empty function bodies; every method must contain real logic.
* Do not introduce dependencies outside the listed crate files.

For detailed contribution guidelines, see the `CONTRIBUTING.md` file in the repository.