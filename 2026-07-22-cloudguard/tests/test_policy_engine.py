import asyncio
import pathlib
import json
from typing import Any, Dict, List

import httpx
import pytest
import yaml
from pydantic import ValidationError

from src.core.models import (
    A2AMessage,
    A2AResponse,
    Incident,
    PolicyRule,
    RemediationAction,
    PriorityLevel,
    ResponseStatus,
)
from src.core.policy_engine import PolicyEngine, PolicyEngineSettings


class MockAsyncClient:
    """Async HTTP client mock that records POST calls and can simulate failures."""

    def __init__(self) -> None:
        self.posts: List[Dict[str, Any]] = []
        self._failures: List[Exception] = []

    def queue_failure(self, exc: Exception) -> None:
        """Queue an exception to be raised on the next request."""
        self._failures.append(exc)

    async def post(self, url: str, json: Dict[str, Any]) -> httpx.Response:
        if self._failures:
            raise self._failures.pop(0)
        self.posts.append({"url": url, "json": json})
        # Return a minimal successful response
        return httpx.Response(200, json={})

    async def aclose(self) -> None:
        """No‑op close method to satisfy the gateway cleanup contract."""
        return None


@pytest.fixture
def rule_file(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary YAML rule file with three distinct rules."""
    rules = [
        {
            "rule_id": "r_high",
            "condition": {"severity": "P0", "cloud": "aws"},
            "actions": [
                {
                    "action_id": "a1",
                    "action_type": "scale",
                    "target": {"namespace": "default", "workload_name": "svc", "cloud": "aws"},
                    "parameters": {"replicas": 3},
                    "dry_run": True,
                    "human_approved": False,
                }
            ],
            "priority": "high",
        },
        {
            "rule_id": "r_medium",
            "condition": {"severity": "P0"},
            "actions": [
                {
                    "action_id": "a2",
                    "action_type": "restart",
                    "target": {"namespace": "default", "workload_name": "svc", "cloud": "aws"},
                    "parameters": {},
                    "dry_run": True,
                    "human_approved": False,
                }
            ],
            "priority": "medium",
        },
        {
            "rule_id": "r_low",
            "condition": {"severity": "P1"},
            "actions": [
                {
                    "action_id": "a3",
                    "action_type": "patch",
                    "target": {"namespace": "default", "workload_name": "svc", "cloud": "gcp"},
                    "parameters": {"version": "v2"},
                    "dry_run": True,
                    "human_approved": False,
                }
            ],
            "priority": "low",
        },
    ]
    path = tmp_path / "policy_rules.yaml"
    path.write_text(yaml.safe_dump(rules))
    return path


@pytest.fixture
def engine(rule_file: pathlib.Path) -> PolicyEngine:
    """Instantiate a PolicyEngine with a mock HTTP client."""
    settings = PolicyEngineSettings(
        rule_source=str(rule_file),
        reload_interval_seconds=0,
        audit_endpoint="http://audit.local/record",
    )
    engine = PolicyEngine(settings=settings)
    # Replace the internal async client with a mock that records calls
    engine._http_client = MockAsyncClient()  # type: ignore[attr-defined]
    return engine


@pytest.mark.asyncio
async def test_evaluate_returns_actions_when_condition_matches(engine: PolicyEngine) -> None:
    incident = Incident(
        incident_id="INC-001",
        title="Critical AWS failure",
        severity="P0",
        cloud="aws",
        service="svc",
        metadata={},
    )
    actions = await engine.evaluate(incident)
    assert isinstance(actions, list)
    assert len(actions) == 2  # high‑priority and medium‑priority rules match
    assert actions[0].action_id == "a1"
    assert actions[1].action_id == "a2"


@pytest.mark.asyncio
async def test_evaluate_returns_empty_when_no_rule_matches(engine: PolicyEngine) -> None:
    incident = Incident(
        incident_id="INC-002",
        title="Minor GCP warning",
        severity="P3",
        cloud="gcp",
        service="svc",
        metadata={},
    )
    actions = await engine.evaluate(incident)
    assert isinstance(actions, list)
    assert len(actions) == 0


@pytest.mark.asyncio
async def test_load_rules_raises_on_invalid_yaml(tmp_path: pathlib.Path) -> None:
    bad_path = tmp_path / "bad_rules.yaml"
    bad_path.write_text("::: not a yaml :::")
    settings = PolicyEngineSettings(
        rule_source=str(bad_path),
        reload_interval_seconds=0,
        audit_endpoint=None,
    )
    engine = PolicyEngine(settings=settings)
    with pytest.raises(yaml.YAMLError):
        await engine.load_rules()


@pytest.mark.asyncio
async def test_audit_log_is_sent_for_each_action(engine: PolicyEngine) -> None:
    incident = Incident(
        incident_id="INC-003",
        title="Scale request",
        severity="P0",
        cloud="aws",
        service="svc",
        metadata={},
    )
    actions = await engine.evaluate(incident)
    # Trigger audit logging for each action
    for action in actions:
        await engine.audit_log(action)

    client: MockAsyncClient = engine._http_client  # type: ignore[attr-defined]
    assert len(client.posts) == len(actions)
    for post in client.posts:
        assert post["url"] == "http://audit.local/record"
        assert "action_id" in post["json"]
        assert "incident_id" not in post["json"]  # audit payload is action‑centric


@pytest.mark.asyncio
async def test_retry_on_transient_audit_failure(engine: PolicyEngine) -> None:
    incident = Incident(
        incident_id="INC-004",
        title="Transient failure test",
        severity="P0",
        cloud="aws",
        service="svc",
        metadata={},
    )
    actions = await engine.evaluate(incident)

    client: MockAsyncClient = engine._http_client  # type: ignore[attr-defined]
    # Simulate a transient network error on the first POST, then succeed
    client.queue_failure(httpx.ConnectError("connection reset"))
    await engine.audit_log(actions[0])

    # After retry the request should have been recorded once
    assert len(client.posts) == 1
    assert client.posts[0]["url"] == "http://audit.local/record"


@pytest.mark.asyncio
async def test_policy_engine_respects_reload_interval(engine: PolicyEngine, rule_file: pathlib.Path) -> None:
    # Initial evaluation uses the original rule set
    incident = Incident(
        incident_id="INC-005",
        title="Initial evaluation",
        severity="P1",
        cloud="gcp",
        service="svc",
        metadata={},
    )
    actions_initial = await engine.evaluate(incident)
    assert len(actions_initial) == 1
    assert actions_initial[0].action_id == "a3"

    # Modify the rule file to change the low‑priority rule
    updated_rules = [
        {
            "rule_id": "r_low",
            "condition": {"severity": "P1"},
            "actions": [
                {
                    "action_id": "a3-mod",
                    "action_type": "patch",
                    "target": {"namespace": "default", "workload_name": "svc", "cloud": "gcp"},
                    "parameters": {"version": "v3"},
                    "dry_run": True,
                    "human_approved": False,
                }
            ],
            "priority": "low",
        }
    ]
    rule_file.write_text(yaml.safe_dump(updated_rules))

    # Force a reload; the engine should pick up the new rule
    await engine.load_rules()
    actions_updated = await engine.evaluate(incident)
    assert len(actions_updated) == 1
    assert actions_updated[0].action_id == "a3-mod"


@pytest.mark.asyncio
async def test_evaluate_preserves_action_order_by_priority(engine: PolicyEngine) -> None:
    incident = Incident(
        incident_id="INC-006",
        title="Priority ordering test",
        severity="P0",
        cloud="aws",
        service="svc",
        metadata={},
    )
    actions = await engine.evaluate(incident)
    # Verify that actions are sorted from highest to lowest priority
    priorities = [action.action_type for action in actions]
    # The high‑priority rule creates a 'scale' action, medium creates 'restart'
    assert priorities == ["scale", "restart"]


@pytest.mark.asyncio
async def test_evaluate_raises_on_malformed_action(engine: PolicyEngine) -> None:
    # Corrupt the rule file with an invalid action schema
    malformed_rules = [
        {
            "rule_id": "r_bad",
            "condition": {"severity": "P0"},
            "actions": [
                {
                    # Missing required fields such as action_id and action_type
                    "target": {"namespace": "default"},
                    "parameters": {},
                }
            ],
            "priority": "high",
        }
    ]
    malformed_path = pathlib.Path(engine._settings.rule_source)  # type: ignore[attr-defined]
    malformed_path.write_text(yaml.safe_dump(malformed_rules))

    with pytest.raises(ValidationError):
        await engine.load_rules()