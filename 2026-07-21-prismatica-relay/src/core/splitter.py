import logging
from typing import Any, Dict, List, Mapping, MutableMapping

from pydantic import BaseModel, HttpUrl, ValidationError, validator

from src.core.models import SubRequest

logger = logging.getLogger(__name__)


class _ClientQuery(BaseModel):
    """Internal representation of the client payload sent to ``/metadata``."""

    query: str
    filters: Mapping[str, Any] = {}
    limit: int = 10

    @validator("limit")
    def _positive_limit(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("limit must be a positive integer")
        return v

    @validator("filters")
    def _validate_filters(cls, v: Mapping[str, Any]) -> Mapping[str, Any]:
        # Only ``tags`` filter is currently supported.
        if not isinstance(v, Mapping):
            raise ValueError("filters must be a mapping")
        if "tags" in v:
            tags = v["tags"]
            if not isinstance(tags, list):
                raise ValueError("filters.tags must be a list of strings")
            for tag in tags:
                if not isinstance(tag, str):
                    raise ValueError("each tag must be a string")
                if len(tag) > 30:
                    raise ValueError("tag length must not exceed 30 characters")
        return v


class RequestSplitter:
    """
    Divides a high‑level client query into independent ``SubRequest`` objects.
    """

    #: Mapping from tag prefix to upstream endpoint. In a real deployment this
    #: would be loaded from configuration or service discovery.
    _TAG_ENDPOINT_MAP: Mapping[str, HttpUrl] = {
        "science": HttpUrl("https://upstream-a.example.com/metadata"),
        "technology": HttpUrl("https://upstream-b.example.com/metadata"),
        "health": HttpUrl("https://upstream-c.example.com/metadata"),
    }

    def __init__(self, default_timeout_ms: int = 2000) -> None:
        """
        Initialise the splitter.

        Args:
            default_timeout_ms: Per‑request timeout used when the client payload
                does not specify a custom timeout.
        """
        if default_timeout_ms <= 0:
            raise ValueError("default_timeout_ms must be positive")
        self._default_timeout_ms = default_timeout_ms
        logger.debug("RequestSplitter initialised with timeout %d ms", default_timeout_ms)

    def split(self, query: Dict[str, Any]) -> List[SubRequest]:
        """
        Validate the incoming payload and produce a list of ``SubRequest`` objects.

        The method extracts the ``tags`` filter (if present) and creates one
        sub‑request per distinct upstream endpoint. If no tags are supplied,
        a single generic request is emitted.

        Args:
            query: Raw JSON payload from the client.

        Returns:
            A list of validated ``SubRequest`` instances ready for fetching.

        Raises:
            ValueError: If the payload fails validation or cannot be mapped to
                upstream endpoints.
        """
        logger.debug("Splitting client query: %s", query)
        try:
            client_query = _ClientQuery(**query)
        except ValidationError as exc:
            logger.error("Client payload validation failed: %s", exc)
            raise ValueError(
                {"code": "invalid_payload", "details": exc.errors()}
            ) from exc

        tags: List[str] = list(client_query.filters.get("tags", []))
        logger.debug("Extracted tags: %s", tags)

        # Determine which endpoints to hit based on tags.
        endpoint_to_params: MutableMapping[HttpUrl, Dict[str, Any]] = {}
        if tags:
            for tag in tags:
                endpoint = self._resolve_endpoint(tag)
                if endpoint not in endpoint_to_params:
                    endpoint_to_params[endpoint] = {"tags": []}
                endpoint_to_params[endpoint]["tags"].append(tag)
        else:
            # No tags – use a default endpoint (first entry in the map).
            default_endpoint = next(iter(self._TAG_ENDPOINT_MAP.values()))
            endpoint_to_params[default_endpoint] = {}

        sub_requests: List[SubRequest] = []
        for endpoint, params in endpoint_to_params.items():
            sub = SubRequest(
                endpoint=endpoint,
                params=params,
                timeout_ms=self._default_timeout_ms,
            )
            if not self.validate_subrequest(sub):
                logger.error("Generated sub‑request failed validation: %s", sub)
                raise ValueError(
                    {"code": "invalid_payload", "details": "sub‑request validation failed"}
                )
            sub_requests.append(sub)
            logger.debug("Created SubRequest: %s", sub)

        logger.info("Generated %d sub‑requests from client query", len(sub_requests))
        return sub_requests

    def validate_subrequest(self, sub: SubRequest) -> bool:
        """
        Ensure a ``SubRequest`` conforms to the upstream schema.

        Checks performed:
        * ``endpoint`` must be a valid HTTP(S) URL.
        * ``timeout_ms`` must be a positive integer.
        * ``params`` must be a JSON‑serialisable mapping.

        Args:
            sub: The sub‑request to validate.

        Returns:
            ``True`` if the sub‑request passes all checks, ``False`` otherwise.
        """
        try:
            # ``endpoint`` is already typed as ``HttpUrl`` by Pydantic; re‑validate
            # to guard against accidental mutation.
            HttpUrl.validate(sub.endpoint)  # type: ignore[attr-defined]
        except ValidationError as exc:
            logger.warning("Invalid endpoint in SubRequest %s: %s", sub, exc)
            return False

        if not isinstance(sub.timeout_ms, int) or sub.timeout_ms <= 0:
            logger.warning("Invalid timeout_ms in SubRequest %s", sub)
            return False

        if not isinstance(sub.params, Mapping):
            logger.warning("params must be a mapping in SubRequest %s", sub)
            return False

        # Ensure params are JSON‑serialisable by attempting a round‑trip.
        try:
            import json

            json.dumps(sub.params)
        except (TypeError, ValueError) as exc:
            logger.warning("params not JSON‑serialisable in SubRequest %s: %s", sub, exc)
            return False

        return True

    def _resolve_endpoint(self, tag: str) -> HttpUrl:
        """
        Resolve a tag to an upstream endpoint using the internal mapping.

        The resolution is case‑insensitive and falls back to the first endpoint
        if no specific mapping exists.

        Args:
            tag: The tag extracted from the client payload.

        Returns:
            The ``HttpUrl`` of the upstream service responsible for the tag.
        """
        tag_lower = tag.lower()
        for prefix, endpoint in self._TAG_ENDPOINT_MAP.items():
            if tag_lower.startswith(prefix):
                logger.debug("Tag '%s' resolved to endpoint %s", tag, endpoint)
                return endpoint
        fallback = next(iter(self._TAG_ENDPOINT_MAP.values()))
        logger.debug(
            "Tag '%s' has no explicit mapping; using fallback endpoint %s", tag, fallback
        )
        return fallback