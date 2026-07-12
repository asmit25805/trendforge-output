import asyncio
import logging
import sqlite3
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.core.models import AuthContext

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class InvalidKeyError(Exception):
    """Raised when an API key is unknown, revoked, or malformed."""


class QuotaExceededError(Exception):
    """Raised when a request would exceed the remaining quota for an API key."""


class AuthProvider(ABC):
    """Abstract base class for API‑key authentication back‑ends.

    Concrete implementations must provide ``validate_key`` and ``deduct_quota``.
    """

    @abstractmethod
    async def validate_key(self, api_key: str) -> AuthContext:
        """Validate *api_key* and return an :class:`AuthContext`.

        Must raise :class:`InvalidKeyError` if the key is not recognised.
        """

    @abstractmethod
    async def deduct_quota(self, api_key: str, tokens: int) -> None:
        """Deduct *tokens* from the quota associated with *api_key*.

        Must raise :class:`QuotaExceededError` if the remaining quota would become
        negative.
        """


class SQLiteAuthProvider(AuthProvider):
    """Simple SQLite‑backed implementation of :class:`AuthProvider`.

    The SQLite database must contain a table ``api_keys`` with columns:

    - ``key`` (TEXT PRIMARY KEY)
    - ``quota`` (INTEGER) – total token quota for the key
    - ``revoked`` (INTEGER) – 0 for active, 1 for revoked
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def _ensure_schema(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS api_keys (
                    key TEXT PRIMARY KEY,
                    quota INTEGER NOT NULL,
                    revoked INTEGER NOT NULL CHECK (revoked IN (0,1))
                )
                """
            )
            conn.commit()

    async def validate_key(self, api_key: str) -> AuthContext:
        def _query():
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT quota, revoked FROM api_keys WHERE key = ?",
                    (api_key,),
                )
                row = cur.fetchone()
                return row

        row = await asyncio.get_event_loop().run_in_executor(None, _query)
        if row is None:
            raise InvalidKeyError(f"Key '{api_key}' not found")
        quota, revoked = row
        if revoked:
            raise InvalidKeyError(f"Key '{api_key}' is revoked")
        return AuthContext(api_key=api_key, quota_remaining=quota)

    async def deduct_quota(self, api_key: str, tokens: int) -> None:
        def _deduct():
            with self._connect() as conn:
                cur = conn.execute(
                    "SELECT quota FROM api_keys WHERE key = ?",
                    (api_key,),
                )
                row = cur.fetchone()
                if row is None:
                    raise InvalidKeyError(f"Key '{api_key}' not found")
                current_quota = row[0]
                if current_quota < tokens:
                    raise QuotaExceededError(
                        f"Key '{api_key}' has {current_quota} tokens left, "
                        f"but {tokens} were requested"
                    )
                new_quota = current_quota - tokens
                conn.execute(
                    "UPDATE api_keys SET quota = ? WHERE key = ?",
                    (new_quota, api_key),
                )
                conn.commit()

        await asyncio.get_event_loop().run_in_executor(None, _deduct)
