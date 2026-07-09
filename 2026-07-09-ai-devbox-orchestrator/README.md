# Overview
ai-devbox-orchestrator is a markdown‑driven marketplace that lets large language models (LLMs) provision isolated cloud development boxes, generate repeatable launch scripts, and visualise workflow loops without writing code.  
Skills are defined in markdown files with front‑matter, enabling human‑editable, version‑controlled knowledge that agents can query directly.

# Features
- **Markdown skill definitions** – simple `SKILL.md` files describe what a skill does and how to run it.  
- **Deterministic provisioning** – Box specifications are hashed to produce idempotent resource names.  
- **Live log streaming** – Execution logs are streamed back to the caller in real time.  
- **Result persistence** – Each run creates a `RESULT.md` artifact and appends a structured entry to `LOG.md`.  
- **Retry logic** – Provisioning failures are retried up to three times with exponential back‑off.  
- **Timeout handling** – Scripts exceeding the default 15 min timeout are captured and marked as failed.  
- **Pluggable backends** – The core abstractions can be swapped between Docker, Kubernetes, or custom providers.  
- **CLI & HTTP façade** – Works as a Claude plugin (`.claude-plugin/plugin.json`) and as a standard Python CLI.

# Installation
```bash
pip install ai-devbox-orchestrator
```
The package requires Python 3.10 or newer. All runtime dependencies are declared in `requirements.txt` and installed automatically.

# Quickstart
The following example demonstrates the full flow:

```python
import pathlib
from src.registry import SkillRegistry
from src.provisioner import BoxProvisioner
from src.executor import SkillExecutor

# 1️⃣ Load all skills from the repository root
repo_root = pathlib.Path(__file__).parent.parent
registry = SkillRegistry()
registry.load_skills(str(repo_root / "examples"))

# 2️⃣ Retrieve a skill by name
skill = registry.get_skill("example-skill")
if skill is None:
    raise SystemExit("Skill not found")

# 3️⃣ Provision an isolated box for the skill
provisioner = BoxProvisioner()
box = provisioner.provision(skill.metadata["box_spec"])

# 4️⃣ Execute the skill inside the box
executor = SkillExecutor()
result = executor.execute(skill, box, inputs={"GREETING": "Hello, world!"})

# 5️⃣ Print a concise summary
print("=== Execution Summary ===")
print(f"Success:   {result.success}")
print(f"Exit code: {result.exit_code}")
print(f"Duration:  {result.duration_ms} ms")
print("Output:")
print(result.output)
```

**Expected output (truncated for brevity):**
```
=== Execution Summary ===
Success:   True
Exit code: 0
Duration:  842 ms
Output:
Hello, world!
```

The script creates a `RESULT.md` file next to the skill definition and appends an entry to `LOG.md`. Subsequent runs will reuse the same box unless the specification changes.

# Architecture
```
┌────────────────┐
│  SkillRegistry   │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│  BoxProvisioner  │
└────────────────┘
        │         
        ▼         
┌────────────────┐
│  SkillExecutor   │
└────────────────┘
```

# API Reference

## src.core.models

### `SkillMeta`
```python
class SkillMeta:
    name: str                     # Unique identifier from front‑matter
    description: str              # Human‑readable purpose
    user_invocable: bool          # Whether an agent may call it directly
    script_path: str              # Relative path to the executable entrypoint
    metadata: dict                # Additional front‑matter keys (tags, version, etc.)
```
Represents a parsed skill definition. Instances are produced by `SkillRegistry`.

### `BoxSpec`
```python
class BoxSpec:
    image: str                    # Base container image (e.g., python:3.12-slim)
    env: dict                     # Environment variables required by the skill
    ports: list[int]              # Ports to expose for dev services
    volumes: list[tuple[str, str]]# Host→container mount pairs
    resources: dict               # CPU/memory limits
```
Describes the environment a skill needs. Stored in the skill's front‑matter under the key `box_spec`.

### `ExecutionResult`
```python
class ExecutionResult:
    success: bool                 # True if script exited 0
    exit_code: int                # Raw process exit code
    output: str                   # Combined stdout/stderr
    duration_ms: int              # Elapsed time in milliseconds
    artifact_path: str            # Path to generated RESULT.md
```
Returned by `SkillExecutor.execute` and persisted as a markdown artifact.

## src.registry

### `SkillRegistry`
```python
class SkillRegistry:
    def load_skills(self, root_path: str) -> list[SkillMeta]:
        """Walk `root_path`, parse each SKILL.md, and return validated SkillMeta objects."""
    def get_skill(self, name: str) -> SkillMeta | None:
        """Return the SkillMeta with the given name or None if it does not exist."""
    def reload(self) -> None:
        """Rescan the filesystem to pick up new or updated skills."""
```
Discovers and validates skill definitions. Raises `SkillLoadError` with line numbers on parsing failures.

## src.provisioner

### `BoxProvisioner`
```python
class BoxProvisioner:
    def provision(self, spec: BoxSpec) -> ProvisionedBox:
        """Create resources, inject scripts, and return a handle to the running box."""
    def ensure_idempotent(self, box_id: str) -> bool:
        """Check whether the requested box already exists and is healthy."""
    def destroy(self, box_id: str) -> None:
        """Tear down the box, handling any dangling resources gracefully."""
```
Handles deterministic provisioning. Wraps lower‑level Docker/Kubernetes calls and raises `ProvisionError` on unrecoverable failures.

## src.executor

### `SkillExecutor`
```python
class SkillExecutor:
    def execute(self, skill: SkillMeta, box: ProvisionedBox, inputs: dict) -> ExecutionResult:
        """Run the skill's entrypoint inside `box`, capture logs, and write RESULT.md."""
    def stream_logs(self, box: ProvisionedBox) -> iter[str]:
        """Yield live log lines for UI or agent consumption."""
    def record_timeline(self, event: str, details: dict) -> None:
        """Append a structured entry to the domain's LOG.md."""
```
Runs the skill script, respects the default 15 min timeout, and records execution metadata.

# Contributing
1. Fork the repository at https://github.com/asmit25805/ai-devbox-orchestrator.  
2. Create a feature branch (`git checkout -b feature/your‑idea`).  
3. Run the test suite locally: `pytest -q`.  
4. Ensure code passes `ruff` linting (`ruff check .`).  
5. Commit your changes with clear messages and push the branch.  
6. Open a pull request targeting the `main` branch.  

All contributions must include tests that cover new behaviour and must not break existing functionality.

# Documentation
The source code is the definitive reference. Public classes and functions are documented with docstrings and type hints. For deeper guidance, explore the `examples` directory, which contains ready‑to‑run skill markdown files.

# Support
Issues and feature requests are tracked on GitHub Issues. Please provide a minimal reproducible example when reporting bugs.