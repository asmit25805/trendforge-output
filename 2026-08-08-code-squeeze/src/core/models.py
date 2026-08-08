import logging
from pathlib import Path
from typing import List

from pydantic import BaseModel, Field, validator

logger = logging.getLogger(__name__)


class Segment(BaseModel):
    """Represents a code segment that will be sent to the LLM for compression."""

    path: str = Field(..., description="File path of the segment")
    content: str = Field(..., description="Raw source code of the segment")
    start_line: int = Field(0, ge=0, description="Zero‑based start line index")
    end_line: int = Field(0, ge=0, description="Zero‑based end line index (exclusive)")


class CompressionResult(BaseModel):
    """Result returned after compressing a Segment."""

    compressed: str = Field(..., description="Compressed source code")
    original_length: int = Field(..., description="Length of the original content in characters")
    compressed_length: int = Field(..., description="Length of the compressed content in characters")


class Config(BaseModel):
    """Configuration object used throughout the proxy.

    The defaults are suitable for local development; they can be overridden by the caller.
    """

    cache_path: Path = Field(Path('.cache'), description="Directory where the SQLite cache is stored")
    provider: str = Field('openai', description="Name of the LLM provider to use")
    model: str = Field('gpt-4o-mini', description="Model identifier for the provider")
    max_batch_size: int = Field(5, ge=1, description="Maximum number of segments processed in a single batch")

    @validator('cache_path', pre=True)
    def _coerce_path(cls, v):
        return Path(v)
