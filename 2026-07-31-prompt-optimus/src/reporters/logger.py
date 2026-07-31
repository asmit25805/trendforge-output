import logging
import json
import threading
from pathlib import Path
from typing import Any, Mapping

import sqlalchemy as sa
from sqlalchemy import MetaData, Table, Column, String, Float, JSON, insert

from src.core.models import TrialResult, ConfigurationError, EvaluationError


# --------------------------------------------------------------------------- #
# Logger factory
# --------------------------------------------------------------------------- #
def get_logger(name: str) -> logging.Logger:
    """
    Return a configured ``logging.Logger`` instance.

    The logger writes human‑readable messages to ``stderr`` and propagates
    to the root logger.  It is safe to call repeatedly – the same instance
    is returned for a given *name*.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s %(name)s – %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger


# --------------------------------------------------------------------------- #
# Persistence helper
# --------------------------------------------------------------------------- #
class TrialResultWriter:
    """
    Persist ``TrialResult`` objects to a JSON lines file and a SQLite database.

    The writer is thread‑safe; concurrent calls are serialized with an internal
    lock.  The SQLite schema is created on first use.
    """

    _lock = threading.Lock()

    def __init__(self, json_path: Path | str, sqlite_path: Path | str) -> None:
        self.json_path = Path(json_path)
        self.sqlite_path = Path(sqlite_path)

        # Ensure parent directories exist
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialise SQLite engine and table
        self._engine = sa.create_engine(f"sqlite:///{self.sqlite_path}", future=True)
        self._metadata = MetaData()
        self._trials_table = Table(
            "trials",
            self._metadata,
            Column("id", String, primary_key=True),
            Column("candidate_id", String, nullable=False),
            Column("output", JSON, nullable=False),
            Column("score", Float, nullable=False),
            Column("metadata", JSON, nullable=False),
        )
        self._metadata.create_all(self._engine)

    def write(self, result: TrialResult) -> None:
        """
        Append *result* to the JSON lines file and insert it into SQLite.

        Any exception raised by the underlying storage back‑ends is wrapped in
        ``ConfigurationError`` so that callers can treat persistence failures as
        fatal.
        """
        with self._lock:
            self._write_json_line(result)
            self._write_sqlite_row(result)

    def _write_json_line(self, result: TrialResult) -> None:
        """Append a single JSON representation of *result* to the JSON file."""
        try:
            line = json.dumps(result.to_dict(), ensure_ascii=False)
            with self.json_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as exc:
            raise ConfigurationError(f"Failed to write trial result to JSON file {self.json_path}: {exc}") from exc

    def _write_sqlite_row(self, result: TrialResult) -> None:
        """Insert *result* as a row in the SQLite ``trials`` table."""
        try:
            stmt = insert(self._trials_table).values(
                id=str(uuid.uuid4()),
                candidate_id=result.candidate_id,
                output=result.output,
                score=result.score,
                metadata=dict(result.metadata),
            )
            with self._engine.begin() as conn:
                conn.execute(stmt)
        except sa.exc.SQLAlchemyError as exc:
            raise ConfigurationError(f"Failed to insert trial result into SQLite DB {self.sqlite_path}: {exc}") from exc


# --------------------------------------------------------------------------- #
# Convenience wrapper used by the engine
# --------------------------------------------------------------------------- #
def persist_trial(result: TrialResult, json_path: Path | str = "prompt_optimus_trials.json",
                 sqlite_path: Path | str = "prompt_optimus_trials.db") -> None:
    """
    Persist *result* using a singleton ``TrialResultWriter``.

    The function creates a writer on first call and re‑uses it thereafter,
    avoiding repeated engine initialisation overhead.
    """
    global _writer_instance  # type: ignore
    try:
        _writer_instance
    except NameError:
        _writer_instance = TrialResultWriter(json_path, sqlite_path)  # noqa: N806
    _writer_instance.write(result)