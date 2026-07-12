import argparse
import asyncio
import json
import logging
import sys
import uuid
from typing import Any, Dict, List

import websockets
from websockets.exceptions import ConnectionClosedError, InvalidMessage

from src.core.models import JobRequest

# Configure root logger for the example client.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("example_client")


class ExampleClient:
    """WebSocket client that authenticates, submits a job, and streams results."""

    def __init__(self, uri: str, api_key: str, max_retries: int = 3) -> None:
        """
        Create a client instance.

        Args:
            uri: WebSocket endpoint of the gputide server.
            api_key: API key used for authentication.
            max_retries: Number of retry attempts for transient failures.
        """
        self._uri = uri
        self._api_key = api_key
        self._max_retries = max_retries

    async def _connect(self) -> websockets.WebSocketClientProtocol:
        """
        Establish a WebSocket connection.

        Returns:
            An active WebSocket client protocol.
        """
        logger.debug("Connecting to %s", self._uri)
        return await websockets.connect(self._uri)

    async def _authenticate(self, ws: websockets.WebSocketClientProtocol) -> bool:
        """
        Send the authentication payload and evaluate the response.

        Args:
            ws: Active WebSocket connection.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        auth_payload = {"type": "auth", "key": self._api_key}
        await ws.send(json.dumps(auth_payload))
        logger.debug("Sent authentication payload")
        try:
            raw = await ws.recv()
        except (ConnectionClosedError, InvalidMessage) as exc:
            logger.error("Failed to receive auth response: %s", exc)
            return False
        response = json.loads(raw)
        if response.get("error"):
            logger.error("Authentication error: %s", response["error"])
            return False
        logger.info("Authentication successful")
        return True

    async def _send_job(self, ws: websockets.WebSocketClientProtocol, job: JobRequest) -> None:
        """
        Transmit a job request to the server.

        Args:
            ws: Active WebSocket connection.
            job: The job request to be processed.
        """
        job_payload = {"type": "job", "payload": job.model_dump() if hasattr(job, "model_dump") else job.__dict__}
        await ws.send(json.dumps(job_payload))
        logger.info("Job %s submitted (model=%s)", job.job_id, job.model)

    async def _handle_stream(self, ws: websockets.WebSocketClientProtocol) -> None:
        """
        Receive streamed chunks from the server and print them.

        Args:
            ws: Active WebSocket connection.
        """
        token_count = 0
        while True:
            try:
                raw = await ws.recv()
            except (ConnectionClosedError, InvalidMessage) as exc:
                logger.error("Stream closed unexpectedly: %s", exc)
                raise RuntimeError("Transient stream error") from exc
            message = json.loads(raw)

            msg_type = message.get("type")
            if msg_type == "chunk":
                content = message.get("content", "")
                token_count += len(content.split())
                print(content, end="", flush=True)
            elif msg_type == "done":
                logger.info("\nStream completed, total tokens: %d", token_count)
                break
            elif msg_type == "error":
                error_msg = message.get("error", "unknown")
                retryable = message.get("retryable", False)
                logger.error("Server error: %s (retryable=%s)", error_msg, retryable)
                if retryable:
                    raise RuntimeError("Transient server error")
                else:
                    sys.exit(1)
            else:
                logger.warning("Received unknown message type: %s", msg_type)

    async def run(self, job: JobRequest) -> None:
        """
        Execute the full client workflow: connect, authenticate, submit job, and stream results.

        Retries are performed for transient failures up to the configured limit.

        Args:
            job: The job request to be processed.
        """
        attempt = 0
        while attempt <= self._max_retries:
            try:
                async with await self._connect() as ws:
                    if not await self._authenticate(ws):
                        return
                    await self._send_job(ws, job)
                    await self._handle_stream(ws)
                return
            except RuntimeError as exc:
                attempt += 1
                if attempt > self._max_retries:
                    logger.error("Maximum retries exceeded: %s", exc)
                    break
                backoff = 2 ** attempt
                logger.info("Retry %d/%d after %d seconds due to: %s", attempt, self._max_retries, backoff, exc)
                await asyncio.sleep(backoff)
            except Exception as exc:  # pylint: disable=broad-except
                logger.exception("Unexpected error: %s", exc)
                break


def build_job_request(
    model: str,
    messages: List[Dict[str, Any]],
    max_tokens: int | None = None,
    stream: bool = True,
) -> JobRequest:
    """
    Construct a JobRequest instance with a unique identifier.

    Args:
        model: Name of the LLM model to invoke.
        messages: Chat history in OpenAI format.
        max_tokens: Optional ceiling for generated tokens.
        stream: Whether the server should stream partial results.

    Returns:
        A fully populated JobRequest.
    """
    job_id = str(uuid.uuid4())
    return JobRequest(
        job_id=job_id,
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        stream=stream,
    )


def parse_cli_args() -> argparse.Namespace:
    """
    Parse command‑line arguments for the example client.

    Returns:
        Namespace with populated arguments.
    """
    parser = argparse.ArgumentParser(description="gputide example WebSocket client")
    parser.add_argument("--uri", required=True, help="WebSocket endpoint, e.g. ws://localhost:8000/ws")
    parser.add_argument("--api-key", required=True, help="API key for authentication")
    parser.add_argument("--model", default="llama2-7b", help="Model name to request")
    parser.add_argument(
        "--message",
        action="append",
        default=[],
        help="Message in JSON format (e.g. '{\"role\":\"user\",\"content\":\"Hello\"}')",
    )
    parser.add_argument("--max-tokens", type=int, default=None, help="Maximum tokens to generate")
    parser.add_argument("--no-stream", dest="stream", action="store_false", help="Disable streaming")
    return parser.parse_args()


def deserialize_messages(raw_messages: List[str]) -> List[Dict[str, Any]]:
    """
    Convert a list of JSON strings into message dictionaries.

    Args:
        raw_messages: List of JSON‑encoded message strings.

    Returns:
        List of message dictionaries.
    """
    messages: List[Dict[str, Any]] = []
    for raw in raw_messages:
        try:
            msg = json.loads(raw)
            if isinstance(msg, dict) and "role" in msg and "content" in msg:
                messages.append(msg)
            else:
                logger.warning("Invalid message format ignored: %s", raw)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to decode message '%s': %s", raw, exc)
    return messages


async def main() -> None:
    """
    Entry point for the example client script.
    """
    args = parse_cli_args()
    messages = deserialize_messages(args.message)
    if not messages:
        logger.error("At least one message must be provided")
        sys.exit(1)

    job = build_job_request(
        model=args.model,
        messages=messages,
        max_tokens=args.max_tokens,
        stream=args.stream,
    )
    client = ExampleClient(uri=args.uri, api_key=args.api_key)
    await client.run(job)


if __name__ == "__main__":
    asyncio.run(main())