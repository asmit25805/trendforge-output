import logging
from typing import Any, Dict, List, Mapping, Optional

from pydantic import BaseModel, Field, HttpUrl, ValidationError, validator

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    """Machine‑readable error information returned by upstream services or the API.

    Attributes
    ----------
    code: str
        A short identifier that can be used programmatically (e.g. ``timeout``,
        ``not_found``).
    message: str
        Human‑readable description of the problem.
    retryable: bool
        Indicates whether the client may safely retry the request. Transient
        HTTP errors such as 502/503/504 are marked as retryable.
    """

    code: str = Field(..., description="Machine‑readable error identifier")
    message: str = Field(..., description="Human‑readable error description")
    retryable: bool = Field(
        False,
        description="True if the error is transient and the client may retry",
    )

    @validator("code")
    def _code_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("error code must be a non‑empty string")
        return v

    @validator("message")
    def _message_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("error message must be a non‑empty string")
        return v


class MetadataItem(BaseModel):
    """A single piece of metadata returned from an upstream provider.

    Attributes
    ----------
    id: str
        Unique identifier supplied by the source.
    title: str
        Human‑readable title.
    tags: List[str]
        Classification tags; each tag is limited to 30 characters.
    thumbnail_url: HttpUrl
        Direct URL to a preview image.
    source: str
        Name of the upstream provider that produced the item.
    """

    id: str = Field(..., description="Unique identifier from the source")
    title: str = Field(..., description="Human‑readable title")
    tags: List[str] = Field(
        default_factory=list,
        description="Classification tags (max 30 characters each)",
    )
    thumbnail_url: HttpUrl = Field(..., description="URL of the preview image")
    source: str = Field(..., description="Name of the upstream provider")

    @validator("id", "title", "source")
    def _non_empty_strings(cls, v: str, field: Any) -> str:
        if not v.strip():
            raise ValueError(f"{field.name} must be a non‑empty string")
        return v

    @validator("tags", each_item=True)
    def _tag_constraints(cls, v: str) -> str:
        if not isinstance(v, str):
            raise TypeError("each tag must be a string")
        if len(v) > 30:
            raise ValueError("tag length must not exceed 30 characters")
        return v


class SubRequest(BaseModel):
    """Descriptor for a single outbound request to an upstream shard.

    Attributes
    ----------
    endpoint: HttpUrl
        Target upstream endpoint.
    params: Mapping[str, Any]
        Query parameters specific to the shard.
    timeout_ms: int
        Per‑request timeout in milliseconds; defaults to 2000 ms.
    """

    endpoint: HttpUrl = Field(..., description="Target upstream endpoint")
    params: Mapping[str, Any] = Field(
        default_factory=dict,
        description="Query parameters for the upstream request",
    )
    timeout_ms: int = Field(
        2000,
        ge=1,
        description="Per‑request timeout in milliseconds (minimum 1 ms)",
    )

    @validator("params")
    def _params_must_be_mapping(cls, v: Mapping[str, Any]) -> Mapping[str, Any]:
        if not isinstance(v, Mapping):
            raise TypeError("params must be a mapping")
        return v

    @validator("timeout_ms")
    def _timeout_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("timeout_ms must be a positive integer")
        return v


class ApiResponse(BaseModel):
    """Standardised representation of an upstream HTTP response.

    Attributes
    ----------
    status: int
        HTTP status code returned by the upstream service.
    payload: List[MetadataItem]
        List of metadata items when the request succeeded (2xx status).
    error: Optional[ErrorDetail]
        Structured error information when the upstream response is non‑2xx.
    """

    status: int = Field(..., ge=100, le=599, description="Upstream HTTP status code")
    payload: List[MetadataItem] = Field(
        default_factory=list,
        description="List of items if the upstream call succeeded",
    )
    error: Optional[ErrorDetail] = Field(
        None,
        description="Error details for non‑2xx responses",
    )

    @validator("payload", always=True)
    def _payload_allowed_only_on_success(cls, v: List[MetadataItem], values: Dict[str, Any]) -> List[MetadataItem]:
        status = values.get("status")
        if status is None:
            raise ValueError("status must be set before payload validation")
        if 200 <= status < 300:
            return v
        if v:
            raise ValueError("payload must be empty when status is not 2xx")
        return v

    @validator("error", always=True)
    def _error_allowed_only_on_failure(cls, v: Optional[ErrorDetail], values: Dict[str, Any]) -> Optional[ErrorDetail]:
        status = values.get("status")
        if status is None:
            raise ValueError("status must be set before error validation")
        if 200 <= status < 300:
            if v is not None:
                raise ValueError("error must be None for successful responses")
        else:
            if v is None:
                raise ValueError("error must be provided for non‑2xx responses")
        return v


class AggregatedResult(BaseModel):
    """Final payload returned to the client after aggregation.

    Attributes
    ----------
    items: List[MetadataItem]
        Deduplicated and ranked list of metadata items.
    errors: List[ErrorDetail]
        Errors that were not retryable and therefore surfaced to the client.
    partial_success: bool
        ``True`` when at least one sub‑request succeeded but some failed.
    """

    items: List[MetadataItem] = Field(
        default_factory=list,
        description="Aggregated list of metadata items",
    )
    errors: List[ErrorDetail] = Field(
        default_factory=list,
        description="Non‑retryable errors collected from sub‑responses",
    )
    partial_success: bool = Field(
        False,
        description="Indicates whether the result is partial due to upstream failures",
    )

    @validator("items")
    def _items_must_be_non_empty_when_success(cls, v: List[MetadataItem], values: Dict[str, Any]) -> List[MetadataItem]:
        if not v and not values.get("partial_success", False):
            raise ValueError("items must contain at least one element for a full success")
        return v

    @validator("errors", each_item=True)
    def _error_items_are_valid(cls, v: ErrorDetail) -> ErrorDetail:
        if not isinstance(v, ErrorDetail):
            raise TypeError("errors must be instances of ErrorDetail")
        return v


__all__ = [
    "ErrorDetail",
    "MetadataItem",
    "SubRequest",
    "ApiResponse",
    "AggregatedResult",
]