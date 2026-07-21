import pytest
from pydantic import ValidationError

from src.core.splitter import RequestSplitter
from src.core.models import SubRequest, MetadataItem, ErrorDetail


@pytest.fixture
def splitter() -> RequestSplitter:
    """Provide a fresh RequestSplitter instance for each test."""
    return RequestSplitter()


def test_splitter_returns_subrequest_instances(splitter: RequestSplitter) -> None:
    """A valid query should produce a list of SubRequest objects."""
    query = {
        "targets": [
            {
                "endpoint": "https://api.example.org/v1/items",
                "params": {"category": "books"},
                "timeout_ms": 1500,
            },
            {
                "endpoint": "https://api.example.org/v1/articles",
                "params": {"tag": "science"},
            },
        ]
    }
    result = splitter.split(query)
    assert isinstance(result, list)
    assert all(isinstance(r, SubRequest) for r in result)
    assert len(result) == 2


def test_splitter_invalid_query_raises_validation_error(splitter: RequestSplitter) -> None:
    """Missing required fields should raise a pydantic ValidationError."""
    # ``targets`` key is missing entirely
    invalid_query = {"foo": "bar"}
    with pytest.raises(ValidationError):
        splitter.split(invalid_query)


def test_splitter_multiple_sources_yield_correct_count(splitter: RequestSplitter) -> None:
    """When the query contains N targets, N SubRequest objects must be returned."""
    query = {
        "targets": [
            {"endpoint": "https://upstream1.test/api", "params": {}},
            {"endpoint": "https://upstream2.test/api", "params": {}},
            {"endpoint": "https://upstream3.test/api", "params": {}},
        ]
    }
    sub_requests = splitter.split(query)
    assert len(sub_requests) == 3
    endpoints = {sr.endpoint for sr in sub_requests}
    expected = {
        "https://upstream1.test/api",
        "https://upstream2.test/api",
        "https://upstream3.test/api",
    }
    assert endpoints == expected


def test_splitter_preserves_params_per_subrequest(splitter: RequestSplitter) -> None:
    """Each SubRequest must retain the exact params dict supplied for its target."""
    query = {
        "targets": [
            {"endpoint": "https://svc.test/a", "params": {"q": "alpha"}},
            {"endpoint": "https://svc.test/b", "params": {"q": "beta", "page": 2}},
        ]
    }
    sub_requests = splitter.split(query)
    assert sub_requests[0].params == {"q": "alpha"}
    assert sub_requests[1].params == {"q": "beta", "page": 2}


def test_splitter_default_timeout_is_applied(splitter: RequestSplitter) -> None:
    """If ``timeout_ms`` is omitted, the default of 2000 ms must be set."""
    query = {
        "targets": [
            {"endpoint": "https://svc.test/default", "params": {}},
        ]
    }
    sub_requests = splitter.split(query)
    assert sub_requests[0].timeout_ms == 2000


def test_validate_subrequest_accepts_valid_object(splitter: RequestSplitter) -> None:
    """The ``validate_subrequest`` method should return True for a well‑formed SubRequest."""
    sub = SubRequest(
        endpoint="https://valid.test/api",
        params={"key": "value"},
        timeout_ms=2500,
    )
    assert splitter.validate_subrequest(sub) is True


def test_validate_subrequest_rejects_invalid_endpoint(splitter: RequestSplitter) -> None:
    """A SubRequest with a malformed endpoint must raise a ValidationError."""
    with pytest.raises(ValidationError):
        SubRequest(endpoint="not-a-url", params={}, timeout_ms=1000)


def test_validate_subrequest_rejects_negative_timeout(splitter: RequestSplitter) -> None:
    """Negative timeout values are not allowed and should trigger validation failure."""
    with pytest.raises(ValidationError):
        SubRequest(endpoint="https://valid.test/api", params={}, timeout_ms=-10)