from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import List

from src.core.models import Leaderboard, ToolEntry

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


def render_markdown(leaderboard: Leaderboard) -> str:
    """Render a `Leaderboard` as a markdown table.

    The table contains the columns: Name, Description, Category, Homepage,
    GitHub and Score.
    """
    header = (
        "| Name | Description | Category | Homepage | GitHub | Score |\n"
        "|------|-------------|----------|----------|--------|-------|"
    )
    rows: List[str] = []
    for entry in leaderboard.entries:
        rows.append(
            f"| {entry.name} | {entry.description} | {entry.category} | "
            f"{entry.homepage or ''} | {entry.github or ''} | {entry.score:.1f} |"
        )
    table = "\n".join([header] + rows)
    return table


def render_json(leaderboard: Leaderboard) -> str:
    """Render a `Leaderboard` as a JSON string.

    The JSON structure mirrors the Pydantic model, with `generated_at` formatted
    as an ISO‑8601 timestamp.
    """
    def default(o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, (Leaderboard, ToolEntry)):
            return o.dict()
        raise TypeError(f"Object of type {type(o)} is not JSON serializable")

    json_str = json.dumps(leaderboard, default=default, indent=2)
    return json_str
