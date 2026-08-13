# cross-updater

A universal updater written in Rust and powered by Tauri that works with Electron, NW.js, and native applications.

## Overview

The updater runs as a separate binary, parses a JSON request from the host, downloads a signed package, verifies integrity, backs up the current executable, replaces it atomically, and launches the new version.

It emits typed events that can be consumed by a Tauri UI or forwarded to an Electron process via IPC.

The design isolates file‑locking and elevation concerns behind a platform‑agnostic adapter, making the core logic portable across Windows, macOS, and Linux.

## Features

- **Atomic updates** – replacement uses move‑replace semantics to avoid partially written binaries.
- **Silent operation** – no console windows appear during the update lifecycle.
- **Typed event bus** – compile‑time safety for progress, error, and log events.
- **Retryable network handling** – exponential back‑off with up to three attempts for transient failures.
- **Cryptographic verification** – SHA‑256 hash and optional PGP signature validation.
- **Cross‑platform adapters** – a single `PlatformAdapter` trait abstracts locking, elevation, and shortcut updates.
- **Backup & rollback** – previous version is stored in the system temporary directory and can be restored on fatal errors.
- **Tauri UI integration** – minimal native UI that can be embedded in any host application.

## Installation

Add the crate to your Cargo workspace:

```bash
cargo add cross-updater
```

The binary is built with the `tauri` feature enabled by default. If you only need the library, disable the default features:

```bash
cargo add cross-updater --no-default-features
```

Build the updater binary:

```bash
cargo build --release --bin cross_updater
```

The resulting executable can be shipped alongside your Electron or native application.

## Quickstart

The following example demonstrates a complete update flow using a mock manifest. Copy the code into `examples/simple_update.rs` and run it.

```rust
use cross_updater::core::engine::UpdaterEngine;
use cross_updater::core::engine::UpdateError;
use cross_updater::core::engine::UpdateRequest;
use std::path::PathBuf;

fn main() -> Result<(), UpdateError> {
    // Prepare a request JSON file path – in a real scenario the host writes this file.
    let request_path = PathBuf::from("update_request.json");

    // Load the request (the struct implements serde::Deserialize).
    let request: UpdateRequest = UpdateRequest::load(&request_path)?;

    // Create the engine and run the update.
    let engine = UpdaterEngine::new();
    engine.run(request)?;

    println!("✅ Update completed successfully");
    Ok(())
}
```

Expected console output (simplified):

```text
🔎 Checking for update…
📥 Downloading package (12.3 MiB)…
✅ Verification succeeded
📦 Extracting archive…
🔄 Replacing executable…
🚀 Launching new version
✅ Update completed successfully
```

The example assumes a `update_request.json` file with the following shape:

```json
{
  "manifest_url": "https://example.com/manifest.json",
  "current_version": "1.0.0",
  "platform": { "os": "windows", "arch": "x86_64", "binary_name": "myapp.exe" }
}
```

Adjust the URLs and platform fields to match your distribution.

## Architecture

The core components interact as illustrated below:

```text
┌─────────────────┐
│   UpdaterEngine   │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│   UpdatePackage   │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│  PlatformAdapter  │
└─────────────────┘
         │         
         ▼         
┌─────────────────┐
│     EventBus      │
└─────────────────┘
```

* **UpdaterEngine** – drives the state machine, coordinates download, verification, backup, replacement, and launch.
* **UpdatePackage** – handles streaming download, hash verification, and safe extraction.
* **PlatformAdapter** – provides OS‑specific implementations for locking, elevation, and atomic replacement.
* **EventBus** – publishes progress, error, and log events to the UI or host process.

## API Reference

### `UpdaterEngine`

```rust
pub struct UpdaterEngine { /* fields omitted for brevity */ }
```

**Methods**

* `pub fn new() -> Self` – constructs a fresh engine with default configuration.
* `pub fn run(&self, request: UpdateRequest) -> Result<(), UpdateError>` – validates the request, loads the manifest, and executes the full update lifecycle.
* `pub fn transition(&self, state: UpdateState) -> Result<(), UpdateError>` – moves the internal state machine forward, emitting an `UpdateEvent` for each transition.
* `pub fn rollback(&self) -> Result<(), UpdateError>` – restores the previous executable from the temporary backup and emits a rollback event.

### `UpdatePackage`

```rust
pub struct UpdatePackage { /* fields omitted for brevity */ }
```

**Methods**

* `pub fn download(&self, dest: &Path) -> Result<(), NetworkError>` – streams the remote archive to `dest` while invoking progress callbacks on the `EventBus`.
* `pub fn verify(&self) -> Result<(), IntegrityError>` – checks the SHA‑256 digest and, if present, validates the PGP signature.
* `pub fn extract(&self, to: &Path) -> Result<(), IoError>` – safely unpacks the archive, preserving executable permissions.

### `PlatformAdapter`

```rust
pub trait PlatformAdapter {
    fn acquire_lock(&self, app_path: &Path) -> Result<FileLock, LockError>;
    fn request_elevation(&self) -> Result<(), ElevationError>;
    fn replace_executable(&self, old: &Path, new: &Path) -> Result<(), FsError>;
}
```

Implementations exist for Windows (`src/platform/native_adapter.rs`), macOS, and Linux. Each implementation respects the platform‑specific semantics for file locking and privilege escalation.

### `EventBus`

```rust
pub struct EventBus { /* fields omitted for brevity */ }
```

**Methods**

* `pub fn emit(&self, event: UpdateEvent)` – broadcasts a typed event to all registered listeners.
* `pub fn subscribe<F>(&self, callback: F) -> SubscriptionHandle where F: Fn(UpdateEvent) + Send + 'static` – registers a listener and returns a handle that can be dropped to unsubscribe.

### `UpdateRequest`

```rust
#[derive(serde::Deserialize)]
pub struct UpdateRequest {
    pub manifest_url: String,
    pub current_version: String,
    pub platform: PlatformInfo,
}
```

The request structure mirrors the JSON file described in the Quickstart section.

## Contributing

Contributions are welcome. Follow these steps to submit a change:

1. Fork the repository on GitHub.
2. Create a new branch for your feature or bug‑fix.
3. Write tests in `tests/` that cover the new behavior.
4. Ensure `cargo clippy` passes without warnings.
5. Run `cargo test` and confirm all tests succeed.
6. Open a pull request targeting the `main` branch.

The CI pipeline validates formatting, linting, and test results on each push and pull request.

## Repository

The source code lives at https://github.com/asmit25805/cross-updater.

Browse the `src/` directory for the core engine, platform adapters, UI components, and event bus implementation.

## Documentation

Generated API documentation can be viewed locally with:

```bash
cargo doc --open
```

The docs include module‑level overviews and examples for each public type.

## Versioning

The project follows semantic versioning. Release notes are kept in the `CHANGELOG.md` file.

## Support

Open an issue on the GitHub issue tracker for bugs, feature requests, or usage questions.

Provide a minimal reproducible example and the output of `cargo version` to help diagnose problems.

## Acknowledgments

Thanks to the Rust community for crates such as `reqwest`, `serde`, and `tauri` that make cross‑platform development approachable.

The architecture draws inspiration from earlier Electron updaters while improving reliability through Rust’s safety guarantees.