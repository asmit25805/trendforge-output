import logging
from typing import Any, Dict, List, Mapping, Optional

import httpx
from pydantic import BaseModel, Field, ValidationError, validator
from sanic import Sanic, response
from sanic.exceptions import SanicException, InvalidUsage, ServerError

from src.core.aggregator import ResultAggregator
from src.core.fetcher import AsyncFetcher
from src.core.models import ApiResponse, AggregatedResult, ErrorDetail, MetadataItem, SubRequest
from src.core.splitter import RequestSplitter
from src.middleware.error_handler import register_error_handler

logger = logging.getLogger(__name__)


class MetadataQuery(BaseModel):
    """Schema for the ``/metadata`` POST payload."""

    query: str = Field(..., description="Search term or identifier")
    filters: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Optional filters; currently only ``tags`` is supported",
    )
    limit: int = Field(
        10,
        ge=1,
        le=100,
        description="Maximum number of items to return (1‑100)",
    )
    offset: int = Field(
        0,
        ge=0,
        description="Zero‑based offset for pagination",
    )

    @validator("filters")
    def _validate_filters(cls, v: Mapping[str, Any]) -> Mapping[str, Any]:
        if "tags" in v:
            tags = v["tags"]
            if not isinstance(tags, list):
                raise ValueError("filters.tags must be a list")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("each tag must be a string")
                if len(tag) > 30:
                    raise ValueError("tag length must not exceed 30 characters")
        return v


def _format_validation_error(err: ValidationError) -> Dict[str, Any]:
    """Convert a pydantic ValidationError into the API error payload."""
    issues = [
        {
            "loc": ".".join(map(str, e["loc"])),
            "msg": e["msg"],
            "type": e["type"],
        }
        for e in err.errors()
    ]
    return {"code": "invalid_payload", "issues": issues}


async def _handle_metadata(request: Any) -> response.HTTPResponse:
    """
    Process a client query, split it into sub‑requests, fetch data concurrently,
    aggregate the results and return a JSON payload.
    """
    try:
        payload = request.json
        if not isinstance(payload, dict):
            raise InvalidUsage("JSON body must be an object")
        query = MetadataQuery(**payload)
    except ValidationError as ve:
        logger.warning("Payload validation failed: %s", ve)
        error_body = _format_validation_error(ve)
        return response.json(error_body, status=400)

    splitter = RequestSplitter()
    try:
        sub_requests: List[SubRequest] = splitter.split(payload)
    except ValueError as ve:
        logger.warning("Splitter error: %s", ve)
        return response.json(
            {"code": "invalid_payload", "issues": [{"msg": str(ve)}]}, status=400
        )

    fetcher = AsyncFetcher()
    try:
        api_responses: List[ApiResponse] = await fetcher.fetch_all(sub_requests)
    except httpx.HTTPError as he:
        logger.exception("Network error during fetch: %s", he)
        return response.json(
            {"code": "internal_error", "message": "Upstream communication failed"},
            status=500,
        )

    aggregator = ResultAggregator()
    aggregated: AggregatedResult = aggregator.aggregate(api_responses)

    # Apply pagination based on limit/offset from the original query
    start = query.offset
    end = start + query.limit
    paginated_items = aggregated.results[start:end]

    response_body = {
        "partial_success": aggregated.partial_success,
        "results": [item.dict() for item in paginated_items],
    }
    if aggregated.errors:
        response_body["errors"] = [e.dict() for e in aggregated.errors]

    return response.json(response_body, status=200)


def _health_check(request: Any) -> response.HTTPResponse:
    """Simple health‑check endpoint used by orchestrators."""
    return response.json({"status": "ok"})


def register_routes(app: Sanic) -> None:
    """
    Register all API routes on the provided Sanic application instance.
    This includes the health‑check endpoint and the ``/metadata`` POST endpoint.
    """
    # Register middleware for unified error handling
    register_error_handler(app)

    # Health‑check (GET)
    app.add_route(_health_check, "/health", methods=["GET"])

    # Metadata aggregation (POST)
    app.add_route(_handle_metadata, "/metadata", methods=["POST"])

    # Enable CORS for all origins – can be tightened later via config
    @app.middleware("request")
    async def _cors_middleware(request):
        request.ctx.cors = True

    @app.middleware("response")
    async def _cors_response_middleware(request, resp):
        if getattr(request.ctx, "cors", False):
            resp.headers["Access-Control-Allow-Origin"] = "*"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization"
        return resp

    logger.info("Routes registered: /health (GET), /metadata (POST)")