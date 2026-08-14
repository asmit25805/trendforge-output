import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import pytest

from src.core.models import AggregatedReport, TokenRecord
from src.core.aggregator import CostAggregator

# Helper to create a TokenRecord with given parameters
def make_record(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
) -> TokenRecord:
    total = prompt_tokens + completion_tokens
    return TokenRecord(
        timestamp=datetime.now(timezone.utc),
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total,
    )


def test_aggregator_initial_state() -> None:
    """A fresh aggregator should produce a zeroed report."""
    agg = CostAggregator()
    report: AggregatedReport = agg.finalize()
    assert report.total_tokens == 0
    assert report.total_cost_usd == 0.0
    assert report.provider_totals == {}
    assert report.model_totals == {}
    assert isinstance(report.run_id, str)


def test_aggregator_single_record() -> None:
    """Adding a single record must be reflected in the final report."""
    agg = CostAggregator()
    record = make_record("dummy", "model-a", 5, 3)
    agg.add_record(record)
    report = agg.finalize()
    assert report.total_tokens == 8
    assert report.provider_totals == {"dummy": 8}
    assert report.model_totals == {"model-a": 8}
    # Cost is calculated from the pricing table; ensure it is a float
    assert isinstance(report.total_cost_usd, float)


def test_aggregator_multiple_records_same_provider_model() -> None:
    """Multiple records sharing provider and model must be summed correctly."""
    agg = CostAggregator()
    records = [
        make_record("provider-x", "model-1", 10, 5),
        make_record("provider-x", "model-1", 7, 2),
        make_record("provider-x", "model-1", 3, 4),
    ]
    for rec in records:
        agg.add_record(rec)
    report = agg.finalize()
    expected_total = sum(r.total_tokens for r in records)
    assert report.total_tokens == expected_total
    assert report.provider_totals == {"provider-x": expected_total}
    assert report.model_totals == {"model-1": expected_total}


def test_aggregator_multiple_providers_and_models() -> None:
    """Aggregator must keep distinct totals per provider and per model."""
    agg = CostAggregator()
    records = [
        make_record("prov-a", "model-1", 4, 1),
        make_record("prov-a", "model-2", 2, 2),
        make_record("prov-b", "model-1", 3, 3),
        make_record("prov-b", "model-3", 5, 0),
    ]
    for rec in records:
        agg.add_record(rec)
    report = agg.finalize()
    # Provider totals
    assert report.provider_totals == {
        "prov-a": 9,  # (4+1)+(2+2)=9
        "prov-b": 11,  # (3+3)+(5+0)=11
    }
    # Model totals
    assert report.model_totals == {
        "model-1": 11,  # 5 + 6
        "model-2": 4,
        "model-3": 5,
    }
    assert report.total_tokens == 20


def test_aggregator_cost_computation_with_mocked_pricing(monkeypatch) -> None:
    """
    By injecting a known pricing table, verify that total_cost_usd equals
    sum(total_tokens * price_per_token) for all records.
    """
    # Mock a simple pricing table where each token costs $0.0001
    mock_pricing = {"model-x": 0.0001, "model-y": 0.0002}
    import src.core.aggregator as agg_mod

    monkeypatch.setattr(agg_mod, "_PRICING_TABLE", mock_pricing, raising=False)

    agg = CostAggregator()
    records = [
        make_record("p1", "model-x", 10, 5),  # 15 tokens * 0.0001
        make_record("p2", "model-y", 3, 7),   # 10 tokens * 0.0002
        make_record("p1", "model-x", 2, 3),   # 5 tokens * 0.0001
    ]
    for rec in records:
        agg.add_record(rec)
    report = agg.finalize()

    expected_cost = (
        15 * 0.0001 + 10 * 0.0002 + 5 * 0.0001
    )  # sum of token * price
    assert abs(report.total_cost_usd - expected_cost) < 1e-9
    # Ensure provider and model totals still match token counts
    assert report.provider_totals == {"p1": 20, "p2": 10}
    assert report.model_totals == {"model-x": 20, "model-y": 10}


def test_aggregator_finalize_is_idempotent() -> None:
    """Calling finalize repeatedly without new records should return identical reports."""
    agg = CostAggregator()
    records = [
        make_record("prov", "model", 1, 1),
        make_record("prov", "model", 2, 3),
    ]
    for rec in records:
        agg.add_record(rec)
    first = agg.finalize()
    second = agg.finalize()
    assert first == second
    # Mutating the returned report should not affect subsequent calls
    first.provider_totals["prov"] = 999
    third = agg.finalize()
    assert third.provider_totals["prov"] == 6  # original sum (1+1+2+3)


def test_aggregator_add_after_finalize_updates_report(monkeypatch) -> None:
    """
    After a finalize call, adding more records must be reflected in the next
    report while the previous report remains unchanged.
    """
    # Use a deterministic pricing table for cost verification
    mock_pricing = {"model-a": 0.001}
    import src.core.aggregator as agg_mod

    monkeypatch.setattr(agg_mod, "_PRICING_TABLE", mock_pricing, raising=False)

    agg = CostAggregator()
    rec1 = make_record("prov", "model-a", 5, 5)  # 10 tokens
    agg.add_record(rec1)
    first_report = agg.finalize()
    assert first_report.total_tokens == 10
    assert abs(first_report.total_cost_usd - 0.01) < 1e-9

    # Add another record after finalization
    rec2 = make_record("prov", "model-a", 2, 3)  # 5 tokens
    agg.add_record(rec2)
    second_report = agg.finalize()
    assert second_report.total_tokens == 15
    assert abs(second_report.total_cost_usd - 0.015) < 1e-9
    # Ensure the first report stayed unchanged
    assert first_report.total_tokens == 10
    assert abs(first_report.total_cost_usd - 0.01) < 1e-9