#!/usr/bin/env python3
"""
Example script for visual‑harness.

Demonstrates a zero‑configuration workflow that opens the *Settings* screen
by locating a visible “Settings” icon and tapping it.  The script can be run
directly or passed to the ``visual‑harness`` CLI via ``--script``.

Features showcased:
* Automatic configuration discovery by walking up the directory tree.
* Explicit session construction with sensible defaults.
* Use of the high‑level ``engine.helpers.tap_icon`` primitive.
* Single capture‑OCR‑dispatch cycle with robust error handling.
* Optional JSON output for CI integration.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict

from src.core.engine import Engine
from src.core.models import AutomationError, Session, register_plugin

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def discover_config(start_dir: Path, max_depth: int = 10) -> Dict[str, Any]:
    """
    Walk upwards from ``start_dir`` looking for a ``.visual_harness.json`` file.
    The first file found is parsed and returned; an empty dict is returned if
    none is found.
    """
    current = start_dir.resolve()
    for _ in range(max_depth):
        candidate = current / ".visual_harness.json"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:  # pragma: no cover
                logging.getLogger("visual_harness.example").error(
                    "Failed to parse config %s: %s", candidate, exc
                )
                return {}
        if current.parent == current:
            break
        current = current.parent
    return {}


def build_session(args: argparse.Namespace) -> Session:
    """
    Create a :class:`Session` from environment variables, optional config file,
    and command‑line overrides.
    """
    # Load defaults from the environment
    session = Session.load_from_env()

    # Merge configuration file if present
    config = discover_config(Path(__file__).parent)
    for key, value in config.items():
        if hasattr(session, key):
            setattr(session, key, value)

    # Apply CLI overrides
    if args.window_id is not None:
        session.window_id = args.window_id
    if args.debug_dir is not None:
        session.debug_dir = args.debug_dir
    if args.backend is not None:
        session.backend_name = args.backend
    if args.ocr_provider is not None:
        session.ocr_provider_name = args.ocr_provider
    return session


def exponential_backoff(attempt: int, base: float = 0.5) -> float:
    """
    Return a back‑off delay in seconds for ``attempt`` (0‑based).  The delay
    grows exponentially but is capped at 5 seconds.
    """
    delay = base * (2 ** attempt)
    return min(delay, 5.0)


def tap_settings_icon(engine: Engine, max_retries: int = 3) -> None:
    """
    Use the high‑level helper ``tap_icon`` to locate and tap the “Settings”
    icon.  Transient failures are retried with exponential back‑off.
    """
    logger = logging.getLogger("visual_harness.example.tap")
    for attempt in range(max_retries + 1):
        try:
            # ``tap_icon`` resolves the label to a concrete coordinate and
            # injects the tap via the configured backend.
            engine.helpers.tap_icon("Settings")
            logger.info("Successfully tapped Settings icon on attempt %d", attempt + 1)
            return
        except AutomationError as exc:
            logger.warning(
                "Attempt %d to tap Settings failed: %s", attempt + 1, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(exponential_backoff(attempt))


def run_engine_cycle(engine: Engine, max_retries: int = 3) -> None:
    """
    Execute a single ``Engine.run_cycle`` with retry semantics for transient
    errors such as low OCR confidence or temporary injection failures.
    """
    logger = logging.getLogger("visual_harness.example.cycle")
    for attempt in range(max_retries + 1):
        try:
            engine.run_cycle()
            logger.info(
                "Engine cycle completed on attempt %d (window %s)",
                attempt + 1,
                engine.session.window_id,
            )
            return
        except AutomationError as exc:
            logger.warning(
                "Engine cycle attempt %d failed: %s", attempt + 1, exc
            )
            if attempt == max_retries:
                raise
            time.sleep(exponential_backoff(attempt))


def configure_logging(debug_dir: str | None) -> None:
    """
    Initialise a root logger that writes human‑readable messages to ``stderr``
    and a detailed debug file inside ``debug_dir`` (if supplied).
    """
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    if debug_dir:
        debug_path = Path(debug_dir) / f"example_{int(time.time())}.log"
        file_handler = logging.FileHandler(debug_path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        root.info("Debug log initialised at %s", debug_path)


def emit_json_result(engine: Engine) -> None:
    """
    Emit a minimal JSON payload describing the successful run.  This format is
    convenient for CI pipelines that consume structured output.
    """
    result = {
        "timestamp": time.time(),
        "window_id": engine.session.window_id,
        "debug_log": next(
            (h.baseFilename for h in engine.logger.handlers if hasattr(h, "baseFilename")),
            None,
        ),
        "status": "success",
    }
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main() -> int:
    """
    Entry point for the example script.  Parses arguments, builds a session,
    creates an ``Engine`` instance, taps the Settings icon, runs a single
    capture‑OCR‑dispatch cycle, and reports the outcome.
    """
    parser = argparse.ArgumentParser(
        description="Visual‑Harness example: open Settings via tap_icon"
    )
    parser.add_argument(
        "--window-id",
        help="Target window identifier (overrides environment/config)",
    )
    parser.add_argument(
        "--debug-dir",
        help="Directory where per‑run debug logs are written",
    )
    parser.add_argument(
        "--backend",
        help="Backend implementation name (e.g., macos, windows, mock)",
    )
    parser.add_argument(
        "--ocr-provider",
        help="OCR provider name (e.g., vision, tesseract)",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Result output format",
    )
    args = parser.parse_args()

    configure_logging(args.debug_dir)

    try:
        session = build_session(args)
        engine = Engine(session)

        # High‑level action: locate and tap the Settings icon
        tap_settings_icon(engine)

        # Perform the capture‑OCR‑dispatch cycle that actually injects the tap
        run_engine_cycle(engine)

        if args.output == "json":
            emit_json_result(engine)
        else:
            sys.stdout.write("✅ Settings icon tapped successfully\n")
        return 0
    except AutomationError as exc:  # pragma: no cover
        sys.stderr.write(f"[ERROR] {exc}\n")
        return 1
    except Exception as exc:  # pragma: no cover
        # Unexpected failures are logged to the debug file for post‑mortem analysis
        logging.getLogger("visual_harness.example").exception(
            "Unhandled exception in example script"
        )
        sys.stderr.write(f"[FATAL] {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())