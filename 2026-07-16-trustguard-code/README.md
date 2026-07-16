# TrustGuard

## Overview

TrustGuard is a zero‑trust, policy‑driven local code reviewer written in TypeScript. It ensures that every edit suggested by a language model is vetted against configurable policies before any file on disk is modified.

## Features

- **Zero‑trust enforcement** – No change reaches the file system without explicit policy approval.
- **Gitignore‑aware caching** – Reads respect `.gitignore` rules and reuse previously parsed files.
- **Atomic batch application** – A whole `ChangeSet` is applied only after the entire set passes policy checks.
- **Pluggable policies** – Policies are pure functions that can be added, removed, or replaced at runtime.

## Installation

```bash
npm install trustguard-code
```

## Usage

```ts
import { PolicyEngine, defaultPolicySet } from "./src/core/policyEngine";
import { FileSystemGuard } from "./src/fs/fileSystemGuard";
import { SearchEngine } from "./src/search/searchEngine";
import { AIConnector } from "./src/ai/aiConnector";
import { ChangeSet } from "./src/types";

const policyEngine = new PolicyEngine(defaultPolicySet);
const fsGuard = new FileSystemGuard(policyEngine);
const search = new SearchEngine();
const ai = new AIConnector({ endpoint: "https://api.example.com/v1" });

// Example workflow
const files = await search.search("src/**/*.ts");
const changeSet: ChangeSet = {
  files: files.map(path => ({ path, oldHash: "", newContent: "" })),
  author: "example@example.com",
};

const verdict = await policyEngine.evaluate(changeSet);
if (verdict.allowed) {
  await fsGuard.applyChangeSet(changeSet);
}
```

## API Reference

### Types (`src/types.ts`)
- `ChangeFile` – Represents a single file modification.
- `ChangeSet` – Collection of `ChangeFile` objects together with metadata.
- `Policy` – Function `(changeSet: ChangeSet) => Promise<Verdict>`.
- `Verdict` – `{ allowed: boolean; reasons?: string[] }`.
- `WriteResult`, `ApplyResult`, `FileContentResult`, `ReadOpts` – Helper result types used by the file system guard.
- `AIResponse` – Shape of the response returned by the AI connector.

### Core (`src/core/policyEngine.ts`)
- `PolicyEngine` – Evaluates a `ChangeSet` against a set of policies.
- `defaultPolicySet` – Built‑in minimal policy collection.

### File System Guard (`src/fs/fileSystemGuard.ts`)
- `FileSystemGuard` – Provides safe read/write operations that enforce policy checks.

### Search Engine (`src/search/searchEngine.ts`)
- `SearchEngine` – Simple glob‑based file search utility.

### AI Connector (`src/ai/aiConnector.ts`)
- `AIConnector` – Minimal wrapper for sending requests to an LLM endpoint.

## Architecture

```
+----------------+      +----------------+      +----------------+
|  PolicyEngine  | ---> | FileSystemGuard| ---> |   File System  |
+----------------+      +----------------+      +----------------+
        ^                         |
        |                         v
+----------------+      +----------------+
|  SearchEngine  | ---> |   AIConnector  |
+----------------+      +----------------+
```

The diagram shows the flow of data: the `SearchEngine` discovers files, the `AIConnector` can generate suggested edits, the `PolicyEngine` evaluates those edits, and the `FileSystemGuard` applies them only after approval.
