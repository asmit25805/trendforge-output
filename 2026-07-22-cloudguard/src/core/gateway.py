from __future__ import annotations

import asyncio
import random
from typing import Dict, Optional

import httpx
import structlog
from pydantic import BaseSettings, Field, PositiveInt, PositiveFloat

from src.core.models import (
    A2AMessage,
    A2AResponse,
    PriorityLevel,
    ResponseStatus,
)

log = structlog.get_logger(__name__)


class GatewaySettings(BaseSettings):
    """Configuration for the A2A gateway."""

    timeout: PositiveFloat = Field(
        10.0,
        description="HTTP timeout in seconds for each request",
    )
    max_retries: PositiveInt = Field(
        3,
        description="Maximum number of retry attempts for transient failures",
    )
    base_backoff: PositiveFloat = Field(
        0.5,
        description="Base back‑off interval in seconds before applying jitter",
    )

    class Config:
        env_prefix = "A2A_GATEWAY_"


class A2AGateway:
    """
    Routes typed A2A messages between independent agents and maintains a dynamic
    registry of endpoints.
    """

    def __init__(self, settings: Optional[GatewaySettings] = None) -> None:
        self._registry: Dict[str, str] = {}
        self.settings = settings or GatewaySettings()
        self._client = httpx.AsyncClient(timeout=self.settings.timeout)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def register_agent(self, name: str, endpoint: str) -> None:
        """
        Add a new agent at runtime.

        Args:
            name: Logical name of the target agent.
            endpoint: HTTP endpoint that receives A2AMessage payloads.
        """
        self._registry[name] = endpoint
        log.info("registered_agent", name=name, endpoint=endpoint)

    def resolve_endpoint(self, target_agent: str) -> Optional[str]:
        """
        Look up the HTTP endpoint for a given agent.

        Args:
            target_agent: Name of the agent to resolve.

        Returns:
            The endpoint URL if registered, otherwise ``None``.
        """
        endpoint = self._registry.get(target_agent)
        if endpoint is None:
            log.warning("endpoint_not_found", target_agent=target_agent)
        return endpoint

    async def send(self, message: A2AMessage) -> A2AResponse:
        """
        Asynchronously dispatch a message to its target agent with retry/back‑off.

        Args:
            message: The A2AMessage to be sent.

        Returns:
            An ``A2AResponse`` reflecting success or failure.
        """
        endpoint = self.resolve_endpoint(message.target_agent)
        if endpoint is None:
            return self._build_failed_response(
                message,
                error=f"Target agent '{message.target_agent}' not registered",
            )

        payload = message.model_dump()
        attempt = 0
        while attempt <= self.settings.max_retries:
            try:
                log.debug(
                    "gateway_send_attempt",
                    attempt=attempt,
                    endpoint=endpoint,
                    message_id=message.id,
                )
                response = await self._client.post(endpoint, json=payload)
                if 200 <= response.status_code < 300:
                    # Successful HTTP response – deserialize into A2AResponse
                    resp_data = response.json()
                    a2a_resp = A2AResponse(**resp_data)
                    log.info(
                        "gateway_send_success",
                        attempt=attempt,
                        endpoint=endpoint,
                        message_id=message.id,
                        status=a2a_resp.status,
                    )
                    return a2a_resp
                if 400 <= response.status_code < 500:
                    # Permanent client error – do not retry
                    error_msg = (
                        f"Client error {response.status_code}: {response.text}"
                    )
                    log.error(
                        "gateway_client_error",
                        endpoint=endpoint,
                        status_code=response.status_code,
                        error=error_msg,
                    )
                    return self._build_failed_response(message, error=error_msg)
                # For 5xx errors we fall through to retry logic
                log.warning(
                    "gateway_server_error",
                    endpoint=endpoint,
                    status_code=response.status_code,
                    attempt=attempt,
                )
                raise httpx.HTTPStatusError(
                    f"Server error {response.status_code}", request=response.request, response=response
                )
            except (httpx.RequestError, httpx.HTTPStatusError) as exc:
                if attempt == self.settings.max_retries:
                    error_msg = f"Exceeded retries: {exc}"
                    log.error(
                        "gateway_final_failure",
                        endpoint=endpoint,
                        attempt=attempt,
                        error=error_msg,
                    )
                    return self._build_failed_response(message, error=error_msg)
                backoff = self._compute_backoff(attempt)
                log.info(
                    "gateway_retry",
                    endpoint=endpoint,
                    attempt=attempt,
                    backoff=backoff,
                    error=str(exc),
                )
                await asyncio.sleep(backoff)
                attempt += 1

        # Should never reach here; defensive fallback
        return self._build_failed_response(
            message,
            error="Unexpected gateway state after retries",
        )

    def _compute_backoff(self, attempt: int) -> float:
        """
        Compute exponential back‑off with jitter.

        Args:
            attempt: Current retry attempt number (0‑based).

        Returns:
            Back‑off duration in seconds.
        """
        jitter = random.uniform(0, self.settings.base_backoff)
        backoff = self.settings.base_backoff * (2 ** attempt) + jitter
        return backoff

    def _build_failed_response(self, message: A2AMessage, error: str) -> A2AResponse:
        """
        Construct a failed ``A2AResponse`` mirroring the request.

        Args:
            message: Original request message.
            error: Human‑readable error description.

        Returns:
            An ``A2AResponse`` with status ``failed``.
        """
        resp = A2AResponse(
            id=message.id,
            source_agent="gateway",
            target_agent=message.source_agent,
            status="failed",  # type: ignore[assignment]
            result=None,
            error=error,
        )
        log.debug(
            "gateway_response_failure",
            request_id=message.id,
            error=error,
        )
        return resp