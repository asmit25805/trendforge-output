# llm-configurator

## Overview

llm-configurator is a durable, pluggable transaction manager for large‑language‑model (LLM) prompt and configuration deployments. It guarantees atomicity and durability across any storage backend, from local filesystems to cloud object stores and version‑controlled repositories. By isolating each deployment in a hidden transaction directory and employing a two‑phase commit workflow, the tool can recover from crashes, roll back partial updates, and enforce consistent state without manual intervention.

## Features

- **Backend‑agnostic**: Supports local filesystem, S3, GCS, Git, and encrypted vaults through a unified `BackendAdapter` interface.
- **Atomic writes**: Uses temporary files, `fsync`, and cross‑platform atomic rename to ensure durability on POSIX and Windows.
- **Pre‑ and post‑deployment hooks**: Executes user‑defined scripts in isolated subprocesses, capturing stdout/stderr for debugging.
- **Snapshot‑based rollback**: Captures immutable snapshots of target files before modification, enabling instant restoration on failure.
- **Retry logic**: Transient errors are automatically retried up to three times with exponential backoff.
- **Structured logging**: Per‑transaction journal files record every step; the CLI emits JSON‑structured status objects for automation.
- **Recovery mode**: Scans leftover transaction directories on startup, validates fingerprints, and either resumes or cleans up automatically.

## Installation

```bash
pip install llm-configurator
```

The package requires Python 3.9 or newer. All runtime dependencies are declared in `requirements.txt`. Development dependencies for testing and linting are installed with the optional `dev` extra:

```bash
pip install -e .[dev]
```

## Quickstart

The following example demonstrates a complete deployment of a prompt file to the local filesystem backend, including a pre‑hook that validates JSON syntax and a post‑hook that prints a confirmation message.

```bash
# Create a simple prompt file
echo "You are a helpful assistant." > prompts/my_prompt.txt

# Write a pre‑hook that checks JSON (will succeed because the file is plain text)
cat > hooks/pre_validate.sh <<'EOF'
#!/usr/bin/env bash
set -e
echo "Running pre‑validation..."
# No actual validation in this demo
EOF
chmod +x hooks/pre_validate.sh

# Write a post‑hook that echoes success
cat > hooks/post_success.sh <<'EOF'
#!/usr/bin/env bash
set -e
echo "Deployment completed successfully."
EOF
chmod +x hooks/post_success.sh

# Run the deployment via the CLI
llm-configurator deploy \
  --backend local \
  --target prompts/my_prompt.txt \
  --hook-dir hooks

# Expected JSON status output (pretty‑printed)
{
  "tx_id": "e3b0c442-98fc-1c14-9a2b-3d6f9e5a7c1d",
  "status": "committed",
  "message": "All targets updated atomically",
  "timestamp": "2026-07-23T12:34:56Z"
}
```

The command creates a hidden directory `.llm-configurator-transaction-<tx_id>` in the current working directory, writes `intent.json`, takes snapshots of any existing target files, runs the pre‑hook, writes the new payload atomically, runs the post‑hook, and finally removes the transaction directory.

## Architecture

The core components interact as illustrated below:

```
┌────────────────────┐
│  TransactionManager  │
└────────────────────┘
          │           
          ▼           
┌────────────────────┐
│    BackendAdapter    │
└────────────────────┘
          │           
          ▼           
┌────────────────────┐
│      HookEngine      │
└────────────────────┘
          │           
          ▼           
┌────────────────────┐
│    SnapshotStore     │
└────────────────────┘
```

## API Reference

The public API lives under `src/core` and `src/backends`. All types are defined in `src/core/models.py`.

### Core Models (`src/core/models.py`)

```python
class TransactionIntent:
    """Encapsulates a deployment request, including target specs, backend configuration, and hooks."""
    tx_id: str
    targets: List[TargetSpec]
    backend: BackendConfig
    hooks: List[HookSpec]
    timestamp: datetime

class FileFingerprint:
    """Immutable description of a file's size, modification time, and SHA‑256 digest."""
    path: str
    size: int
    mtime_ns: int
    sha256: str

class BackendConfig:
    """Configuration for a storage backend; `type` selects the concrete adapter."""
    type: str
    options: dict
```

### TransactionManager (`src/core/engine.py`)

```python
class TransactionManager:
    """Orchestrates the two‑phase commit lifecycle for a deployment transaction."""

    def run(self, intent: TransactionIntent) -> TransactionResult:
        """Validates the intent, creates a hidden transaction directory, and drives the full pipeline."""

    def recover(self) -> List[RecoveredTransaction]:
        """Scans for leftover transaction directories, validates fingerprints, and resumes or cleans up."""

    def abort(self, tx_id: str) -> None:
        """Safely aborts an in‑progress transaction, rolling back any prepared changes."""
```

### BackendAdapter (`src/backends/local.py` and other backend modules)

```python
class BackendAdapter(ABC):
    """Abstract base for storage backends; concrete subclasses implement durability primitives."""

    @abstractmethod
    def write(self, path: str, data: bytes, atomic: bool = True) -> None:
        """Writes `data` to `path` with durability guarantees; atomic rename is used when `atomic` is True."""

    @abstractmethod
    def read(self, path: str) -> bytes:
        """Reads raw bytes from `path`; raises BackendError on failure."""

    @abstractmethod
    def list(self, prefix: str) -> Iterable[str]:
        """Enumerates objects under `prefix`."""

    @abstractmethod
    def apply_acl(self, path: str, acl: ACLSpec) -> None:
        """Enforces platform‑specific permissions on `path`."""
```

### HookEngine (`src/hooks/engine.py`)

```python
class HookEngine:
    """Loads, isolates, and executes user‑defined pre‑ and post‑deployment hooks."""

    def load_hooks(self, dir: str) -> List[Hook]:
        """Discovers hook scripts in `dir`, respecting `.disabled` markers."""

    def execute(self, hook: Hook, context: HookContext) -> HookResult:
        """Runs `hook` in a sandboxed subprocess, capturing stdout, stderr, and exit status."""

    def verify_isolation(self) -> bool:
        """Ensures the hook process cannot affect the host beyond declared side‑effects."""
```

### SnapshotStore (`src/snapshot/store.py`)

```python
class SnapshotStore:
    """Captures immutable snapshots of target files before they are overwritten."""

    def create(self, intent: TransactionIntent) -> Snapshot:
        """Copies each target file to a hidden `.snapshot-<tx_id>` directory and fsyncs metadata."""

    def restore(self, snapshot: Snapshot) -> None:
        """Restores all files from the snapshot atomically."""

    def prune(self, expired_before: datetime) -> None:
        """Removes old snapshots according to the retention policy."""
```

### Supporting Types

```python
class TargetSpec:
    """Specification of a single deployment target, including path and expected content hash."""
    path: str
    expected_sha256: str

class HookSpec:
    """Descriptor for a hook script, indicating when it runs and any environment overrides."""
    path: str
    when: Literal["pre", "post"]
    env: dict

class TransactionResult:
    """Result object emitted by `TransactionManager.run`; contains transaction ID and final status."""
    tx_id: str
    status: Literal["committed", "aborted", "failed"]
    message: str
    timestamp: datetime

class RecoveredTransaction:
    """Representation of a transaction discovered during recovery."""
    tx_id: str
    intent: TransactionIntent
    state: Literal["in_progress", "committed", "aborted"]
```

## Contributing

Contributions are welcome. Follow these steps to submit a change:

1. Fork the repository at `github.com/asmit25805/llm-configurator`.
2. Create a new branch named `feature/<description>` or `bugfix/<description>`.
3. Ensure the test suite passes locally:

```bash
pytest -q
```

4. Run the linter and formatter to keep code style consistent:

```bash
ruff check .
```

5. Commit your changes with a clear message, push the branch, and open a Pull Request against the `main` branch.

The CI workflow automatically runs the test suite and linter on each PR. Ensure your contribution does not introduce new warnings.

## Documentation

The project’s API documentation is generated from docstrings using `pydoc`. Run the following command to view it locally:

```bash
python -m pydoc llm_configurator
```

For deeper insight into transaction internals, consult the source files in `src/core`, `src/backends`, `src/hooks`, and `src/snapshot`.

## Release notes

* **v0.1.0** – Initial release with full transaction lifecycle, local backend, and hook support.
* **v0.2.0** – Added S3 and GCS adapters, improved Windows atomic rename handling.
* **v0.3.0** – Introduced snapshot pruning and configurable retry backoff.