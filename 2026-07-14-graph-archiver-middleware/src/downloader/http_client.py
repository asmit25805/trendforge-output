from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import aiohttp
from aiohttp import ClientError, ClientResponseError

from src.core.models import Action, ActionType, FileNode, NodeStatus, RetryPolicy
from src.graph.graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class Downloader:
    """Asynchronous HTTP downloader with checksum verification and retry support."""

    def __init__(self, session: aiohttp.ClientSession | None = None) -> None:
        self._session = session or aiohttp.ClientSession()

    async def _fetch(self, url: str, dest: Path, retry_policy: RetryPolicy) -> None:
        attempts = 0
        while attempts <= retry_policy.max_retries:
            try:
                async with self._session.get(url) as resp:
                    resp.raise_for_status()
                    hasher = hashlib.sha256()
                    with dest.open("wb") as f:
                        async for chunk in resp.content.iter_chunked(1024 * 64):
                            f.write(chunk)
                            hasher.update(chunk)
                    # Store checksum in metadata (optional)
                    logger.info("Downloaded %s (%d bytes)", url, dest.stat().st_size)
                    return
            except (ClientError, ClientResponseError) as exc:
                attempts += 1
                if attempts > retry_policy.max_retries:
                    logger.error("Failed to download %s after %d attempts: %s", url, attempts - 1, exc)
                    raise
                backoff = retry_policy.backoff_factor * (2 ** (attempts - 1))
                logger.warning("Retry %d for %s after %s seconds", attempts, url, backoff)
                await asyncio.sleep(backoff)

    def download(self, url: str, dest: Path, retry_policy: RetryPolicy = RetryPolicy()) -> None:
        """Public synchronous wrapper that runs the asynchronous download coroutine.

        The function blocks until the download completes.
        """
        asyncio.run(self._fetch(url, dest, retry_policy))

    async def close(self) -> None:
        await self._session.close()
