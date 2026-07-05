# Overview

**chainforge** is a versioned catalog of reusable AI toolchains that can be published, discovered, and executed instantly from the command line.
Each toolchain (called a *chain*) is defined as a JSON document describing a deterministic sequence of steps.
Chains are stored in a serverless SQLite database (Cloudflare D1) and can be executed inside a lightweight WebAssembly sandbox, guaranteeing reproducible results and protecting secrets.

## Features

- **Versioned catalog** – immutable chain versions identified by SHA‑256 fingerprints.
- **Instant execution** – `chainforge run <slug>@<version>` fetches the exact definition and streams step results.
- **Deterministic sandbox** – each step runs in a resource‑capped WASM environment.
- **GitHub OAuth publishing**

## Installation

```bash
npm install chainforge
```

## Quick Start

```bash
# List available chains
chainforge list

# Run a chain (replace <slug> and <version> with real values)
chainforge run my-chain@v1
```

## Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   CLI (Node.js)  |  --->  |   Catalog Store   |  --->  |   SQLite (D1)     |
+-------------------+        +-------------------+        +-------------------+
        |                               |
        v                               v
+-------------------+        +-------------------+
|   Executor (WASM)|  --->  |   Sandbox (WASM)  |
+-------------------+        +-------------------+
```

- **CLI** – parses commands, talks to the catalog store, and streams execution results.
- **Catalog Store** – thin wrapper around a SQLite database that stores `ChainRecord` and `ChainVersionRecord` entries.
- **Executor** – loads a chain definition, resolves the correct version, and runs each step inside the sandbox.
- **Sandbox** – a minimal WebAssembly runtime that isolates step code, limits CPU/memory, and prevents secret leakage.
- **RateLimiter** – ensures a single fingerprint cannot be abused beyond configured limits.
- **AuthManager** – handles GitHub OAuth flow for publishing new chains.

## API Reference

### Types (`src/types.ts`)
- `ChainRecord` – metadata for a chain (slug, title, description, etc.).
- `ChainVersionRecord` – immutable version data (hash, definition, createdAt).
- `StepDefinition` – description of a single step (name, payload, timeout).
- `ExecutionResult` – overall result of a chain execution (status, stepResults).
- `StepResult` – result of an individual step (output, error, duration).
- `RateLimits` – configuration for per‑fingerprint rate limiting.
- `SessionToken` – short‑lived token used during the OAuth flow.

### CatalogStore (`src/catalog/store.ts`)
- `new CatalogStore(dbPath: string)` – creates a store backed by a SQLite file.
- `listChains(filter?: ListFilter): Promise<ChainRecord[]>`
- `getChain(slug: string): Promise<ChainRecord | null>`
- `addChain(record: ChainRecord): Promise<void>`
- `addChainVersion(version: ChainVersionRecord): Promise<void>`
- `listChainVersions(slug: string, filter?: ListFilter): Promise<ChainVersionRecord[]>`

### ChainExecutor (`src/executor/engine.ts`)
- `new ChainExecutor(store: CatalogStore, sandbox: Sandbox)` – constructs an executor.
- `execute(chainSlug: string, versionHash?: string): Promise<ExecutionResult>` – runs the chain.
- `preview(chainSlug: string, versionHash?: string): Promise<StepPreview[]>` – returns a preview of steps without executing.

### AuthManager (`src/auth/oauth.ts`)
- `startOAuth(state: string): Promise<RedirectResponse>` – initiates the GitHub OAuth flow.
- `finishOAuth(code: string, state: string): Promise<SessionToken>` – exchanges the code for a session token.

### RateLimiter (`src/rateLimiter.ts`)
- `check(token: string): Promise<boolean>` – returns `true` if the token is within limits.
- `record(token: string): Promise<void>` – records a usage event.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository:
https://github.com/asmit25805/chainforge

---
