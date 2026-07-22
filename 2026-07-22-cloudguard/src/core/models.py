from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, ValidationError, validator

# --------------------------------------------------------------------------- #
# Enumerations for strict typing
# --------------------------------------------------------------------------- #

Severity = Literal["P0", "P1", "P2", "P3"]
CloudProvider = Literal["aws", "gcp", "azure", "onprem"]
ActionType = Literal["scale", "restart", "patch", "evict", "create"]
PriorityLevel = Literal["low", "medium", "high", "critical"]
ResponseStatus = Literal["accepted", "running", "completed", "failed"]


# --------------------------------------------------------------------------- #
# Core data models
# --------------------------------------------------------------------------- #


class Incident(BaseModel):
    """
    Represents an incoming incident that triggers the remediation workflow.
    """

    incident_id: str = Field(
        ...,
        description="Unique identifier, e.g. INC-<uuid>",
        examples=["INC-123e4567-e89b-12d3-a456-426614174000"],
    )
    title: str = Field(..., description="Short human‑readable description")
    severity: Severity = Field(..., description="Business impact tier")
    cloud: CloudProvider = Field(..., description="Source cloud environment")
    service: str = Field(..., description="Affected service name")
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary provider‑specific payload",
    )
    received_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the incident was recorded",
    )

    @validator("incident_id")
    def _validate_incident_id(cls, v: str) -> str:
        if not v.startswith("INC-"):
            raise ValueError("incident_id must start with 'INC-'")
        # Allow any suffix after the prefix; UUID validation is optional
        return v

    def model_dump_clean(self) -> Dict[str, Any]:
        """Return a JSON‑serialisable dict without private fields."""
        return self.model_dump(exclude_unset=True)


class RemediationAction(BaseModel):
    """
    Describes a single remediation step produced by the policy engine or LLM planner.
    """

    action_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID for traceability",
    )
    action_type: ActionType = Field(..., description="Supported operation type")
    target: Dict[str, Any] = Field(..., description="Target resource description")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Operation‑specific arguments",
    )
    dry_run: bool = Field(
        default=True,
        description="Whether this is a simulation",
    )
    human_approved: bool = Field(
        default=False,
        description="Required for high‑risk actions",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of action creation",
    )

    def approve(self) -> None:
        """Mark the action as approved for execution."""
        self.human_approved = True

    def as_dict(self) -> Dict[str, Any]:
        """Serialize the action for transport or logging."""
        return self.model_dump(exclude_unset=True)


class PolicyRule(BaseModel):
    """
    Declarative rule that maps incident predicates to an ordered list of actions.
    """

    rule_id: str = Field(..., description="Stable identifier for the rule")
    condition: Dict[str, Any] = Field(
        ...,
        description="Declarative match on Incident fields, e.g. {'severity': 'P0'}",
    )
    actions: List[RemediationAction] = Field(
        ...,
        description="Ordered actions to apply when condition matches",
    )
    priority: PriorityLevel = Field(
        default="low",
        description="Dispatch precedence used by the gateway",
    )
    enabled: bool = Field(
        default=True,
        description="Flag to deactivate a rule without removal",
    )

    @validator("actions")
    def _ensure_non_empty(cls, v: List[RemediationAction]) -> List[RemediationAction]:
        if not v:
            raise ValueError("PolicyRule must contain at least one action")
        return v

    def matches(self, incident: Incident) -> bool:
        """
        Evaluate the rule's condition against an Incident.
        Supports simple equality checks; complex predicates can be added later.
        """
        for key, expected in self.condition.items():
            actual = getattr(incident, key, None)
            if isinstance(expected, dict) and isinstance(actual, dict):
                # Nested dict comparison (shallow)
                for sub_key, sub_val in expected.items():
                    if actual.get(sub_key) != sub_val:
                        return False
            else:
                if actual != expected:
                    return False
        return True


class A2AMessage(BaseModel):
    """
    Typed envelope used for inter‑agent communication.
    """

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID of the message",
    )
    source_agent: str = Field(..., description="Sender name")
    target_agent: str = Field(..., description="Receiver name")
    task_type: str = Field(..., description="Semantic type, e.g. 'incident.create'")
    payload: Dict[str, Any] = Field(..., description="Opaque data payload")
    priority: PriorityLevel = Field(
        default="low",
        description="Routing hint for the gateway",
    )
    correlation_id: Optional[str] = Field(
        default=None,
        description="Cross‑message trace identifier",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the message was created",
    )

    @validator("source_agent", "target_agent", "task_type")
    def _non_empty_strings(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("field cannot be empty or whitespace")
        return v

    def as_response(
        self,
        status: ResponseStatus,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> A2AResponse:
        """
        Helper to create a matching A2AResponse for this request.
        """
        return A2AResponse(
            id=self.id,
            source_agent=self.target_agent,
            target_agent=self.source_agent,
            status=status,
            result=result,
            error=error,
        )


class A2AResponse(BaseModel):
    """
    Structured response returned by agents via the A2AGateway.
    """

    id: str = Field(..., description="Mirrors request id")
    source_agent: str = Field(..., description="Responder name")
    target_agent: str = Field(..., description="Original sender")
    status: ResponseStatus = Field(..., description="Current processing state")
    result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Success payload when status is not 'failed'",
    )
    error: Optional[str] = Field(
        default=None,
        description="Human‑readable error when status is 'failed'",
    )
    responded_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp of the response generation",
    )

    @validator("status")
    def _status_consistency(cls, v: ResponseStatus, values: Dict[str, Any]) -> ResponseStatus:
        if v == "failed" and not values.get("error"):
            raise ValueError("error must be set when status is 'failed'")
        if v != "failed" and values.get("error"):
            raise ValueError("error must be None when status is not 'failed'")
        return v

    def is_successful(self) -> bool:
        """Return True when the response indicates a non‑failed terminal state."""
        return self.status in {"accepted", "completed"}

    def as_dict(self) -> Dict[str, Any]:
        """Serialize the response for logging or transport."""
        return self.model_dump(exclude_unset=True)


# --------------------------------------------------------------------------- #
# Exported symbols for `from cloudguard.src.core.models import *`
# --------------------------------------------------------------------------- #

__all__ = [
    "Incident",
    "RemediationAction",
    "PolicyRule",
    "A2AMessage",
    "A2AResponse",
    "Severity",
    "CloudProvider",
    "ActionType",
    "PriorityLevel",
    "ResponseStatus",
]