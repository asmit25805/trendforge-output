from __future__ import annotations

import hashlib
import json
import pathlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Tuple

from pydantic import BaseModel, Field, ValidationError, validator

# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------


class SkillLoadError(RuntimeError):
    """Raised when a skill markdown file cannot be parsed or validated."""

    def __init__(self, path: pathlib.Path, line: int, message: str) -> None:
        super().__init__(f"{path} (line {line}): {message}")
        self.path = path
        self.line = line
        self.message = message


class ProvisionError(RuntimeError):
    """Raised when provisioning a box fails after all retries."""

    def __init__(self, spec_hash: str, attempts: int, last_error: Exception) -> None:
        super().__init__(
            f"Provisioning failed after {attempts} attempts (spec hash {spec_hash}): {last_error}"
        )
        self.spec_hash = spec_hash
        self.attempts = attempts
        self.last_error = last_error


class ExecutionTimeout(RuntimeError):
    """Raised when a skill script exceeds the allowed execution time."""

    def __init__(self, timeout_seconds: int) -> None:
        super().__init__(f"Execution timed out after {timeout_seconds} seconds")
        self.timeout_seconds = timeout_seconds


# ----------------------------------------------------------------------
# Core data models
# ----------------------------------------------------------------------


class SkillMeta(BaseModel):
    """
    Immutable representation of a skill parsed from a markdown file.
    """

    name: str = Field(..., description="Unique identifier extracted from front‑matter")
    description: str = Field(..., description="Human‑readable purpose of the skill")
    user_invocable: bool = Field(
        default=False, description="Whether an agent may call the skill directly"
    )
    script_path: pathlib.Path = Field(
        ..., description="Relative path to the executable entrypoint"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary additional front‑matter keys (tags, version, etc.)",
    )

    @validator("script_path", pre=True)
    def _coerce_path(cls, v: Any) -> pathlib.Path:
        if isinstance(v, pathlib.Path):
            return v
        return pathlib.Path(str(v))

    class Config:
        allow_mutation = False
        arbitrary_types_allowed = True


class BoxSpec(BaseModel):
    """
    Specification that drives the creation of an isolated development box.
    """

    image: str = Field(..., description="Base container image (e.g., python:3.12-slim)")
    env: Dict[str, str] = Field(
        default_factory=dict, description="Environment variables required by the skill"
    )
    ports: List[int] = Field(
        default_factory=list, description="Ports to expose for dev services"
    )
    volumes: List[Tuple[str, str]] = Field(
        default_factory=list,
        description="Host→container mount pairs expressed as (host_path, container_path)",
    )
    resources: Dict[str, Any] = Field(
        default_factory=dict,
        description="CPU/memory limits, e.g. {'cpu': '2', 'memory': '4Gi'}",
    )

    def deterministic_hash(self) -> str:
        """
        Returns a stable SHA‑256 hash of the spec, used for idempotent resource naming.
        """
        # Normalise the spec to a JSON string with sorted keys for deterministic output.
        spec_dict = {
            "image": self.image,
            "env": dict(sorted(self.env.items())),
            "ports": sorted(self.ports),
            "volumes": sorted(self.volumes),
            "resources": self.resources,
        }
        spec_json = json.dumps(spec_dict, separators=(",", ":"), sort_keys=True)
        return hashlib.sha256(spec_json.encode("utf-8")).hexdigest()

    class Config:
        allow_mutation = False
        arbitrary_types_allowed = True


class ProvisionedBox(BaseModel):
    """
    Handle to a running isolated box created by :class:`BoxProvisioner`.
    """

    box_id: str = Field(..., description="Deterministic identifier derived from BoxSpec hash")
    spec: BoxSpec = Field(..., description="The BoxSpec that produced this box")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of when the box was provisioned",
    )
    status: str = Field(
        default="running",
        description="Current lifecycle state (running, failed, terminated)",
    )
    host: str = Field(..., description="Hostname or IP where the box is reachable")
    ports: List[int] = Field(default_factory=list, description="Allocated host ports")
    logs_path: pathlib.Path = Field(
        ..., description="Path where streamed logs are persisted for the box"
    )

    def is_healthy(self) -> bool:
        """
        Returns ``True`` if the box reports a healthy status; otherwise ``False``.
        """
        return self.status == "running"

    def mark_failed(self, reason: str) -> None:
        """
        Transition the box to a failed state and record the failure reason.
        """
        self.status = "failed"
        failure_log = self.logs_path.with_name(f"{self.box_id}_failure.log")
        failure_log.write_text(f"[{datetime.now(timezone.utc).isoformat()}] {reason}\n")

    class Config:
        allow_mutation = True
        arbitrary_types_allowed = True


class ExecutionResult(BaseModel):
    """
    Summary of a skill execution run.
    """

    success: bool = Field(..., description="True if the script exited with code 0")
    exit_code: int = Field(..., description="Raw process exit code")
    output: str = Field(..., description="Combined stdout and stderr")
    duration_ms: int = Field(..., description="Elapsed time in milliseconds")
    artifact_path: pathlib.Path = Field(
        ..., description="Path to the generated RESULT.md markdown artifact"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When the execution result was recorded",
    )

    @property
    def duration_seconds(self) -> float:
        """Duration expressed in seconds."""
        return self.duration_ms / 1000.0

    def to_markdown(self) -> str:
        """
        Serialises the result into a markdown document suitable for persistence.
        """
        header = f"---\nsuccess: {self.success}\nexit_code: {self.exit_code}\n" \
                 f"duration_ms: {self.duration_ms}\n---\n"
        body = f"```\n{self.output.rstrip()}\n```\n"
        return header + body

    def write_artifact(self) -> None:
        """
        Writes the markdown representation to ``artifact_path``.
        """
        self.artifact_path.parent.mkdir(parents=True, exist_ok=True)
        self.artifact_path.write_text(self.to_markdown(), encoding="utf-8")

    class Config:
        allow_mutation = False
        arbitrary_types_allowed = True


# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def load_json_file(path: pathlib.Path) -> Dict[str, Any]:
    """
    Reads a JSON file and returns its content as a dictionary.
    """
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    raw = path.read_text(encoding="utf-8")
    return json.loads(raw)


def stream_file_lines(path: pathlib.Path, chunk_size: int = 4096) -> Iterator[str]:
    """
    Yields lines from a text file lazily, suitable for log streaming.
    """
    with path.open("r", encoding="utf-8") as f:
        buffer = ""
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                if buffer:
                    yield buffer
                break
            buffer += chunk
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                yield line


def exponential_backoff(attempt: int, base: float = 0.5, factor: float = 2.0) -> float:
    """
    Computes a back‑off delay in seconds for a given retry attempt.
    """
    return base * (factor ** (attempt - 1))


def timed_execution(func):
    """
    Decorator that measures execution time, captures stdout/stderr, and returns an
    :class:`ExecutionResult`. The wrapped function must return a tuple
    ``(exit_code: int, output: str)``.
    """

    def wrapper(*args, **kwargs) -> ExecutionResult:
        start = time.time()
        try:
            exit_code, output = func(*args, **kwargs)
            success = exit_code == 0
        except Exception as exc:  # pragma: no cover
            exit_code = 1
            output = str(exc)
            success = False
        duration_ms = int((time.time() - start) * 1000)
        # The caller supplies ``artifact_path`` via kwargs or positional args.
        artifact_path = kwargs.get("artifact_path")
        if artifact_path is None and len(args) > 0:
            artifact_path = getattr(args[0], "artifact_path", None)
        if artifact_path is None:
            raise ValueError("artifact_path must be provided to timed_execution")
        result = ExecutionResult(
            success=success,
            exit_code=exit_code,
            output=output,
            duration_ms=duration_ms,
            artifact_path=pathlib.Path(artifact_path),
        )
        result.write_artifact()
        return result

    return wrapper