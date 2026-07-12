import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import AsyncIterator, Dict, List, Set

from src.auth.auth import AuthProvider, InvalidKeyError, QuotaExceededError, AuthContext
from src.core.models import JobRequest, JobResult, NodeInfo
from src.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)


class WorkerNode(ABC):
    """Abstract base class for a compute node that can execute jobs."""

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Prepare the node for execution (e.g., start subprocesses)."""
        ...

    @abstractmethod
    async def run_job(self, job: JobRequest) -> AsyncIterator[JobResult]:
        """Execute a job and stream partial results."""
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Gracefully stop the node and release resources."""
        ...

    @property
    @abstractmethod
    def node_info(self) -> NodeInfo:
        """Current status of the node."""
        ...


class Scheduler:
    """Coordinates job submission across a pool of WorkerNode instances."""

    def __init__(
        self,
        nodes: List[WorkerNode],
        auth_provider: AuthProvider,
        metrics: MetricsCollector,
    ) -> None:
        self._nodes: List[WorkerNode] = list(nodes)
        self.auth_provider: AuthProvider = auth_provider
        self.metrics: MetricsCollector = metrics

        # Track jobs that are currently running and those that have been cancelled.
        self._active_jobs: Set[str] = set()
        self._cancelled_jobs: Set[str] = set()

        # Simple lock to protect node selection and state mutation.
        self._lock = asyncio.Lock()

    def add_node(self, node: WorkerNode) -> None:
        """Add a new node to the scheduler at runtime."""
        self._nodes.append(node)

    def select_node(self) -> WorkerNode:
        """Return the node with the most free capacity (least loaded)."""
        # Nodes with health not 'healthy' are ignored.
        healthy_nodes = [
            n for n in self._nodes if getattr(n.node_info, "health", "healthy") == "healthy"
        ]
        if not healthy_nodes:
            raise RuntimeError("No healthy nodes available")

        # Choose node with greatest available slots; tie‑break by order.
        selected = max(healthy_nodes, key=lambda n: n.node_info.available)
        return selected

    async def submit(self, job: JobRequest) -> AsyncIterator[JobResult]:
        """
        Authenticate the request, select a node, and stream results.
        Retries transient RuntimeError up to three attempts.
        """
        # ------------------------------------------------------------------- #
        # Authentication
        # ------------------------------------------------------------------- #
        api_key: str = getattr(job, "api_key", "")
        try:
            ctx: AuthContext = self.auth_provider.verify(api_key)
        except InvalidKeyError as exc:
            logger.debug("Invalid API key for job %s: %s", job.job_id, exc)
            raise

        # ------------------------------------------------------------------- #
        # Node selection and bookkeeping
        # ------------------------------------------------------------------- #
        async with self._lock:
            node = self.select_node()
            if node.node_info.available <= 0:
                raise RuntimeError("Selected node has no available capacity")
            # Reserve a slot.
            node.node_info.available -= 1
            self._active_jobs.add(job.job_id)

        attempt = 0
        max_attempts = 3
        try:
            while attempt < max_attempts:
                try:
                    async for result in node.run_job(job):
                        # If the job has been cancelled, abort streaming.
                        if job.job_id in self._cancelled_jobs:
                            raise asyncio.CancelledError(f"Job {job.job_id} cancelled")
                        # Record usage metrics on the final chunk.
                        if result.finished:
                            tokens = result.usage.get("total_tokens", 0)
                            # Consume quota; may raise QuotaExceededError.
                            try:
                                self.auth_provider.consume_quota(api_key, tokens)
                            except QuotaExceededError as exc:
                                logger.debug(
                                    "Quota exceeded for key %s on job %s: %s",
                                    api_key,
                                    job.job_id,
                                    exc,
                                )
                                raise
                            self.metrics.record_success(node.node_info.node_id, tokens)
                        yield result
                    # Normal completion – exit retry loop.
                    break
                except RuntimeError as exc:
                    attempt += 1
                    logger.warning(
                        "Transient error on node %s for job %s (attempt %d/%d): %s",
                        node.node_info.node_id,
                        job.job_id,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    if attempt >= max_attempts:
                        # Record failure metric before propagating.
                        self.metrics.record_failure(node.node_info.node_id, str(exc))
                        raise
                    # Small back‑off before retrying.
                    await asyncio.sleep(0.1)
        finally:
            # ------------------------------------------------------------------- #
            # Cleanup – release node slot and remove job from tracking sets.
            # ------------------------------------------------------------------- #
            async with self._lock:
                node.node_info.available += 1
                self._active_jobs.discard(job.job_id)
                self._cancelled_jobs.discard(job.job_id)

    def cancel(self, job_id: str) -> bool:
        """
        Mark a job as cancelled. The next iteration of ``submit`` will raise
        ``asyncio.CancelledError`` for the job.
        """
        if job_id in self._active_jobs:
            self._cancelled_jobs.add(job_id)
            return True
        return False

    # ----------------------------------------------------------------------- #
    # Helper methods for introspection (useful in debugging / tests)
    # ----------------------------------------------------------------------- #
    def active_job_ids(self) -> Set[str]:
        """Return a snapshot of currently active job identifiers."""
        return set(self._active_jobs)