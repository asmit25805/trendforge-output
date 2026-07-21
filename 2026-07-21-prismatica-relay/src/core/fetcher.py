import asyncio
import logging
from typing import Any, List, Mapping, Optional

import httpx
from pydantic import ValidationError

from src.core.models import ApiResponse, ErrorDetail, MetadataItem, SubRequest

logger = logging.getLogger(__name__)


class AsyncFetcher:
    """
    Performs concurrent HTTP calls for a collection of ``SubRequest`` objects,
    applying per‑request timeouts and translating upstream responses into
    ``ApiResponse`` instances.
    """

    def __init__(self, max_concurrency: int = 10, client: Optional[httpx.AsyncClient] = None) -> None:
        """
        Initialise the fetcher.

        Args:
            max_concurrency: Upper bound for simultaneous outbound requests.
            client: Optional pre‑configured ``httpx.AsyncClient``. If omitted a new
                client is created for each fetch operation.
        """
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be a positive integer")
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._external_client = client
        logger.debug("AsyncFetcher created with max_concurrency=%d", max_concurrency)

    async def fetch(self, sub_requests: List[SubRequest]) -> List[ApiResponse]:
        """
        Execute all sub‑requests concurrently and return a list of ``ApiResponse`` objects.

        The method respects the ``timeout_ms`` attribute of each ``SubRequest`` and
        ensures that no more than ``max_concurrency`` requests are in flight at any
        time.

        Args:
            sub_requests: List of ``SubRequest`` instances to be fetched.

        Returns:
            A list of ``ApiResponse`` objects preserving the order of ``sub_requests``.
        """
        async with self._client_context() as client:
            tasks = [
                self._bounded_fetch(client, sub_req)
                for sub_req in sub_requests
            ]
            responses = await asyncio.gather(*tasks, return_exceptions=False)
            return responses

    async def _bounded_fetch(self, client: httpx.AsyncClient, sub_req: SubRequest) -> ApiResponse:
        """
        Acquire the semaphore, perform a single request, then release the semaphore.

        Args:
            client: An active ``httpx.AsyncClient``.
            sub_req: The ``SubRequest`` describing the target endpoint and parameters.

        Returns:
            An ``ApiResponse`` representing the outcome of the HTTP call.
        """
        async with self._semaphore:
            return await self._fetch_one(client, sub_req)

    async def _fetch_one(self, client: httpx.AsyncClient, sub_req: SubRequest) -> ApiResponse:
        """
        Perform a single HTTP GET request based on ``sub_req`` and translate the
        result into an ``ApiResponse``.

        Args:
            client: An active ``httpx.AsyncClient``.
            sub_req: The request descriptor.

        Returns:
            An ``ApiResponse`` containing either a payload of ``MetadataItem`` objects
            or an ``ErrorDetail`` describing the failure.
        """
        timeout_seconds = sub_req.timeout_ms / 1000.0 if sub_req.timeout_ms else 2.0
        timeout = httpx.Timeout(timeout_seconds, read=timeout_seconds, write=timeout_seconds, connect=timeout_seconds)

        try:
            logger.debug(
                "Fetching %s with params=%s timeout=%.2fs",
                sub_req.endpoint,
                sub_req.params,
                timeout_seconds,
            )
            response = await client.get(
                url=str(sub_req.endpoint),
                params=sub_req.params,
                timeout=timeout,
            )
        except httpx.RequestError as exc:
            logger.error("Network error while contacting %s: %s", sub_req.endpoint, exc)
            error = ErrorDetail(
                code="network_error",
                message=str(exc),
                retryable=True,
            )
            return ApiResponse(status=0, payload=[], error=error)

        if 200 <= response.status_code < 300:
            return await self._handle_successful_response(response)
        else:
            return self._handle_error_response(response)

    async def _handle_successful_response(self, response: httpx.Response) -> ApiResponse:
        """
        Parse a successful (2xx) HTTP response into a list of ``MetadataItem`` objects.

        Args:
            response: The ``httpx.Response`` object with a JSON body.

        Returns:
            An ``ApiResponse`` with ``payload`` populated and ``error`` set to ``None``.
        """
        try:
            raw_data = response.json()
        except ValueError as exc:
            logger.error("Invalid JSON from %s: %s", response.url, exc)
            error = ErrorDetail(
                code="invalid_json",
                message="Upstream returned malformed JSON",
                retryable=False,
            )
            return ApiResponse(status=response.status_code, payload=[], error=error)

        if not isinstance(raw_data, list):
            logger.error("Unexpected payload shape from %s: %s", response.url, raw_data)
            error = ErrorDetail(
                code="unexpected_payload",
                message="Expected a list of metadata items",
                retryable=False,
            )
            return ApiResponse(status=response.status_code, payload=[], error=error)

        items: List[MetadataItem] = []
        for idx, raw_item in enumerate(raw_data):
            try:
                item = MetadataItem.parse_obj(raw_item)
                items.append(item)
            except ValidationError as ve:
                logger.warning(
                    "Metadata item validation failed at index %d from %s: %s",
                    idx,
                    response.url,
                    ve,
                )
                # Skip invalid items but continue processing others.
                continue

        logger.info(
            "Fetched %d valid metadata items from %s (original %d)",
            len(items),
            response.url,
            len(raw_data),
        )
        return ApiResponse(status=response.status_code, payload=items, error=None)

    def _handle_error_response(self, response: httpx.Response) -> ApiResponse:
        """
        Convert a non‑2xx HTTP response into an ``ApiResponse`` containing an ``ErrorDetail``.

        Args:
            response: The ``httpx.Response`` object representing the error.

        Returns:
            An ``ApiResponse`` with an appropriate ``ErrorDetail``.
        """
        status = response.status_code
        retryable = status in {502, 503, 504}
        try:
            body = response.json()
            message = body.get("message") or response.text
        except ValueError:
            message = response.text or response.reason_phrase

        error = ErrorDetail(
            code=f"http_{status}",
            message=message,
            retryable=retryable,
        )
        logger.warning(
            "Upstream error %d from %s (retryable=%s): %s",
            status,
            response.url,
            retryable,
            message,
        )
        return ApiResponse(status=status, payload=[], error=error)

    async def _client_context(self) -> httpx.AsyncClient:
        """
        Provide an ``httpx.AsyncClient`` context manager. If an external client was
        supplied during construction it is yielded directly; otherwise a temporary
        client is created and closed after use.
        """
        if self._external_client is not None:
            # The external client is assumed to be managed by the caller.
            return _DummyAsyncContextManager(self._external_client)
        else:
            return httpx.AsyncClient()


class _DummyAsyncContextManager:
    """
    Wrap an existing ``httpx.AsyncClient`` so it can be used with ``async with`` without
    altering its lifecycle.
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        return self._client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # No cleanup; the caller owns the client.
        return None