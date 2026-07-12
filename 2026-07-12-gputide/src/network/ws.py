import asyncio
import json
import logging
from enum import Enum
from typing import Any, AsyncIterator, Dict

import websockets
from websockets.exceptions import ConnectionClosedError, WebSocketException

from src.auth.auth import AuthProvider, InvalidKeyError, QuotaExceededError
from src.core.engine import Scheduler
from src.core.models import AuthContext, JobRequest, JobResult
from src.metrics.collector import MetricsCollector

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class WSMessageType(str, Enum):
    AUTH = "auth"
    JOB = "job"
    RESULT = "result"
    ERROR = "error"


class WebSocketHandler:
    """Utility class that encapsulates the lifecycle of a single WebSocket client.

    The class is deliberately lightweight – it does not own the ``Scheduler`` or
    ``AuthProvider`` instances; they are injected at construction time.
    """

    def __init__(self, websocket: websockets.WebSocketClientProtocol, auth_provider: AuthProvider, scheduler: Scheduler, collector: MetricsCollector):
        self.websocket = websocket
        self.auth_provider = auth_provider
        self.scheduler = scheduler
        self.collector = collector
        self.api_key: Optional[str] = None
        self.auth_context: Optional[AuthContext] = None

    async def run(self) -> None:
        try:
            await self._authenticate()
            async for message in self._message_iterator():
                await self._handle_message(message)
        except (ConnectionClosedError, WebSocketException) as exc:
            logger.info("WebSocket closed: %s", exc)
        except Exception:
            logger.exception("Unexpected error in WebSocketHandler")
            await self._send_error("internal server error")

    async def _authenticate(self) -> None:
        raw = await self.websocket.recv()
        data = json.loads(raw)
        if data.get("type") != WSMessageType.AUTH:
            raise InvalidKeyError("First message must be authentication")
        self.api_key = data.get("api_key")
        if not self.api_key:
            raise InvalidKeyError("Missing api_key field")
        self.auth_context = await self.auth_provider.validate_key(self.api_key)
        await self._send({"type": WSMessageType.AUTH, "status": "ok", "quota": self.auth_context.quota_remaining})
        logger.info("Client authenticated with key %s", self.api_key)

    async def _message_iterator(self) -> AsyncIterator[str]:
        while True:
            msg = await self.websocket.recv()
            yield msg

    async def _handle_message(self, raw: str) -> None:
        data = json.loads(raw)
        if data.get("type") != WSMessageType.JOB:
            await self._send_error("expected job message")
            return
        payload = data.get("payload", {})
        request_id = data.get("request_id", "")
        job = JobRequest(request_id=request_id, payload=payload)
        # Simple quota deduction – 1 token per job
        await self.auth_provider.deduct_quota(self.api_key, tokens=1)
        result: JobResult = await self.scheduler.schedule(job)
        await self._send({"type": WSMessageType.RESULT, "request_id": result.request_id, "result": result.result})
        self.collector.jobs_processed.inc()

    async def _send(self, message: Dict[str, Any]) -> None:
        await self.websocket.send(json.dumps(message))

    async def _send_error(self, error_msg: str) -> None:
        await self._send({"type": WSMessageType.ERROR, "error": error_msg})
