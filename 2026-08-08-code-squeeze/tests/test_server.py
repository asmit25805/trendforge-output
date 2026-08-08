import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

from src.api.server import ProxyServer
from src.core.models import Config, CompressionResult, Segment
from src.providers.openai_client import LLMResponse, BaseLLMClient, get_client


@pytest.fixture
def temp_config_path(tmp_path: Path) -> Path:
    """Create a minimal ``config.json`` file for the server."""
    config = {
        "model": "test-model",
        "system_prompt_path": str(tmp_path / "system_prompt.txt"),
        "max_workers": 2,
        "rate_limit": 60,
        "cache_path": str(tmp_path / "cache.db"),
    }
    # write a dummy system prompt file
    (tmp_path / "system_prompt.txt").write_text(
        "You are a helpful assistant.", encoding="utf-8"
    )
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path


@pytest.fixture
def proxy_server(temp_config_path: Path) -> ProxyServer:
    """Instantiate a ``ProxyServer`` that loads the temporary config."""
    return ProxyServer(config_path=temp_config_path)


@pytest.fixture
def client(proxy_server: ProxyServer) -> TestClient:
    """FastAPI test client bound to the server's app."""
    return TestClient(proxy_server.app)


class DummyLLMClient(BaseLLMClient):
    """A deterministic LLM client used in tests."""

    def __init__(self, config: Config, responses: List[LLMResponse] | None = None):
        super().__init__(config)
        self._responses = responses or []
        self.call_count = 0

    async def call(self, model: str, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("No dummy response configured")
        return self._responses.pop(0)


def _register_dummy_client(monkeypatch, client_instance: DummyLLMClient):
    """Replace the provider registry so that ``get_client`` returns ``client_instance``."""
    monkeypatch.setattr(
        "src.providers.openai_client._client_registry",
        {"dummy": lambda cfg: client_instance},
        raising=False,
    )
    monkeypatch.setattr(
        "src.providers.openai_client.get_client",
        lambda name, cfg: client_instance,
    )


def _make_segment_payload() -> dict:
    """Return a payload dictionary matching the expected request schema."""
    return {
        "segments": [
            {
                "id": "file1:1-10",
                "intent": "refactor function",
                "code": "def foo():\n    pass\n",
                "metadata": {"path": "file1.py"},
            }
        ]
    }


def _expected_compression_result(segment: Segment, content: str) -> CompressionResult:
    """Create the ``CompressionResult`` that the server should return for ``segment``."""
    return CompressionResult(
        segment_id=segment.id,
        action="KEPT",
        compressed_code=content,
        usage={"total_tokens": 0},
        model="test-model",
        timestamp=datetime.now(timezone.utc),
    )


def test_proxy_server_successful_compression(monkeypatch, client, proxy_server):
    """A valid request should return a JSON list with the compressed result."""
    dummy_response = LLMResponse(content="compressed code", usage={"total_tokens": 5})
    dummy_client = DummyLLMClient(proxy_server.config, [dummy_response])
    _register_dummy_client(monkeypatch, dummy_client)

    payload = _make_segment_payload()
    response = client.post("/compress", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list) and len(data) == 1
    result = data[0]
    assert result["segment_id"] == "file1:1-10"
    assert result["action"] == "KEPT"
    assert result["compressed_code"] == "compressed code"
    assert result["usage"]["total_tokens"] == 5
    assert dummy_client.call_count == 1


def test_proxy_server_invalid_json(monkeypatch, client):
    """Malformed JSON must trigger a 400 response."""
    # Send a plain string instead of JSON; FastAPI will treat it as body.
    response = client.post("/compress", data="not a json")
    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


def test_proxy_server_missing_segments_field(monkeypatch, client):
    """Payload without the required ``segments`` field should be rejected."""
    response = client.post("/compress", json={})
    assert response.status_code == 400
    assert "segments" in response.json()["detail"]


def test_proxy_server_segment_schema_error(monkeypatch, client):
    """A segment missing a required attribute must cause a 400."""
    payload = {"segments": [{"id": "only-id"}]}
    response = client.post("/compress", json=payload)
    assert response.status_code == 400
    # FastAPI includes the pydantic validation error in the detail.
    assert "field required" in response.text


def test_proxy_server_cache_hit(monkeypatch, client, proxy_server):
    """When a cache entry exists the LLM client must not be called."""
    segment = Segment(
        id="file2:5-15",
        intent="optimize loop",
        code="for i in range(10):\n    print(i)\n",
        metadata={"path": "file2.py"},
    )
    signature = proxy_server.engine.lint_processor.hash_signature(
        f"{segment.intent}{segment.code}"
    )
    cached = CompressionResult(
        segment_id=segment.id,
        action="KEPT",
        compressed_code="cached result",
        usage={"total_tokens": 0},
        model=proxy_server.config.model,
        timestamp=datetime.now(timezone.utc),
    )
    proxy_server.engine.cache.set(signature, cached)

    dummy_client = DummyLLMClient(proxy_server.config, [])
    _register_dummy_client(monkeypatch, dummy_client)

    payload = {"segments": [segment.dict()]}
    response = client.post("/compress", json=payload)
    assert response.status_code == 200
    result = response.json()[0]
    assert result["compressed_code"] == "cached result"
    assert dummy_client.call_count == 0


def test_proxy_server_retry_on_transient_error(monkeypatch, client, proxy_server):
    """Transient LLM errors should be retried up to the configured limit."""
    # First two calls raise a connection error, third succeeds.
    class FlakyClient(DummyLLMClient):
        async def call(self, model: str, system_prompt: str, user_prompt: str) -> LLMResponse:
            self.call_count += 1
            if self.call_count < 3:
                raise RuntimeError("Transient failure")
            return LLMResponse(content="final output", usage={"total_tokens": 3})

    flaky = FlakyClient(proxy_server.config, [])
    _register_dummy_client(monkeypatch, flaky)

    payload = _make_segment_payload()
    response = client.post("/compress", json=payload)
    assert response.status_code == 200
    result = response.json()[0]
    assert result["compressed_code"] == "final output"
    # The client should have been called three times (2 retries + final success)
    assert flaky.call_count == 3