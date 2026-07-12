import json
import logging
from dataclasses import dataclass, asdict, field
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence, Union

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# --------------------------------------------------------------------------- #
# Data models used across the project
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class NodeInfo:
    """Information about a worker node.

    Attributes
    ----------
    node_id: str
        Unique identifier for the node.
    capacity: int
        Maximum number of concurrent jobs the node can handle.
    current_load: int = 0
        Number of jobs currently being processed.
    """

    node_id: str
    capacity: int
    current_load: int = 0

    def is_available(self) -> bool:
        """Return ``True`` if the node can accept another job."""
        return self.current_load < self.capacity

    def increment_load(self) -> "NodeInfo":
        """Return a new ``NodeInfo`` with ``current_load`` increased by one.
        ``NodeInfo`` is immutable, so a new instance is returned.
        """
        return NodeInfo(
            node_id=self.node_id,
            capacity=self.capacity,
            current_load=self.current_load + 1,
        )

    def decrement_load(self) -> "NodeInfo":
        """Return a new ``NodeInfo`` with ``current_load`` decreased by one."""
        new_load = max(self.current_load - 1, 0)
        return NodeInfo(
            node_id=self.node_id,
            capacity=self.capacity,
            current_load=new_load,
        )


@dataclass(frozen=True)
class JobRequest:
    """A request sent by a client to be processed by a worker node.

    Attributes
    ----------
    request_id: str
        Unique identifier for the request.
    payload: Mapping[str, Any]
        Arbitrary JSON‑compatible payload that the worker will process.
    """

    request_id: str
    payload: Mapping[str, Any]

    def to_json(self) -> str:
        return json.dumps({"request_id": self.request_id, "payload": self.payload})


@dataclass(frozen=True)
class JobResult:
    """Result returned by a worker node after processing a ``JobRequest``.

    Attributes
    ----------
    request_id: str
        Identifier of the original request.
    result: Mapping[str, Any]
        JSON‑compatible result data.
    """

    request_id: str
    result: Mapping[str, Any]

    def to_json(self) -> str:
        return json.dumps({"request_id": self.request_id, "result": self.result})


@dataclass(frozen=True)
class AuthContext:
    """Authentication context returned after a successful API‑key validation.

    Attributes
    ----------
    api_key: str
        The validated API key.
    quota_remaining: int
        Number of tokens remaining for the key.
    """

    api_key: str
    quota_remaining: int
