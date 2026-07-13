import json
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from pydantic import BaseModel, Field, root_validator, validator
from sqlalchemy import (Boolean, Column, DateTime, Enum as SAEnum, JSON,
                        LargeBinary, String, create_engine, select, Table,
                        MetaData)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError


class InputType(str, Enum):
    """Supported input modalities for illustration requests."""
    TEXT = "text"
    TABLE = "table"
    SCREENSHOT = "screenshot"


class TargetUse(str, Enum):
    """Intended usage contexts that influence aspect ratio and style."""
    SLIDE = "slide"
    ARTICLE = "article"
    SOCIAL_CARD = "social_card"


class QAReport(BaseModel):
    """Result of the validation step performed by ``ImageValidator``."""
    passed: bool = Field(..., description="Overall pass/fail flag")
    failed_checks: List[str] = Field(
        default_factory=list,
        description="Names of checklist items that failed"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Free‑form feedback from the secondary LLM reviewer"
    )
    retryable: bool = Field(
        ...,
        description="Whether the failure can be auto‑fixed by regeneration"
    )

    def is_successful(self) -> bool:
        """Return ``True`` if the report indicates a passing validation."""
        return self.passed

    def should_retry(self) -> bool:
        """Return ``True`` if the failure is marked as retryable."""
        return not self.passed and self.retryable

    def json(self, **kwargs: Any) -> str:
        """Serialize the report to a JSON string."""
        return super().json(**kwargs)


class IllustrationRequest(BaseModel):
    """Payload supplied by the user to request a Guizang‑style illustration."""
    request_id: str = Field(
        ...,
        description="Unique UUID for tracing the request"
    )
    input_type: InputType = Field(
        ...,
        description="How the user supplied the source data"
    )
    raw_content: Union[str, bytes] = Field(
        ...,
        description="Original text, CSV string, or image bytes"
    )
    target_use: TargetUse = Field(
        ...,
        description="Hints for aspect ratio and layout"
    )
    custom_accent: Optional[str] = Field(
        None,
        description="Hex code to override the default accent color"
    )

    @validator("request_id")
    def validate_uuid(cls, v: str) -> str:
        """Ensure ``request_id`` is a valid UUID string."""
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"request_id must be a valid UUID: {v}") from exc
        return v

    @validator("custom_accent")
    def validate_hex_color(cls, v: Optional[str]) -> Optional[str]:
        """Validate optional hex colour strings."""
        if v is None:
            return v
        if not isinstance(v, str) or not v.startswith("#") or len(v) not in (4, 7):
            raise ValueError(f"custom_accent must be a hex colour like '#FFF' or '#FFFFFF', got {v}")
        return v.lower()

    @root_validator
    def check_content_type(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        """Enforce that ``raw_content`` matches the declared ``input_type``."""
        itype = values.get("input_type")
        content = values.get("raw_content")
        if itype == InputType.SCREENSHOT:
            if not isinstance(content, (bytes, bytearray)):
                raise TypeError("raw_content must be bytes for screenshot input_type")
        else:
            if not isinstance(content, str):
                raise TypeError("raw_content must be a string for text or table input_type")
        return values

    def to_dict(self) -> Dict[str, Any]:
        """Return a plain‑dict representation suitable for persistence."""
        return json.loads(self.json())

    def json(self, **kwargs: Any) -> str:
        """Serialize the request to JSON, ensuring UUID string format."""
        data = super().dict()
        data["request_id"] = str(data["request_id"])
        return json.dumps(data, **kwargs)


class IllustrationResult(BaseModel):
    """Final artifact returned after successful image generation and validation."""
    request_id: str = Field(..., description="Links back to the original request")
    image_bytes: bytes = Field(..., description="Final PNG/JPEG ready for embedding")
    prompt_used: str = Field(..., description="Exact prompt sent to the image model")
    qa_report: QAReport = Field(..., description="Outcome of the validation step")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the image was produced"
    )

    @validator("request_id")
    def validate_uuid(cls, v: str) -> str:
        """Ensure ``request_id`` is a valid UUID string."""
        try:
            uuid.UUID(v)
        except ValueError as exc:
            raise ValueError(f"request_id must be a valid UUID: {v}") from exc
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Return a serialisable dict, converting bytes to base64."""
        data = self.dict()
        data["image_bytes"] = self.image_bytes.hex()
        data["qa_report"] = json.loads(self.qa_report.json())
        data["timestamp"] = self.timestamp.isoformat()
        return data

    def json(self, **kwargs: Any) -> str:
        """Serialize the result to JSON, handling binary data safely."""
        return json.dumps(self.to_dict(), **kwargs)


class EventEmitter:
    """Simple publish‑subscribe mechanism used by core components."""
    def __init__(self) -> None:
        self._handlers: Dict[str, List[Callable[[Any], None]]] = {}

    def register_hook(self, event: str, handler: Callable[[Any], None]) -> None:
        """Register ``handler`` to be called when ``event`` is emitted."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: Any) -> None:
        """Synchronously invoke all handlers associated with ``event``."""
        for handler in self._handlers.get(event, []):
            try:
                handler(payload)
            except Exception as exc:
                # Logging is deliberately lightweight to avoid external deps.
                print(f"[EventEmitter] Handler error for event '{event}': {exc}")


class SQLitePersistence:
    """Utility class that persists pipeline artifacts to a local SQLite database."""
    def __init__(self, db_path: Union[str, Path] = "guizang_visualizer.db") -> None:
        self.engine: Engine = create_engine(f"sqlite:///{Path(db_path)}", echo=False, future=True)
        self.metadata = MetaData()
        self._define_tables()
        self.metadata.create_all(self.engine)

    def _define_tables(self) -> None:
        """Define tables for requests, results and QA reports."""
        self.requests = Table(
            "requests",
            self.metadata,
            Column("request_id", String, primary_key=True),
            Column("payload", JSON, nullable=False),
            Column("created_at", DateTime, default=datetime.utcnow)
        )
        self.results = Table(
            "results",
            self.metadata,
            Column("request_id", String, primary_key=True),
            Column("image_bytes", LargeBinary, nullable=False),
            Column("prompt_used", String, nullable=False),
            Column("qa_report", JSON, nullable=False),
            Column("timestamp", DateTime, default=datetime.utcnow)
        )

    def persist_request(self, request: IllustrationRequest) -> None:
        """Insert a new request record; overwrites on conflict."""
        stmt = self.requests.insert().values(
            request_id=request.request_id,
            payload=request.to_dict(),
            created_at=datetime.utcnow()
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def persist_result(self, result: IllustrationResult) -> None:
        """Insert a new result record; overwrites on conflict."""
        stmt = self.results.insert().values(
            request_id=result.request_id,
            image_bytes=result.image_bytes,
            prompt_used=result.prompt_used,
            qa_report=result.qa_report.dict(),
            timestamp=result.timestamp
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)

    def fetch_request(self, request_id: str) -> Optional[IllustrationRequest]:
        """Retrieve a stored request by its UUID."""
        stmt = select(self.requests.c.payload).where(self.requests.c.request_id == request_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        if row:
            payload = row[0]
            return IllustrationRequest(**payload)
        return None

    def fetch_result(self, request_id: str) -> Optional[IllustrationResult]:
        """Retrieve a stored result by its UUID."""
        stmt = select(
            self.results.c.image_bytes,
            self.results.c.prompt_used,
            self.results.c.qa_report,
            self.results.c.timestamp
        ).where(self.results.c.request_id == request_id)
        with self.engine.connect() as conn:
            row = conn.execute(stmt).first()
        if row:
            image_bytes, prompt_used, qa_report_dict, timestamp = row
            qa_report = QAReport(**qa_report_dict)
            return IllustrationResult(
                request_id=request_id,
                image_bytes=image_bytes,
                prompt_used=prompt_used,
                qa_report=qa_report,
                timestamp=timestamp
            )
        return None

    def close(self) -> None:
        """Dispose the underlying engine."""
        self.engine.dispose()


# Export symbols for external imports
__all__ = [
    "InputType",
    "TargetUse",
    "IllustrationRequest",
    "IllustrationResult",
    "QAReport",
    "EventEmitter",
    "SQLitePersistence",
]