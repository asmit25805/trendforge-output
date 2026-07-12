import os
import sqlite3
import tempfile
from typing import Generator

import pytest

from src.auth.auth import (
    AuthProvider,
    InvalidKeyError,
    QuotaExceededError,
    AuthContext,
)


@pytest.fixture(scope="function")
def sqlite_provider() -> Generator[AuthProvider, None, None]:
    """Create a temporary SQLite backend with a single test key."""
    with tempfile.NamedTemporaryFile(delete=False) as tf:
        db_path = tf.name
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE api_keys (
                api_key TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                quota INTEGER NOT NULL
            )
            """
        )
        # Insert a known key with a generous quota.
        cur.execute(
            """
            INSERT INTO api_keys (api_key, owner_id, quota)
            VALUES (?, ?, ?)
            """,
            ("test-key-123", "owner-42", 1000),
        )
        conn.commit()
        conn.close()

        provider = AuthProvider(backend="sqlite", db_path=db_path)
        yield provider
    finally:
        os.unlink(db_path)


def test_verify_returns_auth_context(sqlite_provider: AuthProvider) -> None:
    ctx = sqlite_provider.verify("test-key-123")
    assert isinstance(ctx, AuthContext)
    assert ctx.api_key == "test-key-123"
    assert ctx.owner_id == "owner-42"
    assert ctx.quota == 1000


def test_verify_invalid_key_raises(sqlite_provider: AuthProvider) -> None:
    with pytest.raises(InvalidKeyError):
        sqlite_provider.verify("nonexistent-key")


def test_consume_quota_reduces_quota(sqlite_provider: AuthProvider) -> None:
    ctx = sqlite_provider.verify("test-key-123")
    sqlite_provider.consume_quota(ctx, 200)
    # Verify the quota persisted in the backend.
    refreshed = sqlite_provider.verify("test-key-123")
    assert refreshed.quota == 800


def test_consume_quota_exceeds_limit_raises(sqlite_provider: AuthProvider) -> None:
    ctx = sqlite_provider.verify("test-key-123")
    with pytest.raises(QuotaExceededError):
        sqlite_provider.consume_quota(ctx, 2000)


def test_multiple_consumptions_accumulate(sqlite_provider: AuthProvider) -> None:
    ctx = sqlite_provider.verify("test-key-123")
    sqlite_provider.consume_quota(ctx, 300)
    ctx = sqlite_provider.verify("test-key-123")
    sqlite_provider.consume_quota(ctx, 400)
    refreshed = sqlite_provider.verify("test-key-123")
    assert refreshed.quota == 300


def test_quota_is_isolated_between_keys(sqlite_provider: AuthProvider) -> None:
    # Add a second key with a different quota.
    conn = sqlite3.connect(sqlite_provider._db_path)  # type: ignore[attr-defined]
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO api_keys (api_key, owner_id, quota)
        VALUES (?, ?, ?)
        """,
        ("second-key", "owner-99", 500),
    )
    conn.commit()
    conn.close()

    ctx1 = sqlite_provider.verify("test-key-123")
    ctx2 = sqlite_provider.verify("second-key")
    sqlite_provider.consume_quota(ctx1, 100)
    sqlite_provider.consume_quota(ctx2, 200)

    refreshed1 = sqlite_provider.verify("test-key-123")
    refreshed2 = sqlite_provider.verify("second-key")
    assert refreshed1.quota == 900
    assert refreshed2.quota == 300

def test_consume_quota_updates_context_instance(sqlite_provider: AuthProvider) -> None:
    ctx = sqlite_provider.verify("test-key-123")
    sqlite_provider.consume_quota(ctx, 150)
    # The original AuthContext instance should reflect the new quota.
    assert ctx.quota == 850
    # A fresh context should match the same value.
    fresh = sqlite_provider.verify("test-key-123")
    assert fresh.quota == 850