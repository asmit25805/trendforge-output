from __future__ import annotations

import datetime
import logging
import re
from collections import Counter
from typing import List

from pydantic import ValidationError

from src.core.models import Leaderboard, RepositoryInfo, ToolEntry

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class Aggregator:
    """Aggregates `RepositoryInfo` objects into a `Leaderboard`.

    For each repository the aggregator fetches the `.awesome-ai.md` file, parses
    the markdown table rows, validates them against the `ToolEntry` model and
    builds a deduplicated, scored leaderboard.
    """

    TOOL_TABLE_REGEX = re.compile(r"\|\s*(?P<name>[^|]+?)\s*\|\s*(?P<desc>[^|]+?)\s*\|\s*(?P<cat>[^|]+?)\s*\|\s*(?P<home>[^|]*?)\s*\|\s*(?P<github>[^|]*?)\s*\|\s*(?P<score>[^|]+?)\s*\|", re.IGNORECASE)

    def __init__(self, http_client: Optional[httpx.AsyncClient] = None):
        self.http_client = http_client or httpx.AsyncClient()

    async def _fetch_markdown(self, repo: RepositoryInfo) -> str:
        raw_url = f"https://raw.githubusercontent.com/{repo.owner}/{repo.name}/master/.awesome-ai.md"
        resp = await self.http_client.get(raw_url, timeout=10)
        resp.raise_for_status()
        return resp.text

    def _parse_rows(self, markdown: str) -> List[ToolEntry]:
        entries: List[ToolEntry] = []
        for line in markdown.splitlines():
            match = self.TOOL_TABLE_REGEX.search(line)
            if not match:
                continue
            data = match.groupdict()
            try:
                entry = ToolEntry(
                    name=data["name"].strip(),
                    description=data["desc"].strip(),
                    category=data["cat"].strip(),
                    homepage=data["home"].strip() or None,
                    github=data["github"].strip() or None,
                    score=float(data["score"].strip()),
                )
                entries.append(entry)
            except ValidationError as ve:
                logger.warning("Invalid tool entry in %s: %s", repo.name, ve)
        return entries

    async def aggregate(self, repos: List[RepositoryInfo]) -> Leaderboard:
        """Process a list of repositories and return a populated `Leaderboard`."""
        leaderboard = Leaderboard()
        seen = set()
        for repo in repos:
            try:
                markdown = await self._fetch_markdown(repo)
                entries = self._parse_rows(markdown)
                for entry in entries:
                    key = (entry.name.lower(), entry.github or entry.homepage)
                    if key in seen:
                        continue
                    seen.add(key)
                    leaderboard.add_entry(entry)
            except Exception as exc:
                logger.error("Failed to process repository %s: %s", repo.name, exc)
        leaderboard.sort()
        return leaderboard
