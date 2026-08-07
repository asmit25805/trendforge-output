import pytest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

from src.core.whitelist import WhitelistManager


@pytest.fixture
def fresh_manager() -> WhitelistManager:
    """Create a fresh WhitelistManager with an isolated storage location."""
    with TemporaryDirectory() as tmp_dir:
        storage_path = Path(tmp_dir) / "whitelist.json"
        manager = WhitelistManager(storage_path=storage_path)
        # Ensure the manager starts with an empty whitelist.
        manager._load()
        yield manager
        # Cleanup is automatic via TemporaryDirectory.


def test_add_router_registers_address(fresh_manager: WhitelistManager) -> None:
    chain_id = 1
    router = "0x1111111111111111111111111111111111111111"
    fresh_manager.add_router(chain_id, router)
    assert fresh_manager.is_allowed(chain_id, router, "0x2222222222222222222222222222222222222222")


def test_remove_router_clears_entry(fresh_manager: WhitelistManager) -> None:
    chain_id = 1
    router = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    fresh_manager.add_router(chain_id, router)
    assert fresh_manager.is_allowed(chain_id, router, "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    fresh_manager.remove_router(chain_id, router)
    assert not fresh_manager.is_allowed(chain_id, router, "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")


def test_is_allowed_unknown_chain_returns_false(fresh_manager: WhitelistManager) -> None:
    unknown_chain = 999
    router = "0x1111111111111111111111111111111111111111"
    token = "0x2222222222222222222222222222222222222222"
    assert not fresh_manager.is_allowed(unknown_chain, router, token)


def test_is_allowed_unknown_router_returns_false(fresh_manager: WhitelistManager) -> None:
    chain_id = 1
    unknown_router = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    token = "0x1111111111111111111111111111111111111111"
    fresh_manager.add_router(chain_id, "0x1111111111111111111111111111111111111111")
    assert not fresh_manager.is_allowed(chain_id, unknown_router, token)


def test_add_router_invalid_address_raises_value_error(fresh_manager: WhitelistManager) -> None:
    chain_id = 1
    invalid_router = "0x123"  # Too short to be a valid address
    with pytest.raises(ValueError):
        fresh_manager.add_router(chain_id, invalid_router)


def test_remove_router_nonexistent_does_not_raise(fresh_manager: WhitelistManager) -> None:
    chain_id = 1
    router = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
    # Removing before adding should be a no‑op, not an exception.
    fresh_manager.remove_router(chain_id, router)
    # After removal, still not allowed.
    assert not fresh_manager.is_allowed(chain_id, router, "0xcccccccccccccccccccccccccccccccccccccccc")


def test_multiple_routers_per_chain(fresh_manager: WhitelistManager) -> None:
    chain_id = 42
    routers: List[str] = [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0x3333333333333333333333333333333333333333",
    ]
    for r in routers:
        fresh_manager.add_router(chain_id, r)

    token = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    for r in routers:
        assert fresh_manager.is_allowed(chain_id, r, token)

    # Remove one router and verify the others remain allowed.
    fresh_manager.remove_router(chain_id, routers[1])
    assert not fresh_manager.is_allowed(chain_id, routers[1], token)
    assert fresh_manager.is_allowed(chain_id, routers[0], token)
    assert fresh_manager.is_allowed(chain_id, routers[2], token)