# arbiter-hub

## Overview
arbiter-hub is a permissioned on‑chain capital arbitrage engine that automatically discovers and executes low‑risk cross‑router swaps across multiple EVM chains.  
It operates with on‑chain capital (no flash loans) and enforces strict router, token, and chain whitelists to protect against malicious routing. The engine continuously fetches pool reserves and oracle data, builds candidate opportunities, validates them, simulates gas costs, and executes only the most profitable trades.

## Features
- **Async‑first data collection** – uses `httpx` for parallel JSON‑RPC calls to pool contracts and price oracles.  
- **Robust retry logic** – transient network failures are retried up to three times with exponential back‑off.  
- **Whitelist enforcement** – immutable whitelists for routers, tokens, and chain IDs are managed off‑chain and persisted locally.  
- **Capital‑vault integration** – safe token approvals and balance handling through a dedicated vault contract.  
- **Profit tracking** – daily CSV reports, ROI calculations, and real‑time logging of realized profit vs. gas cost.  
- **Minimal HTTP API** – secured with HMAC, exposing only the endpoints required for bot integration.  
- **Extensible architecture** – clear separation of concerns (engine, whitelist, vault, tracker) for easy contribution.

## Installation
```bash
pip install arbiter-hub
```
The package requires Python 3.9+ and the following runtime dependencies (installed automatically):
- `httpx[http2]`
- `pydantic`
- `loguru`
- `structlog`
- `uvloop` (optional for improved event‑loop performance)

## Quickstart
The example below demonstrates a complete run of the engine for a single cycle. It assumes you have a funded vault contract and the necessary private key configured via environment variables.

```python
import asyncio
from src.core.engine import ArbitrageEngine
from src.core.whitelist import WhitelistManager
from src.utils.logger import logger
from src.core.models import ArbOpportunity

async def main() -> None:
    # Initialise logger (writes JSON lines to stdout)
    logger.info("starting arbiter-hub quickstart")

    # Build whitelist manager and add a trusted router
    wl = WhitelistManager()
    wl.add_router(chain_id=1, router="0x1111111111111111111111111111111111111111")
    wl.add_router(chain_id=137, router="0x2222222222222222222222222222222222222222")

    # Create the engine with default settings
    engine = ArbitrageEngine(whitelist=wl)

    # Run a single discovery‑execution cycle
    await engine.run_cycle()

    # Gracefully stop the engine (no background tasks remain)
    await engine.stop()

if __name__ == "__main__":
    asyncio.run(main())
```

**Expected output (truncated):**
```
2026-08-07 12:00:01.123 | INFO | starting arbiter-hub quickstart
2026-08-07 12:00:02.456 | INFO | fetched 42 pool snapshots
2026-08-07 12:00:03.789 | INFO | built 7 ArbOpportunity candidates
2026-08-07 12:00:04.012 | INFO | 3 opportunities passed whitelist validation
2026-08-07 12:00:05.345 | INFO | executed tx 0xabc123... success=True profit=0.015 ETH
2026-08-07 12:00:05.678 | INFO | daily profit recorded, ROI=2.3%
```

The script will also generate a `profit_report_2026-08-07.csv` file in the current directory containing the day's analytics.

## Architecture
```
┌──────────────────┐
│  ArbitrageEngine   │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│  WhitelistManager  │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│    CapitalVault    │
└──────────────────┘
         │          
         ▼          
┌──────────────────┐
│   ProfitTracker    │
└──────────────────┘
```

### Component Interaction
1. **ArbitrageEngine** fetches pool reserves and oracle prices via async HTTP JSON‑RPC calls.  
2. **WhitelistManager** validates each `RouterStep` against stored whitelists.  
3. **CapitalVault** supplies token approvals and executes the calldata bundle.  
4. **ProfitTracker** records the `ExecutionResult`, updates cumulative statistics, and writes daily CSV reports.  

## API Reference

### `src.core.models`
- **`ArbOpportunity`**
  ```python
  class ArbOpportunity(BaseModel):
      source_chain: int
      target_chain: int
      router_path: List[RouterStep]
      input_token: str
      output_token: str
      input_amount: int
      estimated_profit: int
  ```
  Represents a candidate arbitrage trade, including the full router path and profit estimate.

- **`RouterStep`**
  ```python
  class RouterStep(BaseModel):
      router_address: str
      fee_tier: int
      swap_data: bytes
  ```
  Encodes a single router call within an opportunity.

- **`ExecutionResult`**
  ```python
  class ExecutionResult(BaseModel):
      tx_hash: str
      success: bool
      actual_profit: int
      gas_used: int
  ```
  Returned after a transaction is sent; `success=False` indicates a revert.

- **`ProfitReport`**
  ```python
  class ProfitReport(BaseModel):
      date: date
      total_profit: int
      total_gas_cost: int
      roi: float
  ```
  Summarizes daily performance for analytics dashboards.

### `src.core.whitelist`
- **`WhitelistManager`**
  ```python
  class WhitelistManager:
      def add_router(self, chain_id: int, router: str) -> None
      def remove_router(self, chain_id: int, router: str) -> None
      def is_allowed(self, chain_id: int, router: str, token: str) -> bool
  ```
  Manages immutable whitelists; raises `ValueError` on malformed addresses.

### `src.core.engine`
- **`ArbitrageEngine`**
  ```python
  class ArbitrageEngine:
      def __init__(self, whitelist: WhitelistManager, max_concurrent_requests: int = 10) -> None
      async def run_cycle(self) -> None
      async def execute(self, opportunity: ArbOpportunity) -> ExecutionResult
      async def stop(self) -> None
  ```
  Coordinates discovery, validation, gas simulation, and execution. Handles transient RPC errors with exponential back‑off.

### `src.core.vault` *(not listed but referenced)*
- **`CapitalVault`**
  ```python
  class CapitalVault:
      async def deposit(self, token: str, amount: int) -> str
      async def withdraw(self, token: str, amount: int) -> str
      async def approve(self, token: str, spender: str, amount: int) -> str
  ```
  Wraps on‑chain vault interactions; returns transaction hashes.

### `src.core.tracker`
- **`ProfitTracker`**
  ```python
  class ProfitTracker:
      def record(self, result: ExecutionResult) -> None
      def daily_report(self) -> ProfitReport
      def export_csv(self, path: str) -> None
  ```
  Persists profit data locally in CSV format and provides ROI calculations.

### `src.utils.logger`
- **`logger`**
  ```python
  from loguru import logger
  ```
  Configured to emit JSON‑structured logs; use `logger.info`, `logger.error`, etc.

### `src.api.bot`
- **`BotAPI`**
  ```python
  class BotAPI:
      def __init__(self, secret_key: str) -> None
      async def health(self) -> dict
      async def trigger_cycle(self) -> dict
  ```
  Exposes a minimal HTTP endpoint secured with HMAC; `trigger_cycle` forces the engine to run a new discovery‑execution cycle.

## Contributing
1. **Fork** the repository on GitHub.  
2. **Create** a new branch for your feature or bug fix.  
3. **Run** the test suite locally: `pytest -q`. All tests must pass.  
4. **Commit** with clear messages describing the change.  
5. **Open** a Pull Request targeting the `main` branch. CI will automatically run linting and tests.  

Please ensure new code follows the project's style guidelines:
- Type annotations on every public function.  
- Async functions where I/O latency is involved.  
- No stub implementations; every method must contain real logic.  
- Import only from modules listed in the repository file list.  

Thank you for helping make arbiter-hub more reliable and transparent!