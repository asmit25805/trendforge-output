# Overview
Chameleon Browser is a multi‑persona Chromium launcher written in Rust. It provides a coherent, native fingerprint for each automation session by delegating fingerprint generation to a side‑car gRPC service (PersonaEngine) and injecting the data via a small native preload script. The library is usable from Rust directly or via thin Python bindings, making it suitable for Playwright, Selenium, or any CDP‑based automation framework.

## Features
- **Independent Persona Engine** – runs as a long‑lived gRPC service, isolated from the browser binary.
- **Native fingerprint injection** – a preload script reads a temporary JSON file and overrides native getters (userAgent, hardwareConcurrency, etc.).
- **Robust error handling** – fatal errors abort the process with a clear message.

## Installation
```bash
cargo add chameleon-browser
```

## Architecture
```
+-------------------+        +-------------------+        +-------------------+
|  Persona Engine  | <----> |  gRPC Server      | <----> |  Browser Launcher |
+-------------------+        +-------------------+        +-------------------+
```
* The **Persona Engine** runs as a separate process exposing a gRPC API.
* The **gRPC Server** (part of this crate) forwards requests to the engine and stores run history in SQLite.
* The **Browser Launcher** starts Chromium with a temporary preload script that injects the fingerprint data.

## API Reference
### Engine
- `PersonaEngine` – Connects to the gRPC Persona service.
- `Persona` – Data model representing a fingerprint.
- `ValidationError` – Errors returned when a persona definition is invalid.

### Launcher
- `BrowserLauncher` – Starts a Chromium instance with the supplied `LaunchConfig`.
- `BrowserHandle` – Represents a running browser process and provides methods to terminate it.
- `LaunchConfig` – Configuration for a browser launch (executable path, args, etc.).

### Session Management
- `SessionManager` – Tracks active sessions, persists run records.
- `SessionId` – Unique identifier for a session.
- `SessionInfo` – Metadata about a session (start time, persona used, etc.).

## Usage Example
```rust
use chameleon_browser::engine::{PersonaEngine, Persona};
use chameleon_browser::launcher::{BrowserLauncher, LaunchConfig};
use chameleon_browser::session::{SessionManager, SessionOpts};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialise the engine and fetch a persona
    let engine = PersonaEngine::connect("http://127.0.0.1:50051").await?;
    let persona = engine.get_persona("default").await?;

    // Prepare launch configuration
    let config = LaunchConfig::default();
    let launcher = BrowserLauncher::new(config);
    let handle = launcher.launch(&persona)?;

    // Manage the session
    let manager = SessionManager::new()?;
    let session_id = manager.start_session(handle, persona)?;
    // ... run automation ...
    manager.end_session(session_id)?;
    Ok(())
}
```

## Contributing
Contributions are welcome! Please open issues or pull requests on the GitHub repository.

---
