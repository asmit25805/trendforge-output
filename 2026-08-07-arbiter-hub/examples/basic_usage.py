import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseSettings, Field, validator
from loguru import logger

from src.core.whitelist import WhitelistManager
from src.core.capital_vault import CapitalVault
from src.core.engine import ArbitrageEngine
from src.core.models import ArbOpportunity, RouterStep, ExecutionResult


class Settings(BaseSettings):
    """Configuration for the example script."""

    rpc_url: str = Field(..., description="JSON‑RPC endpoint for the EVM node.")
    private_key: str = Field(..., description="Hex‑encoded private key for the operator wallet.")
    whitelist_path: Path = Field(
        default=Path("./whitelist.json"),
        description="File path where the whitelist JSON is persisted.",
    )
    poll_interval: float = Field(
        default=5.0,
        description="Seconds to wait between engine cycles.",
    )
    max_cycles: int = Field(
        default=3,
        description="Maximum number of engine cycles to run before exiting.",
    )

    @validator("rpc_url")
    def _validate_rpc_url(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError("rpc_url must be a valid HTTP URL")
        return v

    @validator("private_key")
    def _validate_private_key(cls, v: str) -> str:
        if not v.startswith("0x") or len(v) != 66:
            raise ValueError("private_key must be a 0x‑prefixed 32‑byte hex string")
        return v


async def fetch_dummy_opportunity() -> ArbOpportunity:
    """Create a synthetic opportunity for demonstration purposes."""
    router_step = RouterStep(
        router_address="0x1111111111111111111111111111111111111111",
        fee_tier=3000,
        swap_data=b"\x00\x01",
    )
    return ArbOpportunity(
        source_chain=1,
        target_chain=1,
        router_path=[router_step],
        input_token="0x2222222222222222222222222222222222222222",
        output_token="0x3333333333333333333333333333333333333333",
        input_amount=10**18,
        estimated_profit=10**15,
    )


async def main() -> None:
    """Run a short demonstration of the arbitrage engine."""
    # Load configuration from environment variables or .env file.
    settings = Settings()  # type: ignore[arg-type]

    # Initialise logger with a simple format.
    logger.remove()
    logger.add(sys.stderr, format="{time} | {level} | {message}", level="INFO")

    # Initialise whitelist manager.
    whitelist_manager = WhitelistManager(storage_path=settings.whitelist_path)
    # Ensure the whitelist file exists.
    if not settings.whitelist_path.exists():
        settings.whitelist_path.write_text(json.dumps({}))
    # Register a router for the demo chain.
    demo_chain = 1
    demo_router = "0x1111111111111111111111111111111111111111"
    whitelist_manager.add_router(demo_chain, demo_router)

    # Initialise capital vault.
    capital_vault = CapitalVault(
        rpc_url=settings.rpc_url,
        private_key=settings.private_key,
        logger=logger,
    )

    # Initialise the arbitrage engine with collaborators.
    engine = ArbitrageEngine(
        whitelist_manager=whitelist_manager,
        capital_vault=capital_vault,
        profit_tracker=None,  # ProfitTracker can be omitted for a minimal demo.
        logger=logger,
    )

    # Patch the engine's discovery method to return a deterministic opportunity.
    async def _discover_opportunities() -> list[ArbOpportunity]:
        return [await fetch_dummy_opportunity()]

    engine._discover_opportunities = _discover_opportunities  # type: ignore[attr-defined]

    # Run a limited number of cycles.
    for cycle in range(settings.max_cycles):
        logger.info(f"--- Engine cycle {cycle + 1}/{settings.max_cycles} ---")
        try:
            await engine.run_cycle()
        except Exception as exc:  # pragma: no cover
            logger.error(f"Unexpected error during engine cycle: {exc}")
        await asyncio.sleep(settings.poll_interval)

    logger.info("Demo completed successfully.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting.")