from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from typing import Dict, Set

from pydantic import BaseModel, Field, validator

from src.utils.logger import logger

_ETH_ADDRESS_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")


def _validate_eth_address(value: str) -> str:
    """Validate that a string looks like an Ethereum address."""
    if not _ETH_ADDRESS_REGEX.fullmatch(value):
        raise ValueError(f"Invalid Ethereum address: {value}")
    return value.lower()


class _RouterEntry(BaseModel):
    """Internal representation of a router entry for persistence."""

    chain_id: int = Field(..., ge=1, description="EVM chain identifier")
    router: str = Field(..., description="Router contract address")

    @validator("router")
    def check_router(cls, v: str) -> str:
        return _validate_eth_address(v)


class WhitelistManager:
    """
    Maintains immutable whitelists for routers, tokens, and chain IDs.
    All modifications are persisted to a JSON file to survive restarts.
    """

    _DEFAULT_STORAGE = Path("whitelist.json")

    def __init__(self, storage_path: str | os.PathLike | None = None) -> None:
        """
        Initialise the manager, loading persisted data if present.
        """
        self._storage_path: Path = Path(storage_path) if storage_path else self._DEFAULT_STORAGE
        self._routers: Dict[int, Set[str]] = {}
        self._tokens: Set[str] = set()
        self._chains: Set[int] = set()
        self._lock = asyncio.Lock()
        self._load_from_disk()

    # --------------------------------------------------------------------- #
    # Persistence helpers
    # --------------------------------------------------------------------- #
    def _load_from_disk(self) -> None:
        """Load whitelist data from the JSON file; start empty on failure."""
        if not self._storage_path.is_file():
            logger.debug("whitelist.load", msg="no existing file, starting fresh")
            return
        try:
            with self._storage_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
            for entry in raw.get("routers", []):
                model = _RouterEntry(**entry)
                self._routers.setdefault(model.chain_id, set()).add(model.router)
                self._chains.add(model.chain_id)
            for token in raw.get("tokens", []):
                self._tokens.add(_validate_eth_address(token))
            for chain in raw.get("chains", []):
                self._chains.add(int(chain))
            logger.debug("whitelist.load", msg="data loaded", path=str(self._storage_path))
        except Exception as exc:  # pragma: no cover
            logger.error("whitelist.load_error", error=str(exc))
            # Corrupted file – start with empty state to avoid blocking the engine.
            self._routers.clear()
            self._tokens.clear()
            self._chains.clear()

    def _dump_to_disk(self) -> None:
        """Serialise current whitelist state to the JSON file."""
        data = {
            "routers": [
                {"chain_id": cid, "router": r}
                for cid, routers in self._routers.items()
                for r in routers
            ],
            "tokens": list(self._tokens),
            "chains": list(self._chains),
        }
        try:
            with self._storage_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, sort_keys=True)
            logger.debug("whitelist.dump", msg="data persisted", path=str(self._storage_path))
        except Exception as exc:  # pragma: no cover
            logger.error("whitelist.dump_error", error=str(exc))

    # --------------------------------------------------------------------- #
    # Public API – router management
    # --------------------------------------------------------------------- #
    async def add_router(self, chain_id: int, router: str) -> None:
        """
        Validate and store a router address for a given chain.
        """
        async with self._lock:
            router = _validate_eth_address(router)
            if chain_id < 1:
                raise ValueError("chain_id must be a positive integer")
            routers = self._routers.setdefault(chain_id, set())
            if router in routers:
                raise ValueError(f"Router {router} already whitelisted for chain {chain_id}")
            routers.add(router)
            self._chains.add(chain_id)
            self._dump_to_disk()
            logger.info("whitelist.add_router", chain_id=chain_id, router=router)

    async def remove_router(self, chain_id: int, router: str) -> None:
        """
        Remove a router from the whitelist; raises if not present.
        """
        async with self._lock:
            router = _validate_eth_address(router)
            routers = self._routers.get(chain_id)
            if not routers or router not in routers:
                raise ValueError(f"Router {router} not found for chain {chain_id}")
            routers.remove(router)
            if not routers:
                del self._routers[chain_id]
                # If no routers remain for the chain, also drop the chain entry.
                self._chains.discard(chain_id)
            self._dump_to_disk()
            logger.info("whitelist.remove_router", chain_id=chain_id, router=router)

    # --------------------------------------------------------------------- #
    # Public API – token management (optional but useful)
    # --------------------------------------------------------------------- #
    async def add_token(self, token: str) -> None:
        """
        Add a token address to the global token whitelist.
        """
        async with self._lock:
            token = _validate_eth_address(token)
            if token in self._tokens:
                raise ValueError(f"Token {token} already whitelisted")
            self._tokens.add(token)
            self._dump_to_disk()
            logger.info("whitelist.add_token", token=token)

    async def remove_token(self, token: str) -> None:
        """
        Remove a token address from the whitelist.
        """
        async with self._lock:
            token = _validate_eth_address(token)
            if token not in self._tokens:
                raise ValueError(f"Token {token} not found in whitelist")
            self._tokens.remove(token)
            self._dump_to_disk()
            logger.info("whitelist.remove_token", token=token)

    # --------------------------------------------------------------------- #
    # Public API – chain management (optional)
    # --------------------------------------------------------------------- #
    async def add_chain(self, chain_id: int) -> None:
        """
        Explicitly whitelist a chain identifier.
        """
        async with self._lock:
            if chain_id < 1:
                raise ValueError("chain_id must be a positive integer")
            if chain_id in self._chains:
                raise ValueError(f"Chain {chain_id} already whitelisted")
            self._chains.add(chain_id)
            self._dump_to_disk()
            logger.info("whitelist.add_chain", chain_id=chain_id)

    async def remove_chain(self, chain_id: int) -> None:
        """
        Remove a chain from the whitelist; also clears any routers attached.
        """
        async with self._lock:
            if chain_id not in self._chains:
                raise ValueError(f"Chain {chain_id} not found in whitelist")
            self._chains.remove(chain_id)
            self._routers.pop(chain_id, None)
            self._dump_to_disk()
            logger.info("whitelist.remove_chain", chain_id=chain_id)

    # --------------------------------------------------------------------- #
    # Query API
    # --------------------------------------------------------------------- #
    async def is_allowed(self, chain_id: int, router: str, token: str) -> bool:
        """
        Return True if the router and token are permitted on the given chain.
        """
        async with self._lock:
            router = _validate_eth_address(router)
            token = _validate_eth_address(token)
            chain_ok = chain_id in self._chains
            router_ok = router in self._routers.get(chain_id, set())
            token_ok = token in self._tokens
            allowed = chain_ok and router_ok and token_ok
            logger.debug(
                "whitelist.check",
                chain_id=chain_id,
                router=router,
                token=token,
                allowed=allowed,
            )
            return allowed

    # --------------------------------------------------------------------- #
    # Introspection helpers (useful for tests and diagnostics)
    # --------------------------------------------------------------------- #
    async def list_routers(self) -> Dict[int, Set[str]]:
        """Return a copy of the router whitelist mapping."""
        async with self._lock:
            return {cid: routers.copy() for cid, routers in self._routers.items()}

    async def list_tokens(self) -> Set[str]:
        """Return a copy of the token whitelist."""
        async with self._lock:
            return self._tokens.copy()

    async def list_chains(self) -> Set[int]:
        """Return a copy of the chain whitelist."""
        async with self._lock:
            return self._chains.copy()