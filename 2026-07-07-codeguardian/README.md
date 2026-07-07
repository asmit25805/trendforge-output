# codeguardian

## Overview

`codeguardian` is an extensible, plug‑in based security audit platform that combines deterministic static analysis with LLM‑augmented reasoning. It automatically clones a repository, runs multiple scanners in parallel, refines findings, deduplicates via a knowledge base, and finally produces a CVE‑ready report that is cryptographically signed.

## Features

- Async orchestration guaranteeing exactly‑once execution of each `ScanTask`.
- Pluggable agents: static analysis (Bandit, Semgrep), LLM reasoning, fuzzing, etc.
- Persistent PostgreSQL‑backed priority queue with UUID identifiers.
- KnowledgeBase cache for CVE fingerprints and exploit patterns to avoid duplicate work.
- Server‑Sent Events endpoint streaming real‑time task progress.
- Robust error handling and retry semantics.

## Installation

```bash
pip install codeguardian
```

## Quick Start

```bash
# Clone a repository and run the default scan pipeline
codeguardian scan https://github.com/asmit25805/codeguardian
```

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   Repository      | ---> |   Orchestrator    | ---> |   ReportGenerator |
+-------------------+      +-------------------+      +-------------------+
        |                           |                         |
        v                           v                         v
+-------------------+      +-------------------+      +-------------------+
|   Agents (LLM,    |      |   TaskQueue       |      |   KnowledgeBase   |
|   Bandit, etc.)   |      +-------------------+      +-------------------+
+-------------------+
```

The **Orchestrator** pulls `ScanTask` objects from the **TaskQueue**, dispatches them to the appropriate **Agent** implementations, stores intermediate results in the **KnowledgeBase**, and finally hands the aggregated data to the **ReportGenerator**.

## API Reference

### Core Models (`src/core/models.py`)
- `User` – Represents an authenticated user.
- `Project` – Metadata about the repository being scanned.
- `ScanTask` – Individual analysis job (e.g., run Bandit on a file).
- `Vulnerability` – Normalised finding produced by an agent.
- `CVEReport` – Final signed report ready for publication.
- Enums: `UserRole`, `Severity`, `TaskStatus`.

### Orchestrator (`src/core/orchestrator.py`)
- `Orchestrator` – Main entry point; manages task lifecycle.
- `TaskRunner` – Helper that executes a single `ScanTask`.

### Agents (`src/agents/llm_agent.py`)
- `LLMAgent` – Example LLM‑based reasoning agent.

### Persistence (`src/persistence/models.py`)
- SQLAlchemy ORM definitions mirroring the Pydantic core models.

### API Router (`src/api/router.py`)
- FastAPI `APIRouter` exposing endpoints for project creation, task submission, and SSE progress streaming.

### Report Generator (`src/report/generator.py`)
- `ReportGenerator` – Renders a Jinja2 template, signs the JSON payload with HMAC‑SHA256 using the secret defined in `CG_REPORT_SIGNING_SECRET`.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## Repository

Source code: https://github.com/asmit25805/codeguardian
