from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import List

from src.scanner.github import GitHubScanner
from src.aggregator.engine import Aggregator
from src.cache.store import CacheStore
from src.web.renderer import render_markdown, render_json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main() -> None:
    # 1. Scan GitHub for repositories containing `.awesome-ai.md`
    scanner = GitHubScanner()
    repos = scanner.scan()
    logger.info("Scanned %s repositories", len(repos))

    # 2. Aggregate the markdown entries into a leaderboard
    aggregator = Aggregator()
    # Aggregator.aggregate is async; run it in an event loop
    import asyncio
    leaderboard = asyncio.run(aggregator.aggregate(repos))
    logger.info("Aggregated %s tool entries", len(leaderboard.entries))

    # 3. Cache the leaderboard for later use
    cache = CacheStore()
    cache.set_leaderboard(leaderboard)

    # 4. Render outputs
    md = render_markdown(leaderboard)
    json_output = render_json(leaderboard)
    print("--- Markdown Leaderboard ---")
    print(md)
    print("--- JSON Leaderboard ---")
    print(json_output)

if __name__ == "__main__":
    main()
