# Overview

codelink-pilot is a web‑only progressive web application that provides a full‑featured development cockpit directly in the browser. It combines a sandboxed virtual filesystem, a WebAssembly PTY, and live preview rendering so that coding agents can edit files, run commands, and instantly display results without any native dependencies or Electron.

# Features

- **Virtual filesystem** powered by BrowserFS with POSIX‑like APIs, persisted in IndexedDB.
- **Agent integration** through a uniform `AgentAdapter` that spawns WASM PTY processes for any CLI‑style coding assistant.
- **Live preview** rendering of Markdown, HTML, and image assets directly from the virtual filesystem.
- **Terminal emulator** based on xterm.js for interactive command execution.

# Installation

```bash
npm install codelink-pilot
```

# Usage

```ts
import { VirtualFS } from "codelink-pilot/src/core/virtualFS";
import { AgentAdapter } from "codelink-pilot/src/agents/adapter";
import { TerminalEmulator } from "codelink-pilot/src/ui/terminal";
import { PreviewEngine } from "codelink-pilot/src/ui/preview";
import { SyncCoordinator } from "codelink-pilot/src/core/syncCoordinator";

// Initialize the virtual filesystem
const vfs = new VirtualFS();
await vfs.mount();

// Set up the agent adapter
const adapter = new AgentAdapter(vfs);

// Create the terminal emulator
const terminal = new TerminalEmulator(adapter);

// Create the preview engine
const preview = new PreviewEngine(vfs);

// Coordinate everything
const coordinator = new SyncCoordinator(vfs, preview);
await coordinator.initialize();
```

# API Reference

## `VirtualFS`
- **Constructor**: `new VirtualFS()`
- **Methods**:
  - `mount(): Promise<void>` – Mounts the underlying BrowserFS instance.
  - `readFile(path: string): Promise<string>` – Reads a file as UTF‑8 text.
  - `writeFile(path: string, data: string): Promise<void>` – Writes text to a file.
  - `watch(callback: (event: FileChangeEvent) => void): void` – Registers a listener for file change events.

## `AgentAdapter`
- **Constructor**: `new AgentAdapter(vfs: VirtualFS, options?: SessionOptions)`
- **Methods**:
  - `startSession(): Promise<AgentSession>` – Starts a new PTY session.
  - `sendInput(sessionId: string, data: string): void` – Sends input to a running session.
  - `onOutput(callback: (sessionId: string, data: string) => void): void` – Registers a listener for PTY output.

## `TerminalEmulator`
- **Constructor**: `new TerminalEmulator(adapter: AgentAdapter, container: HTMLElement)`
- **Methods**:
  - `focus(): void` – Focuses the terminal input.

## `PreviewEngine`
- **Constructor**: `new PreviewEngine(vfs: VirtualFS)`
- **Methods**:
  - `render(path: string): Promise<PreviewResult>` – Renders a file to HTML or a React node.

## `SyncCoordinator`
- **Constructor**: `new SyncCoordinator(vfs: VirtualFS, previewEngine: PreviewEngine)`
- **Methods**:
  - `initialize(): Promise<void>` – Sets up synchronization between the filesystem and preview engine.

# Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   VirtualFS       | ---> | SyncCoordinator   | ---> | PreviewEngine     |
+-------------------+      +-------------------+      +-------------------+
        |                         ^                         |
        |                         |                         |
        v                         |                         v
+-------------------+      +-------------------+      +-------------------+
|   AgentAdapter    | ---> | TerminalEmulator  | ---> | UI (React)        |
+-------------------+      +-------------------+      +-------------------+
```

- **VirtualFS**: Provides a POSIX‑like API backed by BrowserFS and persisted in IndexedDB.
- **AgentAdapter**: Manages WASM PTY processes and forwards I/O between the terminal and the virtual filesystem.
- **TerminalEmulator**: Renders an xterm.js terminal and connects user input to the `AgentAdapter`.
- **PreviewEngine**: Converts files from the virtual filesystem into rendered HTML or React components.
- **SyncCoordinator**: Keeps the filesystem, preview, and configuration in sync, handling change events and persisting settings.
