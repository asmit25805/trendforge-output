from __future__ import annotations

import asyncio
import json
import sys
import uuid
from typing import Any, List, Mapping, Optional

import httpx
import structlog
from pydantic import BaseSettings, Field, ValidationError

from src.core.gateway import A2AGateway, GatewaySettings
from src.core.models import (
    A2AMessage,
    A2AResponse,
    Incident,
    PriorityLevel,
    RemediationAction,
    ResponseStatus,
)

log = structlog.get_logger(__name__)


class ExampleSettings(BaseSettings):
    """
    Configuration for the example usage script.
    """

    incident_agent_endpoint: str = Field(
        "http://localhost:8001/handle",
        description="HTTP endpoint of the incident agent",
    )
    policy_engine_endpoint: str = Field(
        "http://localhost:8002/handle",
        description="HTTP endpoint of the policy engine",
    )
    healing_agent_endpoint: str = Field(
        "http://localhost:8003/handle",
        description="HTTP endpoint of the healing agent",
    )
    request_timeout: float = Field(
        5.0,
        description="Timeout in seconds for all outbound HTTP calls",
    )
    max_retries: int = Field(
        3,
        description="Maximum number of retries for transient failures",
    )
    base_backoff: float = Field(
        0.2,
        description="Base back‑off interval in seconds before jitter is applied",
    )

    class Config:
        env_prefix = "EXAMPLE_"


settings = ExampleSettings()


def _jittered_backoff(attempt: int) -> float:
    """
    Compute exponential back‑off with jitter for the given retry attempt.
    """
    base = settings.base_backoff * (2 ** attempt)
    jitter = (base * 0.1) * (uuid.uuid4().int % 10) / 10.0
    return base + jitter


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    json_payload: Mapping[str, Any],
) -> httpx.Response:
    """
    Perform an HTTP POST with retry/back‑off handling.
    """
    attempt = 0
    while attempt <= settings.max_retries:
        try:
            response = await client.post(url, json=json_payload, timeout=settings.request_timeout)
            response.raise_for_status()
            return response
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and 400 <= exc.response.status_code < 500:
                log.error(
                    "non_retryable_http_error",
                    url=url,
                    status_code=exc.response.status_code,
                    error=str(exc),
                )
                raise
            if attempt == settings.max_retries:
                log.error(
                    "max_retries_exceeded",
                    url=url,
                    error=str(exc),
                )
                raise
            backoff = _jittered_backoff(attempt)
            log.warning(
                "transient_http_error_retry",
                url=url,
                attempt=attempt,
                backoff=backoff,
                error=str(exc),
            )
            await asyncio.sleep(backoff)
            attempt += 1
    # Should never reach here
    raise RuntimeError("Retry loop exited unexpectedly")


async def post_incident(gateway: A2AGateway, incident: Incident) -> A2AResponse:
    """
    Wrap an Incident in an A2AMessage and send it to the incident agent.
    """
    message = A2AMessage(
        id=str(uuid.uuid4()),
        source_agent="example_client",
        target_agent="incident_agent",
        task_type="incident.create",
        payload=incident.model_dump(),
        priority=PriorityLevel.MEDIUM,
        correlation_id=None,
    )
    response = await gateway.send(message)
    if response.status != ResponseStatus.ACCEPTED:
        log.error(
            "incident_post_failed",
            incident_id=incident.incident_id,
            status=response.status,
            error=response.error,
        )
        raise RuntimeError(f"Failed to post incident: {response.error}")
    log.info("incident_posted", incident_id=incident.incident_id, response_id=response.id)
    return response


async def fetch_plan(gateway: A2AGateway, request_id: str) -> List[RemediationAction]:
    """
    Retrieve the remediation plan for a previously posted incident.
    """
    # In a real deployment the policy engine would push the plan back via A2A.
    # For the example we poll the policy endpoint directly.
    async with httpx.AsyncClient() as client:
        url = f"{settings.policy_engine_endpoint}/plan/{request_id}"
        resp = await _post_with_retry(client, url, {})
        data = resp.json()
        actions_raw = data.get("actions", [])
        actions: List[RemediationAction] = []
        for act in actions_raw:
            try:
                actions.append(RemediationAction(**act))
            except ValidationError as ve:
                log.error(
                    "invalid_action_payload",
                    raw=act,
                    validation_error=str(ve),
                )
                continue
        log.info("plan_fetched", request_id=request_id, action_count=len(actions))
        return actions


async def execute_actions(gateway: A2AGateway, actions: List[RemediationAction]) -> List[A2AResponse]:
    """
    Send each RemediationAction to the healing agent for execution.
    """
    responses: List[A2AResponse] = []
    for action in actions:
        message = A2AMessage(
            id=str(uuid.uuid4()),
            source_agent="example_client",
            target_agent="healing_agent",
            task_type="remediation.execute",
            payload=action.model_dump(),
            priority=PriorityLevel.HIGH if action.human_approved is False else PriorityLevel.MEDIUM,
            correlation_id=None,
        )
        try:
            resp = await gateway.send(message)
            responses.append(resp)
            log.info(
                "action_dispatched",
                action_id=action.action_id,
                response_status=resp.status,
            )
        except Exception as exc:
            log.error(
                "action_dispatch_failed",
                action_id=action.action_id,
                error=str(exc),
            )
            # Continue with remaining actions
    return responses


async def run_example_flow() -> None:
    """
    Orchestrates the full end‑to‑end example: incident → plan → healing.
    """
    # Initialise the gateway with a short timeout for the demo
    gw_settings = GatewaySettings(
        timeout=settings.request_timeout,
        max_retries=settings.max_retries,
        base_backoff=settings.base_backoff,
    )
    gateway = A2AGateway(settings=gw_settings)

    # Register static endpoints – in production these could be discovered dynamically
    gateway.register_agent("incident_agent", settings.incident_agent_endpoint)
    gateway.register_agent("policy_engine", settings.policy_engine_endpoint)
    gateway.register_agent("healing_agent", settings.healing_agent_endpoint)

    # Create a synthetic incident
    incident = Incident(
        incident_id=f"INC-{uuid.uuid4()}",
        title="Example high‑severity outage",
        severity="P0",
        cloud="aws",
        service="web-api",
        metadata={"region": "us-east-1"},
    )

    # Step 1: post the incident
    try:
        post_resp = await post_incident(gateway, incident)
    except Exception as exc:
        log.critical("failed_to_post_incident", error=str(exc))
        sys.exit(1)

    # Step 2: fetch the remediation plan
    try:
        plan_actions = await fetch_plan(gateway, post_resp.id)
        if not plan_actions:
            log.warning("empty_plan_received", request_id=post_resp.id)
            return
    except Exception as exc:
        log.critical("failed_to_fetch_plan", error=str(exc))
        sys.exit(1)

    # Step 3: execute the actions via HealingAgent
    exec_responses = await execute_actions(gateway, plan_actions)

    # Summarise results
    success = sum(1 for r in exec_responses if r.status == ResponseStatus.COMPLETED)
    failed = len(exec_responses) - success
    log.info(
        "execution_summary",
        total=len(exec_responses),
        succeeded=success,
        failed=failed,
    )


if __name__ == "__main__":
    asyncio.run(run_example_flow())