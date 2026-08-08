import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import List

import pytest

from src.core.models import Config, CompressionResult, Segment
from src.core.engine import CacheError, CompressionEngine, CacheStore
from src.providers.openai_client import LLMResponse, BaseLLMClient, get_client


@pytest.fixture
def temp_config(tmp_path: Path) -> Config:
    system_prompt = tmp_path / "system_prompt.txt"
    system_prompt.write_text("You are a helpful assistant.", encoding="utf-8")
    cache_path = tmp_path / "cache.db"
    return Config(
        model="test-model",
        system_prompt_path=system_prompt,
        max_workers=2,
        rate_limit=60,
        cache_path=cache_path,
    )


@pytest.fixture
def engine(temp_config: Config) -> CompressionEngine:
    return CompressionEngine(temp_config)


@pytest.fixture
def dummy_segment() -> Segment:
    return Segment(
        id="file1:1-10",
        intent="refactor the function",
        code="import os\n\nx = 1\n",
        metadata={"path": "file1.py"},
    )


class DummyLLMClient(BaseLLMClient):
    def __init__(self, config: Config, responses: List[LLMResponse] | None = None):
        super().__init__(config)
        self._responses = responses or []
        self.call_count = 0

    async def call(self, model: str, system_prompt: str, user_prompt: str) -> LLMResponse:
        self.call_count += 1
        if not self._responses:
            raise RuntimeError("No dummy response configured")
        return self._responses.pop(0)


def _register_dummy_client(monkeypatch, client_instance):
    def _factory(_config):
        return client_instance

    monkeypatch.setattr(
        "src.providers.openai_client._client_registry",
        {"dummy": _factory},
        raising=False,
    )
    monkeypatch.setattr(
        "src.providers.openai_client.get_client",
        lambda name, cfg: client_instance,
    )


@pytest.mark.asyncio
async def test_engine_uses_cache_hit(monkeypatch, engine, dummy_segment):
    # Prepare a cached result
    signature = engine.lint_processor.hash_signature(
        f"{dummy_segment.intent}{dummy_segment.code}"
    )
    cached_result = CompressionResult(
        segment_id=dummy_segment.id,
        action="KEPT",
        compressed_code="cached code",
        usage={"total_tokens": 0},
        model=engine.config.model,
        timestamp=engine._now(),
    )
    engine.cache.set(signature, cached_result)

    # Ensure LLM client would raise if called
    dummy_client = DummyLLMClient(engine.config, [])
    _register_dummy_client(monkeypatch, dummy_client)

    results = await engine.compress_batch([dummy_segment])
    assert len(results) == 1
    result = results[0]
    assert result.compressed_code == "cached code"
    assert dummy_client.call_count == 0


@pytest.mark.asyncio
async def test_engine_cache_miss_calls_llm(monkeypatch, engine, dummy_segment):
    # No cache entry
    signature = engine.lint_processor.hash_signature(
        f"{dummy_segment.intent}{dummy_segment.code}"
    )
    assert engine.cache.get(signature) is None

    # Dummy LLM response
    llm_resp = LLMResponse(content="compressed version", usage={"total_tokens": 42})
    dummy_client = DummyLLMClient(engine.config, [llm_resp])
    _register_dummy_client(monkeypatch, dummy_client)

    # Monkeypatch lint to be identity
    monkeypatch.setattr(
        engine.lint_processor,
        "lint",
        lambda txt: txt,
    )

    results = await engine.compress_batch([dummy_segment])
    assert len(results) == 1
    result = results[0]
    assert result.compressed_code == "compressed version"
    assert result.usage["total_tokens"] == 42
    assert dummy_client.call_count == 1

    # Verify that the result is now cached
    cached = engine.cache.get(signature)
    assert cached is not None
    assert cached.compressed_code == "compressed version"


@pytest.mark.asyncio
async def test_engine_retry_on_transient_error(monkeypatch, engine, dummy_segment):
    # Simulate two transient failures before success
    transient_error = httpx.HTTPError("Transient network failure")
    llm_resp = LLMResponse(content="final output", usage={"total_tokens": 10})

    class FlakyClient(DummyLLMClient):
        async def call(self, model: str, system_prompt: str, user_prompt: str) -> LLMResponse:
            self.call_count += 1
            if self.call_count <= 2:
                raise transient_error
            return llm_resp

    flaky_client = FlakyClient(engine.config, [])
    _register_dummy_client(monkeypatch, flaky_client)

    # Identity lint
    monkeypatch.setattr(
        engine.lint_processor,
        "lint",
        lambda txt: txt,
    )

    results = await engine.compress_batch([dummy_segment])
    assert len(results) == 1
    result = results[0]
    assert result.compressed_code == "final output"
    # Three calls: two failures + one success
    assert flaky_client.call_count == 3


@pytest.mark.asyncio
async def test_lint_processor_transformations(monkeypatch, engine):
    raw_code = "import os\nimport sys\n\nx = 1\nx = 2\n"
    # Expected lint: remove duplicate import and collapse assignments
    # The actual implementation may vary; we assert deterministic output length
    processed = engine.lint_processor.lint(raw_code)
    assert isinstance(processed, str)
    assert len(processed) < len(raw_code)
    # Ensure hash is stable
    h1 = engine.lint_processor.hash_signature(processed)
    h2 = engine.lint_processor.hash_signature(processed)
    assert h1 == h2


@pytest.mark.asyncio
async def test_cache_error_rebuilds(monkeypatch, engine, dummy_segment):
    # Corrupt the cache by making get raise CacheError
    original_get = engine.cache.get

    def broken_get(sig):
        raise CacheError("Corrupted")

    monkeypatch.setattr(engine.cache, "get", broken_get, raising=False)

    # Dummy LLM response
    llm_resp = LLMResponse(content="recovered output", usage={"total_tokens": 5})
    dummy_client = DummyLLMClient(engine.config, [llm_resp])
    _register_dummy_client(monkeypatch, dummy_client)

    # Identity lint
    monkeypatch.setattr(
        engine.lint_processor,
        "lint",
        lambda txt: txt,
    )

    results = await engine.compress_batch([dummy_segment])
    assert len(results) == 1
    result = results[0]
    assert result.compressed_code == "recovered output"
    # After handling the error, the cache should be functional again
    signature = engine.lint_processor.hash_signature(
        f"{dummy_segment.intent}{dummy_segment.code}"
    )
    cached = engine.cache.get(signature)
    assert cached is not None
    assert cached.compressed_code == "recovered output"


def test_engine_executor_respects_max_workers(monkeypatch, engine):
    # The executor should be created with the configured max_workers
    assert isinstance(engine._executor, ThreadPoolExecutor)
    assert engine._executor._max_workers == engine.config.max_workers
    # Verify that submitting a simple task works
    future = engine._executor.submit(lambda: 1 + 1)
    assert future.result() == 2