import os
import json
import time
import uuid
import shutil
import logging
import pathlib
import datetime
import typing as _t
from dataclasses import dataclass, asdict

from src.core.models import (
    TransactionIntent,
    BackendConfig,
    TargetSpec,
    HookSpec,
    FileFingerprint,
)

from src.backends.local import LocalBackendAdapter
from src.hooks.engine import HookEngine
from src.snapshot.store import SnapshotStore, Snapshot

# ----------------------------------------------------------------------
# Helper utilities
# ----------------------------------------------------------------------


def _is_transient_error(exc: BaseException) -> bool:
    """Return True if *exc* is considered transient and worth retrying."""
    if isinstance(exc, OSError):
        return exc.errno in {
            getattr(os, "EAGAIN", 11),
            getattr(os, "ETIMEDOUT", 110),
            getattr(os, "EWOULDBLOCK", 11),
        }
    return False


def _retry(
    func: _t.Callable[..., _t.Any],
    *args: _t.Any,
    retries: int = 3,
    backoff: float = 0.1,
    **kwargs: _t.Any,
) -> _t.Any:
    """Execute *func* with exponential back‑off retry on transient errors."""
    attempt = 0
    while True:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # pylint: disable=broad-except
            if not _is_transient_error(exc) or attempt >= retries:
                raise
            attempt += 1
            time.sleep(backoff * (2 ** (attempt - 1)))


def _fsync_path(path: pathlib.Path) -> None:
    """Force a directory or file descriptor to be flushed to disk."""
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(
    dest: pathlib.Path,
    data: bytes,
    mode: int = 0o644,
) -> None:
    """Write *data* to *dest* atomically with durability guarantees."""
    tmp = dest.with_name(f".{dest.name}.tmp.{uuid.uuid4().hex}")
    with open(tmp, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.chmod(tmp, mode)
    os.replace(tmp, dest)
    _fsync_path(dest.parent)


# ----------------------------------------------------------------------
# Result containers
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class TransactionResult:
    """Result of a transaction run."""

    tx_id: str
    status: str
    message: str
    timestamp: datetime.datetime

    def to_json(self) -> str:
        """Serialize the result as a JSON string."""
        return json.dumps(
            {
                "tx_id": self.tx_id,
                "status": self.status,
                "message": self.message,
                "timestamp": self.timestamp.isoformat(),
            },
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class RecoveredTransaction:
    """Metadata about a transaction discovered during recovery."""

    tx_id: str
    status: str
    message: str


# ----------------------------------------------------------------------
# Core engine
# ----------------------------------------------------------------------


class TransactionManager:
    """Orchestrates the two‑phase commit lifecycle for a deployment transaction."""

    _TRANSACTION_PREFIX = ".llm-configurator-transaction-"

    def __init__(self) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self, intent: TransactionIntent) -> TransactionResult:
        """Validate *intent*, create a transaction directory, and drive the pipeline."""
        tx_id = intent.tx_id or uuid.uuid4().hex
        tx_dir = pathlib.Path.cwd() / f"{self._TRANSACTION_PREFIX}{tx_id}"
        journal_path = tx_dir / "journal.log"
        tx_dir.mkdir(parents=True, exist_ok=False)
        self._configure_journal(journal_path)

        self._log(f"Created transaction directory {tx_dir}")

        # Persist intent
        intent_path = tx_dir / "intent.json"
        intent_path.write_text(intent.to_json(), encoding="utf-8")
        _fsync_path(intent_path)
        _fsync_path(tx_dir)

        self._log("Wrote intent.json and synced directory")

        # Snapshot creation
        snapshot_store = SnapshotStore(tx_dir)
        snapshot = _retry(snapshot_store.create, intent)
        self._log("Created snapshot")

        # Hook handling
        hook_engine = HookEngine()
        pre_hooks = [h for h in intent.hooks if h.when == "pre"]
        post_hooks = [h for h in intent.hooks if h.when == "post"]

        for hook_spec in pre_hooks:
            result = hook_engine.execute(hook_spec, {"tx_id": tx_id})
            self._log(f"Executed pre‑hook {hook_spec.name}: exit={result.exit_code}")
            if result.exit_code != 0:
                self._log(f"Pre‑hook {hook_spec.name} failed, aborting transaction")
                self.abort(tx_id, tx_dir, snapshot)
                return TransactionResult(
                    tx_id=tx_id,
                    status="aborted",
                    message=f"Pre‑hook {hook_spec.name} failed",
                    timestamp=datetime.datetime.utcnow(),
                )

        # Backend write phase
        backend = self._instantiate_backend(intent.backend)
        for target in intent.targets:
            data = backend.read(target.path)  # type: ignore[arg-type]
            dest_path = pathlib.Path(target.path)
            _retry(_atomic_write, dest_path, data)
            self._log(f"Wrote target {dest_path}")

        # Post‑hook execution
        for hook_spec in post_hooks:
            result = hook_engine.execute(hook_spec, {"tx_id": tx_id})
            self._log(f"Executed post‑hook {hook_spec.name}: exit={result.exit_code}")

        # Final sweep
        manifest_path = tx_dir / "committed.manifest"
        manifest_path.write_text(json.dumps({"tx_id": tx_id, "status": "committed"}), encoding="utf-8")
        _fsync_path(manifest_path)
        _fsync_path(tx_dir)

        self._log("Transaction committed, cleaning up")
        shutil.rmtree(tx_dir, ignore_errors=True)

        return TransactionResult(
            tx_id=tx_id,
            status="committed",
            message="All targets updated atomically",
            timestamp=datetime.datetime.utcnow(),
        )

    def recover(self) -> _t.List[RecoveredTransaction]:
        """Scan for leftover transaction dirs, validate, and resume or clean up."""
        cwd = pathlib.Path.cwd()
        recovered: _t.List[RecoveredTransaction] = []
        for entry in cwd.iterdir():
            if entry.is_dir() and entry.name.startswith(self._TRANSACTION_PREFIX):
                tx_id = entry.name.removeprefix(self._TRANSACTION_PREFIX)
                intent_path = entry / "intent.json"
                if not intent_path.is_file():
                    self._log(f"Missing intent.json in {entry}, removing directory")
                    shutil.rmtree(entry, ignore_errors=True)
                    continue
                try:
                    intent = TransactionIntent.from_json(intent_path.read_text(encoding="utf-8"))
                except Exception as exc:  # pylint: disable=broad-except
                    self._log(f"Failed to parse intent.json in {entry}: {exc}")
                    shutil.rmtree(entry, ignore_errors=True)
                    continue

                snapshot_store = SnapshotStore(entry)
                try:
                    snapshot = snapshot_store.create(intent)
                    self._log(f"Recovered snapshot for tx {tx_id}")
                except Exception as exc:  # pylint: disable=broad-except
                    self._log(f"Snapshot creation failed for tx {tx_id}: {exc}")
                    continue

                recovered.append(
                    RecoveredTransaction(
                        tx_id=tx_id,
                        status="recovered",
                        message="Transaction directory recovered and ready",
                    )
                )
        return recovered

    def abort(self, tx_id: str, tx_dir: pathlib.Path, snapshot: Snapshot) -> None:
        """Safely abort an in‑progress transaction, rolling back any prepared changes."""
        self._log(f"Aborting transaction {tx_id}")
        try:
            snapshot.restore()
            self._log("Restored snapshot")
        except Exception as exc:  # pylint: disable=broad-except
            self._log(f"Failed to restore snapshot during abort: {exc}")

        if tx_dir.is_dir():
            shutil.rmtree(tx_dir, ignore_errors=True)
            self._log(f"Removed transaction directory {tx_dir}")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _configure_journal(self, journal_path: pathlib.Path) -> None:
        """Configure a file handler for per‑transaction logging."""
        handler = logging.FileHandler(journal_path, encoding="utf-8")
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)
        self._logger.setLevel(logging.INFO)

    def _log(self, message: str) -> None:
        """Emit a log line to the transaction journal."""
        self._logger.info(message)

    def _instantiate_backend(self, config: BackendConfig):
        """Factory that returns a concrete BackendAdapter based on *config*."""
        if config.type == "local":
            return LocalBackendAdapter(**config.options)
        raise ValueError(f"Unsupported backend type: {config.type}")