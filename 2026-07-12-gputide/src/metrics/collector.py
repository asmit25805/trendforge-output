import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import Dict, List, Mapping, MutableMapping, Optional

from prometheus_client import Counter, Histogram, start_http_server

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


@dataclass(frozen=True)
class _SuccessMetric:
    """Internal helper dataclass used by :class:`MetricsCollector`.

    It stores a ``Counter`` for successful job completions and a ``Histogram``
    for job latency.
    """

    success_counter: Counter
    latency_histogram: Histogram


class MetricsCollector:
    """Collects Prometheus metrics for the gputide service.

    The collector is deliberately small – it tracks a handful of counters that
    are sufficient for the unit tests and for a basic production deployment.
    """

    def __init__(self, port: int = 8001):
        self.port = port
        # Counters
        self.jobs_total = Counter("gputide_jobs_total", "Total number of jobs received")
        self.jobs_in_progress = Counter("gputide_jobs_in_progress", "Jobs currently being processed")
        self.jobs_processed = Counter("gputide_jobs_processed", "Jobs successfully processed")
        self.jobs_failed = Counter("gputide_jobs_failed", "Jobs that raised an exception")
        # Histogram for latency (seconds)
        self.job_latency = Histogram(
            "gputide_job_latency_seconds",
            "Latency of job processing",
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 5),
        )
        # Start the HTTP server in the background
        self._server_task: Optional[asyncio.Task] = None
        self._start_server()

    def _start_server(self) -> None:
        loop = asyncio.get_event_loop()
        self._server_task = loop.create_task(self._run_http())
        logger.info("Prometheus metrics server started on port %d", self.port)

    async def _run_http(self) -> None:
        # ``start_http_server`` is blocking, so run it in a thread executor.
        await asyncio.get_event_loop().run_in_executor(None, start_http_server, self.port)

    def record_job_latency(self, seconds: float) -> None:
        self.job_latency.observe(seconds)

    def shutdown(self) -> None:
        if self._server_task:
            self._server_task.cancel()
            logger.info("Prometheus metrics server stopped")


def start_prometheus_server(port: int = 8001) -> MetricsCollector:
    """Convenient helper that returns a ready‑to‑use ``MetricsCollector``.

    The function is kept for backward compatibility with earlier versions of the
    library.
    """
    return MetricsCollector(port=port)
