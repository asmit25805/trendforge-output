import asyncio
from typing import Any, Dict, List, Optional

import httpx
import pytest
import structlog

from src.core.gateway import A2AGateway, GatewaySettings
from src.core.models import (
    A2AMessage,
    A2AResponse,
    PriorityLevel,
    ResponseStatus,
)


# --------------------------------------------------------------------------- #
# Helper mock response objects
# --------------------------------------------------------------------------- #
class MockResponse:
    """
    Minimal mock of an httpx.Response that provides the subset of the API used
    by ``A2AGateway``. It stores a status code and optional JSON payload.
    """

    def __init__(self, status_code: int, json_data: Optional[Dict[str, Any]] = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> Dict[str, Any]:
        """Return the JSON payload supplied at construction."""
        return self._json_data

    def raise_for_status(self) -> None:
        """Raise an HTTPStatusError for 4xx/5xx responses."""
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("POST", "http://test"),
                response=httpx.Response(self.status_code),
            )


# --------------------------------------------------------------------------- #
# Helper mock client
# --------------------------------------------------------------------------- #
class MockClient:
    """
    Simple async HTTP client mock that records POST calls and returns a
    pre‑configured sequence of responses or raises exceptions. The client
    mimics the subset of the httpx.AsyncClient interface used by the gateway.
    """

    def __init__(self, responses: List[Any]) -> None:
        """
        ``responses`` is a list where each element is either a ``MockResponse``
        instance (to be returned) or an exception instance (to be raised) for the
        corresponding call.
        """
        self._responses = responses
        self._call_index = 0

    async def post(self, url: str, json: Dict[str, Any]) -> MockResponse:
        """Return the next configured response or raise the configured exception."""
        if self._call_index >= len(self._responses):
            raise RuntimeError("No more mock responses configured")
        resp = self._responses[self._call_index]
        self._call_index += 1
        if isinstance(resp, Exception):
            raise resp
        return resp

    async def aclose(self) -> None:
        """No‑op close method to satisfy the gateway cleanup contract."""
        return None


# --------------------------------------------------------------------------- #
# Pytest fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def gateway() -> A2AGateway:
    """
    Create a baseline ``A2AGateway`` instance with deterministic settings.
    Logging is silenced for test output clarity.
    """
    settings = GatewaySettings(timeout=1.0, max_retries=3, base_backoff=0.0)
    gw = A2AGateway(settings=settings)
    structlog.configure(processors=[])
    return gw


def make_message() -> A2AMessage:
    """
    Produce a canonical ``A2AMessage`` used across the test suite.
    """
    return A2AMessage(
        id="msg-123",
        source_agent="incident_agent",
        target_agent="policy_engine",
        task_type="incident.create",
        payload={"incident_id": "INC-001"},
        priority=PriorityLevel.MEDIUM,
        correlation_id=None,
    )


# --------------------------------------------------------------------------- #
# Test cases
# --------------------------------------------------------------------------- #
def test_register_and_resolve_endpoint(gateway: A2AGateway) -> None:
    """A registered agent should resolve to its configured endpoint."""
    gateway.register_agent("policy_engine", "http://policy.local/handle")
    endpoint = gateway.resolve_endpoint("policy_engine")
    assert endpoint == "http://policy.local/handle"


def test_resolve_unregistered_returns_none(gateway: A2AGateway) -> None:
    """Resolving an unknown agent must return ``None``."""
    endpoint = gateway.resolve_endpoint("nonexistent_agent")
    assert endpoint is None


@pytest.mark.asyncio
async def test_send_successful_response(gateway: A2AGateway) -> None:
    """
    ``A2AGateway.send`` should deserialize a successful 200 response into an
    ``A2AResponse`` instance with the appropriate fields populated.
    """
    gateway.register_agent("policy_engine", "http://policy.local/handle")
    mock_resp = MockResponse(
        200,
        {
            "id": "msg-123",
            "source_agent": "policy_engine",
            "target_agent": "incident_agent",
            "status": "completed",
            "result": {"actions": []},
            "error": None,
        },
    )
    gateway._client = MockClient([mock_resp])  # type: ignore[attr-defined]

    response: A2AResponse = await gateway.send(make_message())
    assert isinstance(response, A2AResponse)
    assert response.id == "msg-123"
    assert response.source_agent == "policy_engine"
    assert response.target_agent == "incident_agent"
    assert response.status == ResponseStatus.COMPLETED
    assert response.result == {"actions": []}
    assert response.error is None


@pytest.mark.asyncio
async def test_send_retries_on_transient_error(gateway: A2AGateway) -> None:
    """
    Transient network errors (e.g., ``ConnectError``) should trigger a retry
    according to the gateway's ``max_retries`` setting.
    """
    gateway.register_agent("policy_engine", "http://policy.local/handle")
    transient_error = httpx.ConnectError("connection failed")
    success_resp = MockResponse(
        200,
        {
            "id": "msg-123",
            "source_agent": "policy_engine",
            "target_agent": "incident_agent",
            "status": "completed",
            "result": {"actions": []},
            "error": None,
        },
    )
    gateway._client = MockClient([transient_error, success_resp])  # type: ignore[attr-defined]

    response: A2AResponse = await gateway.send(make_message())
    assert response.status == ResponseStatus.COMPLETED
    # Verify that both mock responses were consumed, indicating a retry occurred.
    assert gateway._client._call_index == 2  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_send_fails_on_permanent_client_error(gateway: A2AGateway) -> None:
    """
    HTTP 4xx errors are considered permanent; the gateway should not retry and
    should return a failed ``A2AResponse`` containing the error details.
    """
    gateway.register_agent("policy_engine", "http://policy.local/handle")
    client_error = MockResponse(404, {"detail": "not found"})
    gateway._client = MockClient([client_error])  # type: ignore[attr-defined]

    response: A2AResponse = await gateway.send(make_message())
    assert response.status == ResponseStatus.FAILED
    assert isinstance(response.error, str)
    assert "404" in response.error


@pytest.mark.asyncio
async def test_send_raises_when_endpoint_missing(gateway: A2AGateway) -> None:
    """
    If the target agent has not been registered, ``send`` must raise a clear
    ``RuntimeError`` indicating the missing endpoint.
    """
    with pytest.raises(RuntimeError, match="endpoint for target_agent"):
        await gateway.send(make_message())


@pytest.mark.asyncio
async def test_send_respects_max_retries_and_returns_failure(gateway: A2AGateway) -> None:
    """
    When the number of transient failures exceeds ``max_retries``, the gateway
    should return a failed ``A2AResponse`` and include a message about the
    retry limit being exceeded.
    """
    gateway.register_agent("policy_engine", "http://policy.local/handle")
    errors = [httpx.ConnectError("tmp fail") for _ in range(4)]
    gateway._client = MockClient(errors)  # type: ignore[attr-defined]

    response: A2AResponse = await gateway.send(make_message())
    assert response.status == ResponseStatus.FAILED
    assert isinstance(response.error, str)
    assert "exceeded" in response.error.lower()
    # Ensure the client was called max_retries + 1 times (initial attempt + retries)
    assert gateway._client._call_index == 4  # type: ignore[attr-defined]