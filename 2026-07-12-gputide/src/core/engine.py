import asyncio
import json
import logging
from typing import List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from src.auth.auth import AuthProvider, InvalidKeyError, QuotaExceededError, AuthContext
from src.core.models import JobRequest, JobResult, NodeInfo
from src.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class WorkerNode:
    """Represents a single GPU worker capable of processing ``JobRequest`` objects.

    The node holds a ``NodeInfo`` instance that tracks its capacity and current load.
    """

    def __init__(self, node_id: str, capacity: int, collector: MetricsCollector):
        self.info = NodeInfo(node_id=node_id, capacity=capacity, current_load=0)
        self._collector = collector
        self._lock = asyncio.Lock()

    async def process_job(self, request: JobRequest) -> JobResult:
        """Simulate processing a job.

        In a real implementation this would forward the payload to a GPU inference
        engine. Here we simply ``await`` a short sleep and echo the payload back.
        """
        async with self._lock:
            # Update load counters
            self.info = self.info.increment_load()
            self._collector.jobs_in_progress.inc()
            self._collector.jobs_total.inc()
            logger.info("Node %s started job %s", self.info.node_id, request.request_id)

        # Simulated processing time – 0.1 s per request for demo purposes
        await asyncio.sleep(0.1)

        result = JobResult(request_id=request.request_id, result=request.payload)

        async with self._lock:
            self.info = self.info.decrement_load()
            self._collector.jobs_in_progress.dec()
            logger.info("Node %s finished job %s", self.info.node_id, request.request_id)
        return result


class Scheduler:
    """Simple round‑robin / least‑load scheduler for ``WorkerNode`` instances.

    The scheduler is deliberately lightweight – it only tracks a list of nodes
    and selects the one with the smallest ``current_load`` that still has capacity.
    """

    def __init__(self, collector: MetricsCollector):
        self._nodes: List[WorkerNode] = []
        self._collector = collector
        self._node_lock = asyncio.Lock()

    async def add_node(self, node_id: str, capacity: int) -> None:
        async with self._node_lock:
            node = WorkerNode(node_id=node_id, capacity=capacity, collector=self._collector)
            self._nodes.append(node)
            logger.info("Added worker node %s with capacity %d", node_id, capacity)

    async def schedule(self, request: JobRequest) -> JobResult:
        """Select an available node and forward *request* to it.

        Raises ``RuntimeError`` if no node can accept the job.
        """
        async with self._node_lock:
            # Choose node with the lowest load that is still available
            available_nodes = [n for n in self._nodes if n.info.is_available()]
            if not available_nodes:
                raise RuntimeError("No available worker nodes")
            node = min(available_nodes, key=lambda n: n.info.current_load)
        return await node.process_job(request)


def create_app(auth_provider: AuthProvider, scheduler: Scheduler) -> FastAPI:
    """Factory that creates the FastAPI application used by the server.

    The endpoint ``/ws`` expects a query parameter ``api_key`` for authentication.
    """

    app = FastAPI()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        try:
            # First message must contain the API key in JSON: {"api_key": "..."}
            raw = await websocket.receive_text()
            data = json.loads(raw)
            api_key = data.get("api_key")
            if not api_key:
                raise InvalidKeyError("Missing api_key in initial message")
            auth_ctx: AuthContext = await auth_provider.validate_key(api_key)
            logger.info("Authenticated client with key %s (quota %d)", api_key, auth_ctx.quota_remaining)

            while True:
                msg = await websocket.receive_text()
                payload = json.loads(msg)
                job_req = JobRequest(request_id=payload.get("request_id", ""), payload=payload.get("payload", {}))
                # Simple quota check – assume each request costs 1 token
                await auth_provider.deduct_quota(api_key, tokens=1)
                result = await scheduler.schedule(job_req)
                await websocket.send_text(result.to_json())
        except (WebSocketDisconnect, ConnectionError):
            logger.info("WebSocket client disconnected")
        except InvalidKeyError as exc:
            await websocket.send_text(json.dumps({"error": str(exc)}))
            await websocket.close()
        except QuotaExceededError as exc:
            await websocket.send_text(json.dumps({"error": str(exc)}))
            await websocket.close()
        except Exception as exc:
            logger.exception("Unexpected error in WebSocket handler")
            await websocket.send_text(json.dumps({"error": "internal server error"}))
            await websocket.close()

    return app


def run_server(host: str = "0.0.0.0", port: int = 8000, *, auth_provider: AuthProvider, scheduler: Scheduler):
    """Convenience wrapper that starts the FastAPI server using ``uvicorn``.

    This function is imported by the package's ``__main__`` entry point.
    """
    import uvicorn

    app = create_app(auth_provider=auth_provider, scheduler=scheduler)
    uvicorn.run(app, host=host, port=port)
