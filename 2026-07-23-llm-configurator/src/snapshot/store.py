import os
import json
import shutil
import logging
import pathlib
import datetime
import typing as _t
from dataclasses import dataclass, field

from src.core.models import TransactionIntent, FileFingerprint, TargetSpec
from src.core.engine import _atomic_write, _fsync_path, _retry

logger = logging.getLogger(__name__)


class SnapshotError(Exception):
    """Raised when snapshot creation, restoration or pruning fails."""


def _compute_fingerprint(path: pathlib.Path) -> FileFingerprint:
    """Return a :class:`FileFingerprint` for *path*."""
    stat = path.stat()
    with open(path, "rb") as f:
        data = f.read()
    sha256 = (
        __import__("hashlib")
        .sha256(data)
        .hexdigest()
    )
    return FileFingerprint(
        path=str(path),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        sha256=sha256,
    )


@dataclass(frozen=True)
class Snapshot:
    """Immutable snapshot of a set of target files for a transaction."""

    tx_id: str
    snapshot_dir: pathlib.Path
    manifest_path: pathlib.Path = field(init=False)
    _entries: _t.List[dict] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "manifest_path", self.snapshot_dir / "manifest.json")

    def add_entry(
        self,
        original: pathlib.Path,
        snapshot: pathlib.Path | None,
        fingerprint: FileFingerprint | None,
    ) -> None:
        """Record a single file entry in the snapshot manifest."""
        entry = {
            "original": str(original),
            "snapshot": str(snapshot) if snapshot else None,
            "fingerprint": fingerprint.model_dump() if fingerprint else None,
        }
        self._entries.append(entry)

    def write_manifest(self) -> None:
        """Persist the snapshot manifest to disk."""
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "tx_id": self.tx_id,
            "created": datetime.datetime.utcnow().isoformat(),
            "entries": self._entries,
        }
        tmp = self.manifest_path.with_name(f".manifest.{uuid.uuid4().hex}.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.manifest_path)
        _fsync_path(self.snapshot_dir)

    @classmethod
    def load(cls, snapshot_dir: pathlib.Path) -> "Snapshot":
        """Load a snapshot from *snapshot_dir*."""
        manifest = snapshot_dir / "manifest.json"
        if not manifest.is_file():
            raise SnapshotError(f"Missing manifest in {snapshot_dir}")
        with open(manifest, "r", encoding="utf-8") as f:
            data = json.load(f)
        snap = cls(tx_id=data["tx_id"], snapshot_dir=snapshot_dir)
        object.__setattr__(snap, "_entries", data.get("entries", []))
        return snap

    @property
    def entries(self) -> _t.List[dict]:
        """Return the list of file entries stored in the manifest."""
        return list(self._entries)


class SnapshotStore:
    """Service responsible for creating, restoring and pruning snapshots."""

    def __init__(self, base_dir: str | pathlib.Path = ".") -> None:
        """
        Parameters
        ----------
        base_dir: Directory where snapshot directories will be created.
        """
        self.base_dir = pathlib.Path(base_dir).expanduser().resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _snapshot_path(self, tx_id: str) -> pathlib.Path:
        """Return the hidden directory path for a given transaction id."""
        return self.base_dir / f".snapshot-{tx_id}"

    def create(self, intent: TransactionIntent) -> Snapshot:
        """
        Capture immutable snapshots of all target files described by *intent*.

        Returns
        -------
        Snapshot
            An object representing the created snapshot.
        """
        snapshot_dir = self._snapshot_path(intent.tx_id)
        snapshot = Snapshot(tx_id=intent.tx_id, snapshot_dir=snapshot_dir)

        for target in intent.targets:
            original_path = pathlib.Path(target.path).expanduser().resolve()
            if original_path.is_file():
                fingerprint = _compute_fingerprint(original_path)
                snap_path = snapshot_dir / original_path.relative_to("/").as_posix()
                snap_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _retry(shutil.copy2, str(original_path), str(snap_path))
                except Exception as exc:
                    raise SnapshotError(
                        f"Failed to copy {original_path} to snapshot: {exc}"
                    ) from exc
                _fsync_path(snap_path.parent)
                snapshot.add_entry(original_path, snap_path, fingerprint)
            else:
                # File does not exist – record a None snapshot to indicate deletion on restore.
                snapshot.add_entry(original_path, None, None)

        snapshot.write_manifest()
        logger.debug("Created snapshot for tx %s at %s", intent.tx_id, snapshot_dir)
        return snapshot

    def restore(self, snapshot: Snapshot) -> None:
        """
        Restore all files from *snapshot* to their original locations.

        The operation is atomic per file and guarantees durability.
        """
        for entry in snapshot.entries:
            original = pathlib.Path(entry["original"])
            snap_path = pathlib.Path(entry["snapshot"]) if entry["snapshot"] else None

            if snap_path and snap_path.is_file():
                data = snap_path.read_bytes()
                try:
                    _retry(_atomic_write, original, data)
                except Exception as exc:
                    raise SnapshotError(
                        f"Failed to restore {original} from snapshot: {exc}"
                    ) from exc
                logger.debug("Restored %s from snapshot", original)
            else:
                # No snapshot file – the original file did not exist before the transaction.
                if original.is_file():
                    try:
                        original.unlink()
                        _fsync_path(original.parent)
                    except OSError as exc:
                        raise SnapshotError(
                            f"Failed to delete {original} during restore: {exc}"
                        ) from exc
                    logger.debug("Deleted %s as part of restore", original)

        # Cleanup snapshot directory after successful restore.
        try:
            shutil.rmtree(snapshot.snapshot_dir)
        except OSError as exc:
            raise SnapshotError(
                f"Failed to remove snapshot directory {snapshot.snapshot_dir}: {exc}"
            ) from exc
        logger.debug("Removed snapshot directory %s", snapshot.snapshot_dir)

    def prune(self, expired_before: datetime.datetime) -> None:
        """
        Remove snapshot directories older than *expired_before*.

        Parameters
        ----------
        expired_before: Datetime threshold; snapshots created before this are deleted.
        """
        now = datetime.datetime.utcnow()
        for entry in self.base_dir.iterdir():
            if not entry.is_dir() or not entry.name.startswith(".snapshot-"):
                continue
            manifest = entry / "manifest.json"
            if not manifest.is_file():
                # Corrupt snapshot – remove it.
                try:
                    shutil.rmtree(entry)
                    logger.info("Pruned corrupt snapshot %s", entry)
                except OSError as exc:
                    logger.warning("Unable to prune %s: %s", entry, exc)
                continue
            try:
                with open(manifest, "r", encoding="utf-8") as f:
                    data = json.load(f)
                created = datetime.datetime.fromisoformat(data["created"])
            except Exception:
                # Unreadable manifest – treat as expired.
                created = now
            if created < expired_before:
                try:
                    shutil.rmtree(entry)
                    logger.info("Pruned snapshot %s (created %s)", entry, created)
                except OSError as exc:
                    logger.warning("Failed to prune %s: %s", entry, exc)