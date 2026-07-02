import os
import json
import math
import logging
from typing import List, Dict, Any, Tuple, Optional

from src.core.models import (
    Document,
    SearchResult,
    _open_secure,
    _read_secure,
    _write_secure,
    _logger,
    register_hook,
    Hook,
)

# --------------------------------------------------------------------------- #
# Configuration handling
# --------------------------------------------------------------------------- #

_DEFAULT_CONFIG = {
    "k1": 1.5,
    "b": 0.75,
    "index_path": os.path.join(".scribe", "bm25_index.json"),
}

def _discover_config(start_dir: str, filename: str = "bm25_config.json") -> Optional[str]:
    """Walk upwards from ``start_dir`` looking for a JSON config file."""
    current = os.path.abspath(start_dir)
    root = os.path.abspath(os.sep)
    while True:
        candidate = os.path.join(current, filename)
        if os.path.isfile(candidate):
            return candidate
        if current == root:
            break
        current = os.path.dirname(current)
    return None

def _load_config() -> Dict[str, Any]:
    """Load BM25 configuration, falling back to defaults on error."""
    path = _discover_config(os.getcwd())
    if not path:
        return _DEFAULT_CONFIG.copy()
    try:
        fd = _open_secure(path, os.O_RDONLY)
        try:
            raw = b""
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                raw += chunk
        finally:
            os.close(fd)
        data = json.loads(raw.decode())
        if not isinstance(data, dict):
            raise ValueError("Config must be a JSON object")
        cfg = _DEFAULT_CONFIG.copy()
        cfg.update({k: data[k] for k in _DEFAULT_CONFIG.keys() if k in data})
        return cfg
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to load BM25 config %s: %s", path, exc)
        return _DEFAULT_CONFIG.copy()

# --------------------------------------------------------------------------- #
# BM25 core implementation
# --------------------------------------------------------------------------- #

class BM25Index:
    """In‑memory BM25 index with persistence support."""

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.N = 0  # total number of documents
        self.avg_len = 0.0
        self.doc_lengths: Dict[str, int] = {}
        self.term_freqs: Dict[str, Dict[str, int]] = {}
        self.documents: Dict[str, Document] = {}

    # --------------------------------------------------------------------- #
    # Document handling
    # --------------------------------------------------------------------- #

    def add_document(self, doc: Document) -> None:
        """Add a single document to the index, updating statistics."""
        if doc.id in self.documents:
            # Duplicate IDs are ignored to keep idempotency.
            return
        tokens = self._tokenize(doc.text)
        length = len(tokens)
        self.documents[doc.id] = doc
        self.doc_lengths[doc.id] = length
        self.N += 1
        self.avg_len = sum(self.doc_lengths.values()) / self.N

        for token in tokens:
            postings = self.term_freqs.setdefault(token, {})
            postings[doc.id] = postings.get(doc.id, 0) + 1

    def add_documents(self, docs: List[Document]) -> None:
        """Add multiple documents efficiently."""
        for doc in docs:
            self.add_document(doc)

    # --------------------------------------------------------------------- #
    # Scoring utilities
    # --------------------------------------------------------------------- #

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Simple whitespace tokenizer, lower‑casing."""
        return text.lower().split()

    def _idf(self, term: str) -> float:
        """Compute inverse document frequency for a term."""
        df = len(self.term_freqs.get(term, {}))
        if df == 0:
            return 0.0
        return math.log((self.N - df + 0.5) / (df + 0.5) + 1.0)

    def _score(self, query: str) -> List[Tuple[Document, float]]:
        """Score all documents for the given query."""
        query_terms = self._tokenize(query)
        scores: Dict[str, float] = {}
        for term in query_terms:
            idf = self._idf(term)
            postings = self.term_freqs.get(term, {})
            for doc_id, freq in postings.items():
                dl = self.doc_lengths[doc_id]
                norm = (freq * (self.k1 + 1)) / (
                    freq + self.k1 * (1 - self.b + self.b * dl / self.avg_len)
                )
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * norm
        return [(self.documents[doc_id], score) for doc_id, score in scores.items()]

    # --------------------------------------------------------------------- #
    # Persistence
    # --------------------------------------------------------------------- #

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the index to a JSON‑compatible dict."""
        return {
            "k1": self.k1,
            "b": self.b,
            "N": self.N,
            "avg_len": self.avg_len,
            "doc_lengths": self.doc_lengths,
            "term_freqs": self.term_freqs,
            "documents": {
                doc_id: {
                    "id": doc.id,
                    "session_id": doc.session_id,
                    "text": doc.text,
                    "timestamp": doc.timestamp.isoformat(),
                }
                for doc_id, doc in self.documents.items()
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BM25Index":
        """Recreate an index from a dict produced by ``to_dict``."""
        idx = cls(k1=data.get("k1", 1.5), b=data.get("b", 0.75))
        idx.N = data.get("N", 0)
        idx.avg_len = data.get("avg_len", 0.0)
        idx.doc_lengths = data.get("doc_lengths", {})
        idx.term_freqs = data.get("term_freqs", {})
        docs = data.get("documents", {})
        for doc_id, payload in docs.items():
            try:
                ts = datetime.fromisoformat(payload["timestamp"])
            except Exception:  # pragma: no cover
                ts = datetime.utcnow()
            idx.documents[doc_id] = Document(
                id=payload["id"],
                session_id=payload["session_id"],
                text=payload["text"],
                timestamp=ts,
            )
        return idx

# --------------------------------------------------------------------------- #
# IndexBuilder – public façade used by ArchiveEngine
# --------------------------------------------------------------------------- #

class IndexBuilder:
    """Creates and maintains a lightweight on‑disk BM25 index."""

    def __init__(self) -> None:
        cfg = _load_config()
        self.index_path: str = cfg["index_path"]
        self.index = BM25Index(k1=cfg["k1"], b=cfg["b"])
        self._load_existing()
        self._post_add_hooks: List[Hook] = []

    def _load_existing(self) -> None:
        """Load an existing index from disk, if present."""
        if not os.path.isfile(self.index_path):
            return
        try:
            raw = _read_secure(self.index_path)
            data = json.loads(raw.decode())
            self.index = BM25Index.from_dict(data)
        except Exception as exc:  # pragma: no cover
            _logger.error("Failed to load BM25 index %s: %s", self.index_path, exc)

    def add_documents(self, docs: List[Document]) -> None:
        """Incrementally add new sentences to the index while preserving previous state."""
        if not docs:
            return
        self.index.add_documents(docs)
        for hook in self._post_add_hooks:
            try:
                hook(docs)
            except Exception as exc:  # pragma: no cover
                _logger.error("Post‑add hook error: %s", exc)

    def persist(self) -> None:
        """Write the index to the configured .scribe directory using safe file operations."""
        payload = json.dumps(self.index.to_dict(), ensure_ascii=False, indent=2).encode()
        try:
            _write_secure(self.index_path, payload)
        except Exception as exc:  # pragma: no cover
            _logger.error("Failed to persist BM25 index %s: %s", self.index_path, exc)

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Perform a fast offline BM25 search over the indexed sentences."""
        scored = self.index._score(query)
        scored.sort(key=lambda pair: pair[1], reverse=True)
        results: List[SearchResult] = []
        for doc, score in scored[:top_k]:
            results.append(SearchResult(document=doc, score=score))
        return results

    # --------------------------------------------------------------------- #
    # Hook registration API
    # --------------------------------------------------------------------- #

    def register_post_add(self, func: Hook) -> None:
        """Register a hook to be called after documents are added."""
        self._post_add_hooks.append(func)

# Register the builder in the global hook registry for external plugins.
register_hook("index_builder_created", lambda builder: None)