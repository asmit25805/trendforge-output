import logging
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from src.core.models import Config, Segment, CompressionResult
from src.core.engine import CompressionEngine, CacheError

logger = logging.getLogger(__name__)


class ProxyServer:
    """FastAPI wrapper exposing the compression endpoint.

    The server is instantiated with a ``Config`` object and provides a ``run`` method
    that starts the ASGI server using ``uvicorn``.
    """

    def __init__(self, config: Config):
        self.app = FastAPI()
        self.engine = CompressionEngine(config)
        self._register_routes()

    def _register_routes(self) -> None:
        @self.app.post("/compress")
        async def compress_endpoint(segments: List[Segment]):
            """Compress a batch of ``Segment`` objects.

            Returns a list of ``CompressionResult`` dictionaries.  Errors raised by the
            cache layer are translated into HTTP 500 responses.
            """
            try:
                results: List[CompressionResult] = self.engine.compress_batch(segments)
                return JSONResponse(content=[r.dict() for r in results])
            except CacheError as exc:
                logger.error("Cache error during compression: %s", exc)
                raise HTTPException(status_code=500, detail=str(exc))

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """Start the server using uvicorn.

        This method blocks until the server is stopped.
        """
        import uvicorn

        uvicorn.run(self.app, host=host, port=port)
