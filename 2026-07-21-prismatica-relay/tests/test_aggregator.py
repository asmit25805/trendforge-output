import pytest
from typing import List

from src.core.aggregator import ResultAggregator, AggregatedResult
from src.core.models import ApiResponse, MetadataItem, ErrorDetail


@pytest.fixture
def aggregator() -> ResultAggregator:
    """Provide a fresh ResultAggregator for each test."""
    return ResultAggregator()


def _make_item(item_id: str, title: str, source: str) -> MetadataItem:
    return MetadataItem(
        id=item_id,
        title=title,
        tags=["test"],
        thumbnail_url="https://example.org/thumb.png",
        source=source,
    )


def _make_success_response(items: List[MetadataItem]) -> ApiResponse:
    return ApiResponse(status=200, payload=items, error=None)


def _make_error_response(
    status: int, code: str, message: str, retryable: bool
) -> ApiResponse:
    return ApiResponse(
        status=status,
        payload=[],
        error=ErrorDetail(code=code, message=message, retryable=retryable),
    )


def test_aggregate_combines_successful_payloads(aggregator: ResultAggregator) -> None:
    """Aggregating two successful responses yields the union of their items."""
    resp1 = _make_success_response([_make_item("1", "Alpha", "srcA")])
    resp2 = _make_success_response([_make_item("2", "Beta", "srcB")])
    result: AggregatedResult = aggregator.aggregate([resp1, resp2])

    assert isinstance(result, AggregatedResult)
    assert len(result.items) == 2
    ids = {item.id for item in result.items}
    assert ids == {"1", "2"}
    assert result.partial_success is False
    assert result.errors == []


def test_aggregate_deduplicates_items(aggregator: ResultAggregator) -> None:
    """Duplicate items (same id and source) are collapsed to a single entry."""
    dup = _make_item("dup", "Duplicate", "srcX")
    resp1 = _make_success_response([dup])
    resp2 = _make_success_response([dup])
    result = aggregator.aggregate([resp1, resp2])

    assert len(result.items) == 1
    assert result.items[0].id == "dup"
    assert result.items[0].source == "srcX"
    assert result.partial_success is False


def test_aggregate_partial_success_with_retryable_error(aggregator: ResultAggregator) -> None:
    """When a retryable error occurs, other successful items are kept and partial_success is True."""
    good = _make_success_response([_make_item("good", "Good Item", "srcY")])
    bad = _make_error_response(
        status=502,
        code="upstream_timeout",
        message="Upstream timed out",
        retryable=True,
    )
    result = aggregator.aggregate([good, bad])

    assert len(result.items) == 1
    assert result.items[0].id == "good"
    assert result.partial_success is True
    assert len(result.errors) == 1
    assert result.errors[0].code == "upstream_timeout"
    assert result.errors[0].retryable is True


def test_aggregate_non_retryable_error_is_dropped(aggregator: ResultAggregator) -> None:
    """Non‑retryable errors are omitted from the final payload but still trigger partial_success."""
    good = _make_success_response([_make_item("keep", "Keep Me", "srcZ")])
    bad = _make_error_response(
        status=404,
        code="not_found",
        message="Resource not found",
        retryable=False,
    )
    result = aggregator.aggregate([good, bad])

    assert len(result.items) == 1
    assert result.items[0].id == "keep"
    assert result.partial_success is True
    # Non‑retryable errors are not exposed to the client
    assert result.errors == []


def test_deduplicate_preserves_original_order(aggregator: ResultAggregator) -> None:
    """deduplicate should keep the first occurrence of each item and retain order."""
    items = [
        _make_item("a", "First", "src1"),
        _make_item("b", "Second", "src2"),
        _make_item("a", "First Duplicate", "src1"),
        _make_item("c", "Third", "src3"),
    ]
    deduped = aggregator.deduplicate(items)

    assert len(deduped) == 3
    assert [item.id for item in deduped] == ["a", "b", "c"]
    # The first occurrence of "a" is kept
    assert deduped[0].title == "First"


def test_aggregate_multiple_errors_mixed_retryable_and_not(aggregator: ResultAggregator) -> None:
    """Mixed error types result in partial_success with only retryable errors reported."""
    success = _make_success_response([_make_item("ok", "OK", "srcM")])
    retryable_err = _make_error_response(
        status=503,
        code="service_unavailable",
        message="Service temporarily unavailable",
        retryable=True,
    )
    non_retryable_err = _make_error_response(
        status=400,
        code="bad_request",
        message="Invalid query parameter",
        retryable=False,
    )
    result = aggregator.aggregate([success, retryable_err, non_retryable_err])

    assert len(result.items) == 1
    assert result.items[0].id == "ok"
    assert result.partial_success is True
    assert len(result.errors) == 1
    assert result.errors[0].code == "service_unavailable"
    assert result.errors[0].retryable is True