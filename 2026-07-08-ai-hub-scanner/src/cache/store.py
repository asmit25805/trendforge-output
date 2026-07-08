from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

from src.core.models import Leaderboard, RepositoryInfo
from src.web.renderer import render_json, render_markdown

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class CacheStore:
    """A very small in‑memory cache with optional JSON persistence.

    The cache stores arbitrary Python objects keyed by a string. For leaderboard
    data we provide convenience methods that automatically serialize to JSON or
    markdown using the renderer helpers.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._store: Dict[str, Any] = {}
        self._expiry: Dict[str, float] = {}
        self.ttl_seconds = ttl_seconds

    def set(self, key: str, value: Any) -> None:
        self._store[key] = value
        self._expiry[key] = time.time() + self.ttl_seconds
        logger.debug("Cache set: %s (expires in %s seconds)", key, self.ttl_seconds)

    def get(self, key: str) -> Optional[Any]:
        if key not in self._store:
            logger.debug("Cache miss: %s", key)
            return None
        if time.time() > self._expiry.get(key, 0):
            logger.debug("Cache expired: %s", key)
            self._store.pop(key, None)
            self._expiry.pop(key, None)
            return None
        logger.debug("Cache hit: %s", key)
        return self._store[key]

    # Convenience helpers for the leaderboard type
    def set_leaderboard(self, leaderboard: Leaderboard) -> None:
        self.set("leaderboard", leaderboard)

    def get_leaderboard(self) -> Optional[Leaderboard]:
        return self.get("leaderboard")

    def render_leaderboard_markdown(self) -> Optional[str]:
        lb = self.get_leaderboard()
        if lb is None:
            return None
        return render_markdown(lb)

    def render_leaderboard_json(self) -> Optional[str]:
        lb = self.get_leaderboard()
        if lb is None:
            return None
        return render_json(lb)
