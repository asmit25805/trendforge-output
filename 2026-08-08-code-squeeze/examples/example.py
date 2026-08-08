import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import httpx
import uvicorn
from fastapi import FastAPI

from src.api.server import ProxyServer
from src.core.models import Config, CompressionResult, Segment

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def _write_system_prompt(path: Path) -> None:
    """
    Write a minimal system prompt file required by the LLM client.
    """
    prompt = "You are a deterministic code compression assistant."
    try:
        path.write_text(prompt, encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write system prompt at %s: %s", path, exc)
        raise


def _write_config_file(path: Path, system_prompt_path: Path, cache_path: Path) -> None:
    """
    Create a tiny ``config.json`` that the server can discover.
    """
    cfg: Dict[str, Any] = {
        "model": "dummy",
        "system_prompt_path": str(system_prompt_path),
        "max_workers": 2,
        "rate_limit": 60,
        "cache_path": str(cache_path),
    }
    try:
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.error("Failed to write config file at %s: %s", path, exc)
        raise


def _discover_config(start_dir: Path) -> Path:
    """
    Walk upwards from ``start_dir`` looking for ``config.json``.
    Returns the absolute path to the file or raises ``FileNotFoundError``.
    """
    current = start_dir.resolve()
    for _ in range(10):
        candidate = current / "config.json"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise FileNotFoundError("Configuration file 'config.json' not found")


def _load_config() -> Config:
    """
    Load a ``Config`` instance from the nearest ``config.json``.
    """
    config_path = _discover_config(Path.cwd())
    return Config.parse_file(config_path)


def _create_example_segments() -> List[Segment]:
    """
    Produce a list with a single example ``Segment`` used for the demo request.
    """
    return [
        Segment(
            id="example.py:1-5",
            intent="simplify the function",
            code=(
                "def add(a, b):\n"
                "    # Adds two numbers\n"
                "    result = a + b\n"
                "    return result\n"
            ),
            metadata={"path": "example.py"},
        )
    ]


def _payload_from_segments(segments: List[Segment]) -> Dict[str, Any]:
    """
    Convert a list of ``Segment`` objects into the JSON payload expected by the server.
    """
    return {
        "segments": [
            {
                "id": seg.id,
                "intent": seg.intent,
                "code": seg.code,
                "metadata": seg.metadata,
            }
            for seg in segments
        ]
    }


def _run_server_in_thread(config_path: Path, host: str = "127.0.0.1", port: int = 8000) -> threading.Thread:
    """
    Spin up a ``ProxyServer`` in a background thread using ``uvicorn``.
    Returns the thread object so the caller can join or terminate it.
    """
    server = ProxyServer(config_path=config_path)

    def _target() -> None:
        try:
            uvicorn.run(server.app, host=host, port=port, log_level="info")
        except Exception as exc:  # pragma: no cover
            logger.exception("Server crashed: %s", exc)

    thread = threading.Thread(target=_target, daemon=True, name="ProxyServerThread")
    thread.start()
    # Give the server a moment to start listening.
    time.sleep(1.0)
    return thread


async def _post_payload(url: str, payload: Dict[str, Any]) -> List[CompressionResult]:
    """
    Send a POST request to ``/compress`` and parse the JSON response into ``CompressionResult`` objects.
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("HTTP request failed at line %d: %s", sys._getframe().f_lineno, exc)
            raise

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            logger.error("Invalid JSON response at line %d: %s", sys._getframe().f_lineno, exc)
            raise

        results: List[CompressionResult] = []
        for item in data.get("results", []):
            try:
                result = CompressionResult(
                    segment_id=item["segment_id"],
                    action=item["action"],
                    compressed_code=item["compressed_code"],
                    usage=item["usage"],
                    model=item["model"],
                    timestamp=item["timestamp"],
                )
                results.append(result)
            except KeyError as exc:
                logger.error(
                    "Missing expected field %s in response item at line %d", exc.args[0], sys._getframe().f_lineno
                )
                raise
        return results


def _print_results(results: List[CompressionResult]) -> None:
    """
    Pretty‑print the compression results to stdout.
    """
    for res in results:
        logger.info(
            "Segment %s -> %s (model=%s, tokens=%s)",
            res.segment_id,
            res.action,
            res.model,
            res.usage.get("total_tokens", "N/A"),
        )
        if res.compressed_code:
            logger.info("Compressed code:\n%s", res.compressed_code)


def main() -> None:
    """
    Entry point for the example script.
    It creates a temporary configuration, launches the server, sends a payload,
    and prints the compression results.
    """
    # Create a temporary directory that will hold config files.
    temp_dir = Path(os.getenv("CODE_SQUEEZE_EXAMPLE_ROOT", Path.cwd()))
    config_path = temp_dir / "config.json"
    system_prompt_path = temp_dir / "system_prompt.txt"
    cache_path = temp_dir / "cache.db"

    try:
        _write_system_prompt(system_prompt_path)
        _write_config_file(config_path, system_prompt_path, cache_path)
    except Exception as exc:  # pragma: no cover
        logger.error("Failed to prepare configuration at line %d: %s", sys._getframe().f_lineno, exc)
        sys.exit(1)

    # Start the server.
    server_thread = _run_server_in_thread(config_path)

    # Build the request payload.
    segments = _create_example_segments()
    payload = _payload_from_segments(segments)

    # Perform the request.
    url = "http://127.0.0.1:8000/compress"
    try:
        results = asyncio.run(_post_payload(url, payload))
    except Exception as exc:  # pragma: no cover
        logger.error("Compression request failed at line %d: %s", sys._getframe().f_lineno, exc)
        sys.exit(1)

    # Display the outcome.
    _print_results(results)

    # Clean shutdown – uvicorn runs in daemon mode, so exiting the script stops it.
    logger.info("Example completed successfully.")


if __name__ == "__main__":
    main()