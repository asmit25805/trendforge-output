import asyncio
from datetime import datetime, timedelta
from typing import List

import pytest
from unittest.mock import AsyncMock, MagicMock, call

from src.core.engine import ArbitrageEngine
from src.core.models import ArbOpportunity, ExecutionResult, RouterStep
from src.core.whitelist import WhitelistManager
from src.core.profit_tracker import ProfitTracker
from src.core.capital_vault import CapitalVault


@pytest.fixture
def dummy_router_step() -> RouterStep:
    return RouterStep(
        router_address="0x1111111111111111111111111111111111111111",
        fee_tier=3000,
        swap_data=b"\x00\x01",
    )


@pytest.fixture
def dummy_opportunity(dummy_router_step: RouterStep) -> ArbOpportunity:
    return ArbOpportunity(
        source_chain=1,
        target_chain=1,
        router_path=[dummy_router_step],
        input_token="0x2222222222222222222222222222222222222222",
        output_token="0x3333333333333333333333333333333333333333",
        input_amount=10**18,
        estimated_profit=10**15,
    )


@pytest.fixture
def mock_whitelist_manager() -> WhitelistManager:
    manager = MagicMock(spec=WhitelistManager)
    manager.is_allowed.return_value = True
    return manager


@pytest.fixture
def mock_capital_vault() -> CapitalVault:
    vault = MagicMock(spec=CapitalVault)
    vault.approve.return_value = "0xapprovehash"
    vault.deposit.return_value = "0xdeposithash"
    vault.withdraw.return_value = "0xwithdrawhash"
    return vault


@pytest.fixture
def mock_profit_tracker() -> ProfitTracker:
    tracker = MagicMock(spec=ProfitTracker)
    tracker.record.return_value = None
    return tracker


@pytest.fixture
def engine(
    mock_whitelist_manager: WhitelistManager,
    mock_capital_vault: CapitalVault,
    mock_profit_tracker: ProfitTracker,
) -> ArbitrageEngine:
    # Assume ArbitrageEngine accepts its collaborators via keyword arguments.
    return ArbitrageEngine(
        whitelist_manager=mock_whitelist_manager,
        capital_vault=mock_capital_vault,
        profit_tracker=mock_profit_tracker,
    )


@pytest.mark.asyncio
async def test_engine_runs_cycle_successful(
    engine: ArbitrageEngine,
    dummy_opportunity: ArbOpportunity,
    mock_whitelist_manager: WhitelistManager,
    mock_capital_vault: CapitalVault,
    mock_profit_tracker: ProfitTracker,
):
    """Successful flow: opportunity passes whitelist, executes, profit recorded."""
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])
    engine.execute = AsyncMock(
        return_value=ExecutionResult(
            tx_hash="0xtxhash",
            success=True,
            actual_profit=10**15,
            gas_used=21000,
        )
    )

    await engine.run_cycle()

    # Whitelist should be consulted once per router step
    assert mock_whitelist_manager.is_allowed.call_count == len(dummy_opportunity.router_path)
    # Execution should be called once
    engine.execute.assert_awaited_once_with(dummy_opportunity)
    # Profit tracker should record the result
    mock_profit_tracker.record.assert_called_once()


@pytest.mark.asyncio
async def test_engine_skips_invalid_opportunity(
    engine: ArbitrageEngine,
    dummy_opportunity: ArbOpportunity,
    mock_whitelist_manager: WhitelistManager,
):
    """Opportunity rejected by whitelist should be discarded without execution."""
    mock_whitelist_manager.is_allowed.return_value = False
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])
    engine.execute = AsyncMock()

    await engine.run_cycle()

    mock_whitelist_manager.is_allowed.assert_called()
    engine.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_engine_retries_on_transient_network_error(
    engine: ArbitrageEngine,
    dummy_opportunity: ArbOpportunity,
):
    """Transient RPC error triggers retry logic up to three attempts."""
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])

    # Simulate a transient failure on first two calls, then success
    side_effects = [
        Exception("RPC timeout"),
        Exception("RPC timeout"),
        ExecutionResult(
            tx_hash="0xtxhash",
            success=True,
            actual_profit=10**15,
            gas_used=21000,
        ),
    ]
    engine.execute = AsyncMock(side_effect=side_effects)

    await engine.run_cycle()

    # execute should have been called three times (2 retries + final success)
    assert engine.execute.await_count == 3
    # After success, profit should be recorded once
    engine.profit_tracker.record.assert_called_once()


@pytest.mark.asyncio
async def test_engine_handles_persistent_network_failure(
    engine: ArbitraryEngine,
    dummy_opportunity: ArbOpportunity,
):
    """Persistent network failure after retries causes the engine to skip the block."""
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])
    engine.execute = AsyncMock(side_effect=Exception("Permanent RPC failure"))

    await engine.run_cycle()

    # execute should be attempted max_retries + 1 times (default 3 retries)
    assert engine.execute.await_count == 4
    # No profit should be recorded
    engine.profit_tracker.record.assert_not_called()


@pytest.mark.asyncio
async def test_engine_records_failed_transaction_as_loss(
    engine: ArbitrageEngine,
    dummy_opportunity: ArbOpportunity,
):
    """When a transaction reverts, the result is recorded with success=False."""
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])
    engine.execute = AsyncMock(
        return_value=ExecutionResult(
            tx_hash="0xfailedhash",
            success=False,
            actual_profit=0,
            gas_used=21000,
        )
    )

    await engine.run_cycle()

    engine.execute.assert_awaited_once()
    engine.profit_tracker.record.assert_called_once()
    recorded_result = engine.profit_tracker.record.call_args[0][0]
    assert isinstance(recorded_result, ExecutionResult)
    assert not recorded_result.success
    assert recorded_result.actual_profit == 0


@pytest.mark.asyncio
async def test_engine_graceful_stop_during_long_running_cycle(
    engine: ArbitrageEngine,
    dummy_opportunity: ArbOpportunity,
):
    """Calling stop() should cause the next run_cycle to exit early."""
    engine._discover_opportunities = AsyncMock(return_value=[dummy_opportunity])
    # Simulate a long-running execution that checks the stop flag periodically
    async def long_execution(_: ArbOpportunity) -> ExecutionResult:
        for _ in range(5):
            if engine._stop_requested:
                raise asyncio.CancelledError()
            await asyncio.sleep(0.01)
        return ExecutionResult(
            tx_hash="0xhash",
            success=True,
            actual_profit=10**15,
            gas_used=21000,
        )
    engine.execute = AsyncMock(side_effect=long_execution)

    # Request stop before running the cycle
    engine.stop()
    with pytest.raises(asyncio.CancelledError):
        await engine.run_cycle()

    # Ensure no profit was recorded because execution was cancelled
    engine.profit_tracker.record.assert_not_called()