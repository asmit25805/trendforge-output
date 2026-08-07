from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import httpx
from pydantic import BaseSettings, Field, validator

from src.core.engine import ArbitrageEngine
from src.core.models import ExecutionResult, ProfitReport
from src.utils.logger import logger


class BotAPIError(RuntimeError):
    """Raised when a request to the engine API fails irrecoverably."""


class BotAPISettings(BaseSettings):
    """
    Configuration for the BotAPI client.
    """

    base_url: str = Field(
        ...,
        description="Base URL of the engine HTTP API, e.g. http://localhost:8000",
    )
    secret_key: str = Field(
        ...,
        description="Shared secret used for HMAC authentication",
        min_length=1,
    )
    max_retries: int = Field(
        3,
        ge=1,
        description="Maximum number of retry attempts for transient HTTP errors",
    )
    backoff_factor: float = Field(
        0.5,
        gt=0.0,
        description="Base back‑off factor in seconds for exponential retry delays",
    )
    request_timeout: float = Field(
        10.0,
        gt=0.0,
        description="HTTP request timeout in seconds",
    )

    @validator("base_url")
    def _strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


class BotAPI:
    """
    High‑level client used by external bots to interact with the arbitrage engine.
    """

    def __init__(
        self,
        engine: ArbitrageEngine,
        *,
        settings: BotAPISettings | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        """
        Initialise the BotAPI with a running engine instance and optional settings.
        """
        self._engine = engine
        self._settings = settings or BotAPISettings()
        self._client = http_client or httpx.AsyncClient(
            timeout=self._settings.request_timeout
        )
        logger.debug(
            "botapi.init",
            base_url=self._settings.base_url,
            max_retries=self._settings.max_retries,
        )

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #

    def _hmac_signature(self, payload: bytes) -> str:
        """
        Compute a hex‑encoded HMAC‑SHA256 signature for the given payload.
        """
        secret = self._settings.secret_key.encode()
        signature = hmac.new(secret, payload, hashlib.sha256).hexdigest()
        logger.trace("botapi.hmac", signature=signature)
        return signature

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        retry: bool = True,
    ) -> httpx.Response:
        """
        Perform an HTTP request with automatic HMAC signing and retry logic.
        """
        url = f"{self._settings.base_url}{path}"
        payload = b""
        if json_body is not None:
            payload = json.dumps(json_body, separators=(",", ":")).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Signature": self._hmac_signature(payload),
        }

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await self._client.request(
                    method, url, content=payload, headers=headers
                )
                response.raise_for_status()
                logger.debug(
                    "botapi.request_success",
                    method=method,
                    url=url,
                    status_code=response.status_code,
                    attempt=attempt,
                )
                return response
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                logger.warning(
                    "botapi.transient_error",
                    method=method,
                    url=url,
                    error=str(exc),
                    attempt=attempt,
                )
                if not retry or attempt >= self._settings.max_retries:
                    raise BotAPIError(
                        f"Transient error after {attempt} attempts: {exc}"
                    ) from exc
                await asyncio.sleep(self._settings.backoff_factor * (2 ** (attempt - 1)))
            except httpx.HTTPStatusError as exc:
                # Non‑2xx responses are considered fatal for the client.
                logger.error(
                    "botapi.http_error",
                    method=method,
                    url=url,
                    status_code=exc.response.status_code,
                    content=exc.response.text,
                )
                raise BotAPIError(
                    f"HTTP error {exc.response.status_code}: {exc.response.text}"
                ) from exc

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    async def run_cycle(self) -> None:
        """
        Trigger a single discovery‑execution cycle on the engine.
        """
        logger.info("botapi.run_cycle_start")
        # Directly invoke the engine's coroutine to avoid network latency when
        # the client runs in the same process.  The HTTP endpoint mirrors this
        # behaviour for remote deployments.
        await self._engine.run_cycle()
        logger.info("botapi.run_cycle_complete")

    async def trigger_remote_cycle(self) -> None:
        """
        Send a POST request to the engine's `/run-cycle` endpoint.
        """
        await self._request("POST", "/run-cycle")
        logger.info("botapi.trigger_remote_cycle_success")

    async def get_daily_report(self) -> ProfitReport:
        """
        Retrieve the latest daily profit report from the engine.
        """
        response = await self._request("GET", "/daily-report")
        data = response.json()
        # Construct a ProfitReport model; pydantic will validate fields.
        report = ProfitReport(**data)  # type: ignore[arg-type]
        logger.debug("botapi.daily_report", report=report.dict())
        return report

    async def get_status(self) -> Dict[str, Any]:
        """
        Query a lightweight status endpoint exposing engine health metrics.
        """
        response = await self._request("GET", "/status")
        status = response.json()
        logger.debug("botapi.status", status=status)
        return status

    async def submit_opportunity(
        self, opportunity: ArbOpportunity
    ) -> ExecutionResult:
        """
        Submit a pre‑constructed arbitrage opportunity for immediate execution.
        """
        payload = opportunity.dict()
        response = await self._request(
            "POST", "/execute", json_body=payload, retry=False
        )
        result_data = response.json()
        result = ExecutionResult(**result_data)  # type: ignore[arg-type]
        logger.info(
            "botapi.submit_opportunity",
            tx_hash=result.tx_hash,
            success=result.success,
            profit=result.actual_profit,
        )
        return result

    async def health_check(self) -> bool:
        """
        Perform a simple health‑check request; returns True if the engine replies.
        """
        try:
            await self._request("GET", "/health")
            logger.debug("botapi.health_check_success")
            return True
        except BotAPIError:
            logger.error("botapi.health_check_failed")
            return False

    async def close(self) -> None:
        """
        Gracefully close the underlying HTTP client.
        """
        await self._client.aclose()
        logger.debug("botapi.client_closed")
```