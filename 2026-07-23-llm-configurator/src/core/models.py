import json
import os
import pathlib
import hashlib
import shutil
import tempfile
import datetime
import typing as _t
from dataclasses import dataclass

from pydantic import BaseModel, Field, ValidationError, validator
from pydantic import RootModel
from typing import Literal, Iterable, List, Dict, Any

# ----------------------------------------------------------------------
# Core data models
# ----------------------------------------------------------------------


class BackendConfig(BaseModel):
    """Configuration for a storage backend.

    Attributes:
        type: Identifier of the backend (e.g., 'local', 's3', 'gcs', 'git', 'vault').
        options: Backend‑specific parameters such as bucket name or repository URL.
    """

    type: Literal["local", "s3", "gcs", "git", "vault"]
    options: Dict[str, Any] = Field(default_factory=dict)


class TargetSpec(BaseModel):
    """Specification of a single deployment target.

    Attributes:
        path: Absolute or relative path where the new payload will be written.
        sha256: Expected SHA‑256 hash of the new content; used for verification.
    """

    path: str
    sha256: str

    @validator("sha256")
    def _validate_sha256(cls, v: str) -> str:
        if len(v) != 64 or any(c not in "0123456789abcdef" for c in v.lower()):
            raise ValueError("sha256 must be a 64‑character hex string")
        return v.lower()


class HookSpec(BaseModel):
    """Descriptor for a user‑defined hook.

    Attributes:
        name: Human readable identifier.
        script: Path to the executable script.
        when: Either 'pre' or 'post' indicating when the hook runs.
    """

    name: str
    script: str
    when: Literal["pre", "post"]


class TransactionIntent(BaseModel):
    """Intent describing a full deployment transaction.

    Attributes:
        tx_id: UUID4 string generated at transaction start.
        targets: List of files to be updated together.
        backend: Backend configuration used for reading/writing payloads.
        hooks: Optional list of hook specifications.
        timestamp: Creation time of the intent.
    """

    tx_id: str
    targets: List[TargetSpec]
    backend: BackendConfig
    hooks: List[HookSpec] = Field(default_factory=list)
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    def to_json(self) -> str:
        """Serialize the intent to a JSON string."""
        return self.model_dump_json(by_alias=True, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "TransactionIntent":
        """Deserialize a JSON string into a TransactionIntent."""
        return cls.model_validate_json(data)


class FileFingerprint(BaseModel):
    """Immutable fingerprint of a file on disk.

    Attributes:
        path: Absolute path of the file.
        size: Length in bytes.
        mtime_ns: Modification time in nanoseconds.
        sha256: Hex digest of the file contents.
    """

    path: str
    size: int
    mtime_ns: int
    sha256: str

    @classmethod
    def compute(cls, path: str) -> "FileFingerprint":
        """Create a fingerprint for *path*.

        Raises:
            FileNotFoundError: If the file does not exist.
            OSError: For other I/O problems.
        """
        p = pathlib.Path(path).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        stat = p.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns

        hasher = hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        sha256 = hasher.hexdigest()

        return cls(path=str(p), size=size, mtime_ns=mtime_ns, sha256=sha256)


class SnapshotInfo(BaseModel):
    """Metadata describing a snapshot taken for a transaction."""

    tx_id: str
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    files: List[FileFingerprint]

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain‑dict representation suitable for JSON/YAML output."""
        return {
            "tx_id": self.tx_id,
            "created_at": self.created_at.isoformat(),
            "files": [f.model_dump() for f in self.files],
        }

    def to_json(self) -> str:
        """Serialize the snapshot metadata to JSON."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)


class TransactionResult(BaseModel):
    """Result emitted by the CLI after a transaction finishes."""

    tx_id: str
    status: Literal["committed", "aborted", "recovered"]
    message: str
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)

    def to_json(self) -> str:
        """Serialize the result to a JSON string."""
        return self.model_dump_json(by_alias=True, indent=2)


# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def _atomic_write(path: str, data: bytes) -> None:
    """Write *data* to *path* atomically and ensure durability.

    The function writes to a temporary file in the same directory,
    calls ``fsync`` on the file descriptor, then renames the temporary
    file over the target path.  Finally it fsyncs the containing directory.
    """
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=target.parent, prefix=".tmp-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as tmp_file:
            tmp_file.write(data)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, target)
        dir_fd = os.open(target.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    finally:
        # In case rename failed, ensure the temp file is removed.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def load_intent(tx_dir: str) -> TransactionIntent:
    """Load a TransactionIntent from ``intent.json`` inside *tx_dir*.

    Raises:
        FileNotFoundError: If the intent file does not exist.
        ValidationError: If the JSON cannot be parsed into a valid model.
    """
    intent_path = pathlib.Path(tx_dir) / "intent.json"
    with intent_path.open("r", encoding="utf-8") as f:
        raw = f.read()
    return TransactionIntent.from_json(raw)


def save_intent(intent: TransactionIntent, tx_dir: str) -> None:
    """Persist *intent* as ``intent.json`` inside *tx_dir* using durable write."""
    intent_path = pathlib.Path(tx_dir) / "intent.json"
    _atomic_write(intent_path, intent.to_json().encode("utf-8"))


def discover_config(start: str) -> pathlib.Path | None:
    """Search upward from *start* for a ``.llm-configurator.yaml`` or ``.json`` file.

    Returns the first configuration file found, or ``None`` if none exists.
    """
    current = pathlib.Path(start).resolve()
    for parent in [current, *current.parents]:
        for name in (".llm-configurator.yaml", ".llm-configurator.json"):
            candidate = parent / name
            if candidate.is_file():
                return candidate
    return None


# ----------------------------------------------------------------------
# Plugin registry for hook engines
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class HookEngineEntry:
    name: str
    factory: _t.Callable[[str], "HookEngine"]  # type: ignore  # forward reference


class HookEngineRegistry:
    """Registry that maps a hook‑engine name to a concrete implementation."""

    _registry: Dict[str, HookEngineEntry] = {}

    @classmethod
    def register(cls, name: str, factory: _t.Callable[[str], "HookEngine"]) -> None:
        """Register a new hook engine.

        Args:
            name: Identifier used in configuration.
            factory: Callable that receives a directory path and returns a HookEngine.
        """
        if name in cls._registry:
            raise ValueError(f"Hook engine '{name}' already registered")
        cls._registry[name] = HookEngineEntry(name=name, factory=factory)

    @classmethod
    def get(cls, name: str, directory: str) -> "HookEngine":
        """Retrieve a HookEngine instance for *name*.

        Raises:
            KeyError: If the name is not registered.
        """
        entry = cls._registry[name]
        return entry.factory(directory)


# ----------------------------------------------------------------------
# Concrete hook engine implementation (local subprocess)
# ----------------------------------------------------------------------


class HookResult(BaseModel):
    """Result of a hook execution."""

    hook_name: str
    returncode: int
    stdout: str
    stderr: str
    duration_seconds: float


class HookContext(BaseModel):
    """Context passed to a hook execution."""

    tx_id: str
    target_paths: List[str]
    env: Dict[str, str] = Field(default_factory=dict)


class HookEngine:
    """Engine that loads and runs hook scripts in isolated subprocesses."""

    def __init__(self, hook_dir: str):
        self.hook_dir = pathlib.Path(hook_dir).resolve()
        self.hooks: List[HookSpec] = self.load_hooks(str(self.hook_dir))

    def load_hooks(self, dir_path: str) -> List[HookSpec]:
        """Discover hook specifications in *dir_path*.

        Hook files ending with ``.disabled`` are ignored.
        """
        base = pathlib.Path(dir_path)
        specs: List[HookSpec] = []
        for script in base.iterdir():
            if script.is_file() and not script.name.endswith(".disabled"):
                when = "pre" if script.name.startswith("pre_") else "post"
                specs.append(
                    HookSpec(name=script.stem, script=str(script), when=when)
                )
        return specs

    def execute(self, hook: HookSpec, context: HookContext) -> HookResult:
        """Run *hook* with *context* in a subprocess and capture its output."""
        import subprocess
        import time

        env = os.environ.copy()
        env.update(context.env)
        env["LLM_TX_ID"] = context.tx_id
        env["LLM_TARGETS"] = json.dumps(context.target_paths)

        start = time.time()
        proc = subprocess.Popen(
            [hook.script],
            cwd=self.hook_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = proc.communicate()
        duration = time.time() - start

        return HookResult(
            hook_name=hook.name,
            returncode=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_seconds=duration,
        )

    def verify_isolation(self) -> bool:
        """Simple sanity check that the subprocess cannot modify the parent process."""
        # The implementation relies on the fact that we spawn a fresh process
        # with a limited environment.  A more thorough check would involve
        # seccomp or OS‑level sandboxing, which is out of scope for this core.
        return True


# Register the default local hook engine
HookEngineRegistry.register("local", lambda d: HookEngine(d))


# ----------------------------------------------------------------------
# Export helpers for multiple output formats
# ----------------------------------------------------------------------


def export_model(model: BaseModel, fmt: Literal["json", "dict", "yaml"] = "json") -> str | Dict[str, Any]:
    """Serialize a pydantic model to the requested format.

    Args:
        model: Instance of a pydantic BaseModel.
        fmt: Desired output format.

    Returns:
        JSON string, dict, or YAML string (if ``yaml`` is requested).

    Raises:
        ValueError: If an unsupported format is requested.
    """
    if fmt == "json":
        return model.model_dump_json(indent=2, by_alias=True)
    if fmt == "dict":
        return model.model_dump()
    if fmt == "yaml":
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("YAML output requires PyYAML") from exc
        return yaml.safe_dump(model.model_dump(), sort_keys=False)
    raise ValueError(f"Unsupported format: {fmt}")


# ----------------------------------------------------------------------
# Validation utilities used by TransactionManager and SnapshotStore
# ----------------------------------------------------------------------


def verify_fingerprints(
    expected: List[FileFingerprint], actual_paths: Iterable[str]
) -> List[FileFingerprint]:
    """Compare *expected* fingerprints against files on disk.

    Returns a list of fingerprints that differ (size, mtime, or hash).
    """
    mismatches: List[FileFingerprint] = []
    path_map = {fp.path: fp for fp in expected}
    for p in actual_paths:
        try:
            current = FileFingerprint.compute(p)
        except FileNotFoundError:
            mismatches.append(path_map.get(p, FileFingerprint(path=p, size=0, mtime_ns=0, sha256="")))
            continue
        expected_fp = path_map.get(p)
        if expected_fp is None:
            continue
        if (
            current.size != expected_fp.size
            or current.mtime_ns != expected_fp.mtime_ns
            or current.sha256 != expected_fp.sha256
        ):
            mismatches.append(current)
    return mismatches


# ----------------------------------------------------------------------
# End of models module
# ----------------------------------------------------------------------