import os
import json
import logging
import pathlib
import typing as _t
from dataclasses import dataclass

from src.core.models import BackendConfig, FileFingerprint
from src.core.engine import _atomic_write, _fsync_path, _retry

logger = logging.getLogger(__name__)


class BackendError(Exception):
    """Raised when a backend operation cannot be completed."""


@dataclass(frozen=True)
class LocalBackendAdapter:
    """Concrete backend that stores payloads on the local filesystem.

    The adapter respects the ``root`` option in :class:`BackendConfig.options`;
    all paths are resolved relative to that directory.  It provides atomic
    writes, durable fsyncs and a minimal ACL interface based on POSIX mode bits.
    """

    config: BackendConfig

    def __post_init__(self) -> None:
        # Resolve the root directory; default to the current working directory.
        root = self.config.options.get("root", os.getcwd())
        object.__setattr__(self, "root", pathlib.Path(root).expanduser().resolve())
        if not self.root.is_dir():
            raise BackendError(f"Root path '{self.root}' is not a directory")
        logger.debug("LocalBackendAdapter initialized with root %s", self.root)

    # ----------------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------------

    def write(self, path: str, data: bytes, atomic: bool = True) -> None:
        """Write *data* to *path* under the configured root.

        If ``atomic`` is true the write is performed via a temporary file and
        ``os.replace`` to guarantee that readers never see a partially‑written
        file.  The file and its parent directory are fsynced to ensure durability.
        """
        dest = self._resolve_path(path)
        self._ensure_parent_dir(dest)

        try:
            if atomic:
                _atomic_write(dest, data)
            else:
                with open(dest, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
                _fsync_path(dest.parent)
        except OSError as exc:
            logger.error("Failed to write %s: %s", dest, exc)
            raise BackendError(f"Unable to write '{dest}': {exc}") from exc

    def read(self, path: str) -> bytes:
        """Read the entire contents of *path* and return them as ``bytes``.

        Raises :class:`BackendError` if the file cannot be opened or read.
        """
        src = self._resolve_path(path)
        try:
            with open(src, "rb") as f:
                data = f.read()
            return data
        except OSError as exc:
            logger.error("Failed to read %s: %s", src, exc)
            raise BackendError(f"Unable to read '{src}': {exc}") from exc

    def list(self, prefix: str) -> _t.Iterable[str]:
        """Yield all stored paths that start with *prefix*.

        The returned strings are relative to the configured root and use forward
        slashes regardless of the host OS.
        """
        base = self.root
        pref_path = pathlib.Path(prefix).as_posix()
        for root, _, files in os.walk(base):
            for name in files:
                full_path = pathlib.Path(root, name)
                rel = full_path.relative_to(base).as_posix()
                if rel.startswith(pref_path):
                    yield rel

    def apply_acl(self, path: str, acl: _t.Mapping[str, _t.Any]) -> None:
        """Apply a minimal ACL to *path*.

        The *acl* mapping currently supports a ``mode`` key with an integer POSIX
        permission mask (e.g. ``0o644``).  Unsupported keys are ignored.
        """
        target = self._resolve_path(path)
        mode = acl.get("mode")
        if mode is None:
            logger.debug("No mode supplied for ACL on %s; skipping", target)
            return
        if not isinstance(mode, int):
            raise BackendError("ACL mode must be an integer")
        try:
            os.chmod(target, mode)
        except OSError as exc:
            logger.error("Failed to set ACL on %s: %s", target, exc)
            raise BackendError(f"Unable to set ACL on '{target}': {exc}") from exc

    # ----------------------------------------------------------------------
    # Helper utilities
    # ----------------------------------------------------------------------

    def _resolve_path(self, path: str) -> pathlib.Path:
        """Resolve *path* relative to the backend root, preventing escapes."""
        candidate = self.root.joinpath(path).resolve()
        if not str(candidate).startswith(str(self.root)):
            raise BackendError(f"Attempted path escape: {path}")
        return candidate

    def _ensure_parent_dir(self, dest: pathlib.Path) -> None:
        """Create the parent directory of *dest* if it does not exist."""
        parent = dest.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            _fsync_path(parent)
        except OSError as exc:
            logger.error("Failed to create directory %s: %s", parent, exc)
            raise BackendError(f"Unable to create directory '{parent}': {exc}") from exc

    # ----------------------------------------------------------------------
    # Fingerprint utilities (used by SnapshotStore)
    # ----------------------------------------------------------------------

    def fingerprint(self, path: str) -> FileFingerprint:
        """Return a :class:`FileFingerprint` for *path*.

        The method reads file metadata and computes a SHA‑256 digest.  It is
        deliberately lightweight because it is called only during snapshot
        creation and recovery.
        """
        target = self._resolve_path(path)
        if not target.is_file():
            raise BackendError(f"File not found for fingerprinting: {target}")

        stat = target.stat()
        size = stat.st_size
        mtime_ns = stat.st_mtime_ns

        # Compute SHA‑256 in a streaming fashion to avoid loading huge files.
        import hashlib

        sha256 = hashlib.sha256()
        try:
            with open(target, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    sha256.update(chunk)
        except OSError as exc:
            logger.error("Failed to read %s for fingerprint: %s", target, exc)
            raise BackendError(f"Unable to fingerprint '{target}': {exc}") from exc

        return FileFingerprint(
            path=str(target),
            size=size,
            mtime_ns=mtime_ns,
            sha256=sha256.hexdigest(),
        )

    # ----------------------------------------------------------------------
    # Retry‑aware wrappers (used by TransactionManager)
    # ----------------------------------------------------------------------

    def write_with_retry(self, path: str, data: bytes, atomic: bool = True) -> None:
        """Write *data* with transient‑error retry semantics."""
        _retry(self.write, path, data, atomic=atomic)

    def read_with_retry(self, path: str) -> bytes:
        """Read *path* with transient‑error retry semantics."""
        return _retry(self.read, path)

    def list_with_retry(self, prefix: str) -> _t.List[str]:
        """List with retry semantics; returns a concrete list."""
        return list(_retry(self.list, prefix))

    def apply_acl_with_retry(self, path: str, acl: _t.Mapping[str, _t.Any]) -> None:
        """Apply ACL with retry semantics."""
        _retry(self.apply_acl, path, acl)


__all__ = ["LocalBackendAdapter", "BackendError"]