# Kitty Browser Proxy

**Kitty‑Browser‑Proxy** brings full‑fidelity web browsing to any Kitty‑compatible terminal. It runs a daemon that renders pages off‑screen with Electron, captures frames as PNG textures, encodes them using the Kitty graphics protocol, and streams the data over WebSocket to a terminal client. Input events travel back to the daemon, allowing interactive navigation from within headless CI containers, remote SSH sessions, or Kubernetes pods.

## Features

- **Zero‑copy frame capture** – Electron off‑screen shared‑texture mode avoids CPU‑side rasterisation.
- **WebSocket transport** – Works across container boundaries, SSH tunnels, and Kubernetes services.
- **Lossless PNG encoding** – Balances quality and size; compatible with Kitty graphics.
- **Bidirectional input** – Keyboard and mouse events are sent from the terminal to the daemon.
- **Cross‑platform** – Works on Linux, macOS, and Windows (where Kitty is available).

## Installation

```bash
npm install kitty-browser-proxy
```

## Quick Start

```bash
# Start the daemon (runs in the background)
npx kitty-browser-proxy daemon &

# Open a new terminal window and launch the client
npx kitty-browser-proxy run --url https://example.com --width 1024 --height 768
```

The terminal will display the rendered page using Kitty's graphics protocol. Use your mouse and keyboard as you would in a normal browser.

## Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   Kitty Terminal | <----> |   FrameStreamer   | <----> |   BrowserEngine   |
+-------------------+        +-------------------+        +-------------------+
        ^                               ^
        |                               |
   Input Events                PNG Frame Capture
```

- **BrowserEngine** – Launches an off‑screen Chromium instance via Electron, loads the requested URL, and captures frames as PNG buffers.
- **FrameStreamer** – Listens for WebSocket connections from terminal clients, encodes PNG buffers into Kitty graphics protocol chunks, and forwards them.
- **SessionManager** – Coordinates multiple concurrent sessions, each with its own BrowserEngine and FrameStreamer.
- **TerminalRenderer** – Runs inside the terminal, receives frame packets, and renders them using Kitty escape sequences.

## API Reference

### Types

- `RenderConfig`
  ```ts
  interface RenderConfig {
    url: string;               // URL to load
    viewportWidth: number;     // Width in pixels
    viewportHeight: number;    // Height in pixels
  }
  ```
- `BrowserSession`
  ```ts
  interface BrowserSession {
    id: string;                // UUID for the session
    config: RenderConfig;      // Rendering configuration
  }
  ```
- `FramePacket`
  ```ts
  interface FramePacket {
    sessionId: string;
    timestamp: number;
    pngData: Buffer;
    width: number;
    height: number;
  }
  ```
- `ErrorReport`
  ```ts
  interface ErrorReport {
    code: string;
    message: string;
    stack?: string;
  }
  ```

### Classes

- `BrowserEngine`
  - `constructor(config: RenderConfig)`
  - `init(): Promise<void>` – Starts Electron and creates the off‑screen window.
  - `captureFrame(): Promise<Buffer>` – Returns a PNG buffer of the current frame.
  - `shutdown(): Promise<void>` – Cleans up resources.

- `FrameStreamer`
  - `constructor(port?: number)` – Starts a WebSocket server.
  - `broadcast(frame: FramePacket): void` – Sends a frame to all connected clients.
  - `close(): Promise<void>` – Shuts down the server.

- `SessionManager`
  - `constructor(defaultConfig: RenderConfig)`
  - `createSession(config?: Partial<RenderConfig>): Promise<SessionHandle>` – Creates a new session.
  - `SessionHandle` – Returned object with `id` and `close()`.

- `TerminalRenderer`
  - `constructor(url: string)` – Connects to the daemon.
  - Handles incoming `FramePacket` messages and renders them.
  - `close(): void` – Closes the WebSocket connection.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## License

MIT
