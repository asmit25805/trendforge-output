import os
import json
import uuid
import logging
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from typing import Dict, Any, Callable, List, Optional, Mapping

# Configure a module‑level logger that writes to the project's error log.
_LOG_PATH = os.path.join(".scribe", "error.log")
os.makedirs(os.path.dirname(_LOG_PATH), exist_ok=True)
_logger = logging.getLogger(__name__)
_handler = logging.FileHandler(_LOG_PATH, mode="a", encoding="utf-8")
_formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
_handler.setFormatter(_formatter)
_logger.addHandler(_handler)
_logger.setLevel(logging.ERROR)


class ModelError(RuntimeError):
    """Raised when a model fails to load, validate or persist."""


def _open_secure(path: str, flags: int, mode: int = 0o600) -> int:
    """
    Open a file using O_NOFOLLOW and explicit permission checks.
    Retries up to three times with exponential backoff on transient errors.
    """
    for attempt in range(3):
        try:
            fd = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0), mode)
            return fd
        except OSError as exc:
            # Transient errors are typically EAGAIN or EINTR.
            if exc.errno in (os.errno.EAGAIN, os.errno.EINTR):
                backoff = 0.1 * (2 ** attempt)
                time.sleep(backoff)
                continue
            _logger.error("Secure open failed for %s: %s", path, exc)
            raise ModelError(f"Unable to open {path!r}") from exc
    raise ModelError(f"Exceeded retries opening {path!r}")


def _write_secure(path: str, data: bytes) -> None:
    """
    Write bytes to a file atomically using a temporary file and rename.
    The target directory must already exist and be confined.
    """
    dir_name = os.path.dirname(path) or "."
    tmp_path = f"{path}.tmp.{uuid.uuid4().hex}"
    fd = _open_secure(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.replace(tmp_path, path)
    except OSError as exc:
        _logger.error("Atomic replace failed for %s -> %s: %s", tmp_path, path, exc)
        raise ModelError(f"Failed to persist {path!r}") from exc


def _read_secure(path: str) -> bytes:
    """
    Read the entire contents of a file securely.
    """
    fd = _open_secure(path, os.O_RDONLY)
    try:
        chunks = []
        while True:
            chunk = os.read(fd, 8192)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


# --------------------------------------------------------------------------- #
# Plugin registry ------------------------------------------------------------ #
# --------------------------------------------------------------------------- #

Hook = Callable[..., Any]
_registry: Dict[str, List[Hook]] = {}


def register_hook(name: str, func: Hook) -> None:
    """
    Register a callable under a hook name. The callable will be invoked
    by ``run_hook`` with the same arguments.
    """
    if name not in _registry:
        _registry[name] = []
    _registry[name].append(func)
    _logger.debug("Hook %s registered: %s", name, func)


def get_hooks(name: str) -> List[Hook]:
    """
    Return a list of callables registered for the given hook name.
    """
    return list(_registry.get(name, []))


def run_hook(name: str, *args: Any, **kwargs: Any) -> List[Any]:
    """
    Execute all callables registered under ``name`` and collect their results.
    """
    results = []
    for func in get_hooks(name):
        try:
            results.append(func(*args, **kwargs))
        except Exception as exc:  # pragma: no cover
            _logger.error("Hook %s raised %s", name, exc)
    return results


# --------------------------------------------------------------------------- #
# Configuration discovery ---------------------------------------------------- #
# --------------------------------------------------------------------------- #

def find_config(start_path: str, filename: str = "config.json") -> Optional[str]:
    """
    Walk upwards from ``start_path`` looking for a configuration file.
    Returns the absolute path if found, otherwise ``None``.
    """
    current = os.path.abspath(start_path)
    while True:
        candidate = os.path.join(current, filename)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


# --------------------------------------------------------------------------- #
# Data models ---------------------------------------------------------------- #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class Document:
    """
    Represents a single redacted sentence extracted from a transcript.
    """
    id: str
    session_id: str
    text: str
    timestamp: datetime

    @staticmethod
    def create(session_id: str, text: str, timestamp: Optional[datetime] = None) -> "Document":
        """
        Factory that generates a stable UUID based on content and timestamp.
        """
        ts = timestamp or datetime.utcnow()
        raw = f"{session_id}:{text}:{ts.isoformat()}"
        doc_id = uuid.uuid5(uuid.NAMESPACE_OID, raw).hex
        return Document(id=doc_id, session_id=session_id, text=text, timestamp=ts)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the document to a JSON‑compatible dictionary.
        """
        return {
            "id": self.id,
            "session_id": self.session_id,
            "text": self.text,
            "timestamp": self.timestamp.isoformat(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "Document":
        """
        Recreate a Document instance from a dictionary produced by ``to_dict``.
        """
        return Document(
            id=str(data["id"]),
            session_id=str(data["session_id"]),
            text=str(data["text"]),
            timestamp=datetime.fromisoformat(str(data["timestamp"])),
        )


@dataclass(slots=True)
class CaptureState:
    """
    Tracks the last processed byte offset for each session and the archive version.
    """
    session_offsets: Dict[str, int] = field(default_factory=dict)
    archive_version: int = 1

    @staticmethod
    def load(path: str) -> "CaptureState":
        """
        Load a JSON representation from ``path``. If the file does not exist,
        returns a fresh state instance.
        """
        if not os.path.exists(path):
            return CaptureState()
        raw = _read_secure(path)
        try:
            data = json.loads(raw.decode("utf-8"))
            return CaptureState(
                session_offsets={k: int(v) for k, v in data.get("session_offsets", {}).items()},
                archive_version=int(data.get("archive_version", 1)),
            )
        except (ValueError, TypeError) as exc:
            _logger.error("Failed to parse CaptureState from %s: %s", path, exc)
            raise ModelError("Corrupt capture state file") from exc

    def persist(self, path: str) -> None:
        """
        Write the current state to ``path`` atomically.
        """
        data = {
            "session_offsets": self.session_offsets,
            "archive_version": self.archive_version,
        }
        payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        _write_secure(path, payload)


@dataclass(frozen=True, slots=True)
class SearchResult:
    """
    Result of a BM25 query, pairing a document with its relevance score.
    """
    document: Document
    score: float

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the result to a dictionary.
        """
        return {"document": self.document.to_dict(), "score": self.score}


@dataclass(frozen=True, slots=True)
class TranscriptMeta:
    """
    Metadata describing a transcript file.
    """
    session_id: str
    file_path: str
    created_at: datetime
    updated_at: datetime

    @staticmethod
    def from_path(session_id: str, file_path: str) -> "TranscriptMeta":
        """
        Build metadata from the filesystem timestamps of ``file_path``.
        """
        stat = os.stat(file_path)
        created = datetime.fromtimestamp(stat.st_ctime)
        updated = datetime.fromtimestamp(stat.st_mtime)
        return TranscriptMeta(
            session_id=session_id,
            file_path=os.path.abspath(file_path),
            created_at=created,
            updated_at=updated,
        )

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the metadata to a JSON‑compatible dictionary.
        """
        return {
            "session_id": self.session_id,
            "file_path": self.file_path,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """
    Holds the generated summary and auxiliary information.
    """
    session_id: str
    summary_text: str
    generated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the summary result to a dictionary.
        """
        return {
            "session_id": self.session_id,
            "summary_text": self.summary_text,
            "generated_at": self.generated_at.isoformat(),
        }

    @staticmethod
    def from_dict(data: Mapping[str, Any]) -> "SummaryResult":
        """
        Recreate a SummaryResult from its dictionary representation.
        """
        return SummaryResult(
            session_id=str(data["session_id"]),
            summary_text=str(data["summary_text"]),
            generated_at=datetime.fromisoformat(str(data["generated_at"])),
        )


# --------------------------------------------------------------------------- #
# Utility functions ---------------------------------------------------------- #
# --------------------------------------------------------------------------- #

def format_document(doc: Document, fmt: str = "json") -> str:
    """
    Return a string representation of ``doc`` in the requested format.
    Supported formats: ``json`` and ``text``.
    """
    if fmt == "json":
        return json.dumps(doc.to_dict(), ensure_ascii=False, indent=2)
    if fmt == "text":
        return f"{doc.timestamp.isoformat()} [{doc.session_id}] {doc.text}"
    raise ValueError(f"Unsupported format: {fmt!r}")


def format_search_results(results: List[SearchResult], fmt: str = "json") -> str:
    """
    Serialize a list of ``SearchResult`` objects.
    """
    if fmt == "json":
        payload = [r.to_dict() for r in results]
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt == "text":
        lines = []
        for r in results:
            lines.append(f"{r.score:.2f} – {r.document.text}")
        return "\n".join(lines)
    raise ValueError(f"Unsupported format: {fmt!r}")


def load_documents(path: str) -> List[Document]:
    """
    Load a JSON lines file where each line is a serialized Document.
    """
    raw = _read_secure(path)
    docs: List[Document] = []
    for line in raw.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            data = json.loads(line)
            docs.append(Document.from_dict(data))
        except (ValueError, TypeError) as exc:
            _logger.error("Failed to parse Document line: %s", exc)
    return docs


def save_documents(path: str, docs: List[Document]) -> None:
    """
    Persist a list of Document objects as JSON lines.
    """
    lines = "\n".join(json.dumps(d.to_dict(), ensure_ascii=False) for d in docs)
    _write_secure(path, lines.encode("utf-8"))


# --------------------------------------------------------------------------- #
# Exported symbols ----------------------------------------------------------- #
# --------------------------------------------------------------------------- #

__all__ = [
    "Document",
    "CaptureState",
    "SearchResult",
    "TranscriptMeta",
    "SummaryResult",
    "register_hook",
    "get_hooks",
    "run_hook",
    "find_config",
    "format_document",
    "format_search_results",
    "load_documents",
    "save_documents",
]