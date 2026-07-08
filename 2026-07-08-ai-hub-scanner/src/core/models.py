from __future__ import annotations

import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl, validator


class RepositoryInfo(BaseModel):
    """Information about a GitHub repository that contains an `.awesome-ai.md` file."""

    name: str = Field(..., description="Repository name")
    owner: str = Field(..., description="Repository owner/login")
    html_url: HttpUrl = Field(..., description="URL to the repository on GitHub")
    description: Optional[str] = Field(None, description="Repository description")
    pushed_at: datetime.datetime = Field(..., description="Last push timestamp")

    @validator("pushed_at", pre=True)
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.datetime.fromisoformat(v.rstrip('Z'))
        return v


class ToolEntry(BaseModel):
    """A single AI tool entry parsed from a markdown file."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Short description of the tool")
    category: Literal["LLM", "Dataset", "Framework", "Other"] = Field(..., description="Tool category")
    homepage: Optional[HttpUrl] = Field(None, description="Official homepage URL")
    github: Optional[HttpUrl] = Field(None, description="GitHub repository URL")
    score: float = Field(0.0, ge=0.0, le=100.0, description="Computed relevance score")

    @validator("score", pre=True, always=True)
    def default_score(cls, v):
        return float(v) if v is not None else 0.0


class Leaderboard(BaseModel):
    """Aggregated list of tool entries with a generation timestamp."""

    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.utcnow)
    entries: List[ToolEntry] = Field(default_factory=list)

    def add_entry(self, entry: ToolEntry) -> None:
        self.entries.append(entry)

    def sort(self) -> None:
        self.entries.sort(key=lambda e: e.score, reverse=True)
