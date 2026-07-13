import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel, create_model, ValidationError

# --------------------------------------------------------------------------- #
# Global logger configuration
# --------------------------------------------------------------------------- #
_logger = logging.getLogger(__name__)
_handler = logging.StreamHandler()
_formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S"
)
_handler.setFormatter(_formatter)
_logger.addHandler(_handler)
_logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------- #
# Event handling utilities
# --------------------------------------------------------------------------- #
_event_handlers: Dict[str, List[Callable[[Dict[str, Any]], None]]] = {}
_event_lock = threading.Lock()


def register_event_handler(event: str, handler: Callable[[Dict[str, Any]], None]) -> None:
    """
    Register a callable to be invoked when *event* is emitted.
    """
    with _event_lock:
        _event_handlers.setdefault(event, []).append(handler)
    _logger.debug("Handler %s registered for event %s", handler, event)


def emit_event(event: str, payload: Dict[str, Any]) -> None:
    """
    Emit *event* to all registered handlers. Handlers are executed sequentially.
    """
    handlers = _event_handlers.get(event, [])
    if not handlers:
        _logger.debug("No handlers for event %s", event)
        return

    _logger.info("Emitting event %s with payload keys %s", event, list(payload.keys()))
    for handler in handlers:
        try:
            handler(payload)
        except Exception as exc:  # pragma: no cover
            _logger.error(
                "Error in handler %s for event %s: %s", handler, event, exc, exc_info=True
            )


# --------------------------------------------------------------------------- #
# JSON‑schema validation (via Pydantic)
# --------------------------------------------------------------------------- #
def _build_pydantic_model(schema: Dict[str, Any]) -> Type[BaseModel]:
    """
    Dynamically construct a Pydantic model from a JSON‑schema dictionary.
    Supports ``type`` and ``enum`` constraints for simple fields.
    """
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: Dict[str, Tuple[Any, Any]] = {}

    for name, prop in properties.items():
        field_type = Any
        if prop.get("type") == "string":
            field_type = str
        elif prop.get("type") == "integer":
            field_type = int
        elif prop.get("type") == "number":
            field_type = float
        elif prop.get("type") == "boolean":
            field_type = bool
        elif prop.get("type") == "object":
            field_type = dict
        elif prop.get("type") == "array":
            field_type = list

        if "enum" in prop:
            enum_vals = tuple(prop["enum"])
            field_type = field_type if field_type is not Any else str

            class EnumValidator(str):
                @classmethod
                def __get_validators__(cls):
                    yield cls.validate

                @classmethod
                def validate(cls, v):
                    if v not in enum_vals:
                        raise ValueError(f"{v!r} not in allowed enum {enum_vals}")
                    return v

            field_type = EnumValidator

        default = ... if name in required else None
        fields[name] = (field_type, default)

    return create_model("DynamicSchemaModel", **fields)  # type: ignore[arg-type]


def validate_schema(data: Dict[str, Any], schema: Dict[str, Any]) -> bool:
    """
    Validate *data* against a JSON‑schema dict. Returns True on success, False otherwise.
    """
    Model = _build_pydantic_model(schema)
    try:
        Model(**data)
        _logger.debug("Schema validation succeeded for data %s", data)
        return True
    except ValidationError as exc:
        _logger.warning("Schema validation failed: %s", exc)
        return False


# --------------------------------------------------------------------------- #
# SQLite connection helpers
# --------------------------------------------------------------------------- #
_connection_cache: Dict[str, sqlite3.Connection] = {}
_connection_lock = threading.Lock()


def get_sqlite_connection(db_path: str = "guizang_visualizer.db") -> sqlite3.Connection:
    """
    Return a thread‑safe SQLite connection for *db_path*. Connections are cached per path.
    """
    with _connection_lock:
        if db_path not in _connection_cache:
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            _connection_cache[db_path] = conn
            _logger.info("Created new SQLite connection for %s", db_path)
        else:
            conn = _connection_cache[db_path]
    return conn


def close_sqlite_connection(db_path: str = "guizang_visualizer.db") -> None:
    """
    Close and remove the cached SQLite connection for *db_path*.
    """
    with _connection_lock:
        conn = _connection_cache.pop(db_path, None)
        if conn:
            conn.close()
            _logger.info("Closed SQLite connection for %s", db_path)


def execute_sql(
    sql: str, parameters: Optional[Tuple[Any, ...]] = None, db_path: str = "guizang_visualizer.db"
) -> List[sqlite3.Row]:
    """
    Execute *sql* with optional *parameters* and return fetched rows.
    """
    conn = get_sqlite_connection(db_path)
    cur = conn.cursor()
    try:
        if parameters:
            cur.execute(sql, parameters)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        conn.commit()
        _logger.debug("Executed SQL: %s with params %s", sql, parameters)
        return rows
    finally:
        cur.close()


# --------------------------------------------------------------------------- #
# Retry decorator with exponential back‑off
# --------------------------------------------------------------------------- #
def retry(
    attempts: int = 3,
    backoff_factor: float = 0.5,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator that retries the wrapped function on *retry_exceptions*.
    Uses exponential back‑off based on *backoff_factor*.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            delay = backoff_factor
            for attempt in range(1, attempts + 1):
                try:
                    _logger.debug(
                        "Attempt %d/%d for function %s", attempt, attempts, func.__name__
                    )
                    return func(*args, **kwargs)
                except retry_exceptions as exc:
                    if attempt == attempts:
                        _logger.error(
                            "All %d attempts failed for %s: %s", attempts, func.__name__, exc
                        )
                        raise
                    _logger.warning(
                        "Retryable error on attempt %d for %s: %s – sleeping %.2fs",
                        attempt,
                        func.__name__,
                        exc,
                        delay,
                    )
                    time.sleep(delay)
                    delay *= 2
            # Unreachable – the loop either returns or raises
            raise RuntimeError("Retry logic fell through unexpectedly")  # pragma: no cover

        return wrapper

    return decorator


# --------------------------------------------------------------------------- #
# JSON file utilities
# --------------------------------------------------------------------------- #
def load_json_file(path: Path | str) -> Dict[str, Any]:
    """
    Load a JSON file from *path* and return its content as a dictionary.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"JSON file not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    _logger.debug("Loaded JSON from %s", p)
    return data


def save_json_file(data: Dict[str, Any], path: Path | str) -> None:
    """
    Serialize *data* as JSON and write it to *path*.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    _logger.info("Saved JSON to %s", p)


# --------------------------------------------------------------------------- #
# Structured logging helper
# --------------------------------------------------------------------------- #
def log_structured(event: str, payload: Dict[str, Any]) -> None:
    """
    Emit a structured log line for *event* with *payload* fields.
    """
    message = json.dumps({"event": event, "payload": payload}, ensure_ascii=False)
    _logger.info(message)


# --------------------------------------------------------------------------- #
# Context manager for temporary SQLite transactions
# --------------------------------------------------------------------------- #
class Transaction:
    """
    Context manager that wraps a SQLite transaction. Commits on success,
    rolls back on exception.
    """

    def __init__(self, db_path: str = "guizang_visualizer.db"):
        self._db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None

    def __enter__(self) -> sqlite3.Cursor:
        self._conn = get_sqlite_connection(self._db_path)
        self._cursor = self._conn.cursor()
        self._cursor.execute("BEGIN")
        _logger.debug("Started transaction on %s", self._db_path)
        return self._cursor

    def __exit__(self, exc_type: Optional[Type[BaseException]], exc: Optional[BaseException], tb: Any) -> None:
        if self._conn is None:
            return
        if exc_type is None:
            self._conn.commit()
            _logger.debug("Transaction committed on %s", self._db_path)
        else:
            self._conn.rollback()
            _logger.warning(
                "Transaction rolled back on %s due to %s", self._db_path, exc_type
            )
        self._cursor.close()


# --------------------------------------------------------------------------- #
# Public symbols export
# --------------------------------------------------------------------------- #
__all__ = [
    "register_event_handler",
    "emit_event",
    "validate_schema",
    "get_sqlite_connection",
    "close_sqlite_connection",
    "execute_sql",
    "retry",
    "load_json_file",
    "save_json_file",
    "log_structured",
    "Transaction",
]