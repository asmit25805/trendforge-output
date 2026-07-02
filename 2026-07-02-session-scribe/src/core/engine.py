import os
import json
import uuid
import argparse
import logging
from datetime import datetime
from typing import List, Dict, Any

from src.core.models import (
    Document,
    CaptureState,
    SearchResult,
    _open_secure,
    _read_secure,
    _write_secure,
    _logger,
)

from src.redaction.redactor import Redactor
from src.summarization.summarizer import Summarizer
from src.indexing.bm25 import IndexBuilder


CAPTURE_STATE_PATH = os.path.join(".scribe", "capture_state.json")
CONTEXT_PATH = os.path.join(".scribe", "context.md")


def _load_capture_state() -> CaptureState:
    """Load the persistent capture state, creating a default if missing."""
    if not os.path.exists(CAPTURE_STATE_PATH):
        default_state = CaptureState(session_offsets={}, archive_version=1)
        _write_secure(CAPTURE_STATE_PATH, json.dumps(asdict(default_state)).encode())
        return default_state
    raw = _read_secure(CAPTURE_STATE_PATH)
    data = json.loads(raw.decode())
    return CaptureState(**data)


def _save_capture_state(state: CaptureState) -> None:
    """Persist the capture state atomically."""
    payload = json.dumps(
        {
            "session_offsets": state.session_offsets,
            "archive_version": state.archive_version,
        },
        sort_keys=True,
    ).encode()
    _write_secure(CAPTURE_STATE_PATH, payload)


class ArchiveEngine:
    """Coordinates the end‑to‑end pipeline for a given session."""

    def __init__(self) -> None:
        self.redactor = Redactor()
        self.summarizer = Summarizer()
        self.index_builder = IndexBuilder()
        self.state = _load_capture_state()

    def _transcript_path(self, session_id: str) -> str:
        """Derive the transcript file name for a session."""
        return f"{session_id}.txt"

    def _read_new_lines(self, path: str, offset: int) -> List[str]:
        """Read all lines appended after the stored offset."""
        fd = _open_secure(path, os.O_RDONLY)
        try:
            os.lseek(fd, offset, os.SEEK_SET)
            chunks = []
            while True:
                data = os.read(fd, 8192)
                if not data:
                    break
                chunks.append(data)
            raw = b"".join(chunks)
            return raw.decode(errors="replace").splitlines()
        finally:
            os.close(fd)

    def process_session(self, session_id: str) -> None:
        """Detect new transcript lines, run through the pipeline, and update the archive."""
        transcript_path = self._transcript_path(session_id)
        if not os.path.isfile(transcript_path):
            _logger.error("Transcript file not found for session %s", session_id)
            return

        offset = self.state.session_offsets.get(session_id, 0)
        try:
            new_lines = self._read_new_lines(transcript_path, offset)
        except Exception as exc:
            _logger.error("Failed to read transcript %s: %s", transcript_path, exc)
            return

        if not new_lines:
            return

        documents: List[Document] = []
        for line in new_lines:
            try:
                safe_line = self.redactor.redact(line)
            except Exception as exc:
                _logger.error("Redaction error on line %r: %s", line, exc)
                safe_line = line
            doc = Document(
                id=str(uuid.uuid4()),
                session_id=session_id,
                text=safe_line,
                timestamp=datetime.utcnow(),
            )
            documents.append(doc)

        try:
            self.index_builder.add_documents(documents)
            self.index_builder.persist()
        except Exception as exc:
            _logger.error("Indexing error for session %s: %s", session_id, exc)

        try:
            sentences = [doc.text for doc in documents]
            summary = self.summarizer.summarize(sentences, ratio=0.2)
            summary_bytes = "\n".join(summary).encode()
            _write_secure(CONTEXT_PATH, summary_bytes)
        except Exception as exc:
            _logger.error("Summarization error for session %s: %s", session_id, exc)

        # Update offset to end of file
        try:
            final_size = os.path.getsize(transcript_path)
            self.state.session_offsets[session_id] = final_size
            _save_capture_state(self.state)
        except Exception as exc:
            _logger.error("Failed to update capture state for %s: %s", session_id, exc)

    def search(self, query: str, top_k: int = 5) -> List[SearchResult]:
        """Perform a fast, offline BM25 search over the indexed sentences."""
        try:
            raw_results = self.index_builder.search(query, top_k)
        except Exception as exc:
            _logger.error("Search operation failed: %s", exc)
            return []

        results: List[SearchResult] = []
        for doc, score in raw_results:
            results.append(SearchResult(document=doc, score=score))
        return results


def process_cli() -> None:
    """Entry point for the command‑line interface."""
    parser = argparse.ArgumentParser(prog="session-scribe")
    subparsers = parser.add_subparsers(dest="command", required=True)

    proc_parser = subparsers.add_parser("process", help="Process a session transcript")
    proc_parser.add_argument("session_id", type=str, help="Identifier of the session")

    search_parser = subparsers.add_parser("search", help="Search the archive")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument(
        "--top", type=int, default=5, help="Number of results to return"
    )

    args = parser.parse_args()
    engine = ArchiveEngine()

    if args.command == "process":
        engine.process_session(args.session_id)
    elif args.command == "search":
        results = engine.search(args.query, top_k=args.top)
        for res in results:
            print(f"{res.document.session_id}: {res.document.text} (score: {res.score:.2f})")
    else:
        parser.error("Unknown command")

if __name__ == "__main__":
    process_cli()