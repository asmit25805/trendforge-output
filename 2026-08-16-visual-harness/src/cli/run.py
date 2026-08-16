from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.engine import Engine
from src.core.models import AutomationError, Session

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _discover_config(start_dir: Path) -> Dict[str, Any]:
    """
    Walk upwards from ``start_dir`` looking for a ``.visual_harness.json`` file.
    The first file found is parsed and returned; an empty dict is returned if
    none is found.
    """
    current = start_dir.resolve()
    for _ in range(10):
        candidate = current / ".visual_harness.json"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                logging.getLogger("visual_harness.cli").error(
                    "Failed to parse config %s: %s", candidate, exc
                )
                return {}
        if current.parent == current:
            break
        current = current.parent
    return {}


def _build_session(
    args: argparse.Namespace, config: Dict[str, Any]
) -> Session:
    """
    Create a :class:`Session` from environment variables, command‑line arguments,
    and optional configuration file. Command‑line arguments take precedence over
    configuration values.
    """
    session = Session.load_from_env()
    # Apply configuration overrides
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


def _run_engine_once(engine: Engine, output_format: str) -> None:
    """
    Execute a single engine cycle and emit the result in the requested format.
    """
    try:
        engine.run_cycle()
        if output_format == "json":
            result = {
                "timestamp": time.time(),
                "window_id": engine.session.window_id,
                "debug_log": str(engine.logger.handlers[0].baseFilename),
            }
            json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
            sys.stdout.write("\n")
        else:
            sys.stdout.write(
                f"[INFO] Cycle completed for window {engine.session.window_id}\n"
            )
    except AutomationError as exc:
        sys.stderr.write(f"[ERROR] {exc}\n")
        sys.exit(1)


def _execute_user_script(engine: Engine, script_path: Path) -> None:
    """
    Load a Python script from ``script_path`` and execute it inside the engine
    context. Any exception is reported as a fatal error.
    """
    try:
        script_content = script_path.read_text(encoding="utf-8")
    except OSError as exc:
        sys.stderr.write(f"[FATAL] Unable to read script {script_path}: {exc}\n")
        sys.exit(1)

    try:
        engine.execute_script(script_content, globals_dict={})
    except AutomationError as exc:
        sys.stderr.write(f"[ERROR] {exc}\n")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"[FATAL] Unexpected error while executing script: {exc}\n")
        sys.exit(1)


def _configure_logging(debug_dir: Optional[Path]) -> None:
    """
    Initialise a root logger that writes DEBUG level messages to a file inside
    ``debug_dir`` and INFO level messages to the console.
    """
    logger = logging.getLogger("visual_harness")
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(levelname)s %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    if debug_dir is None:
        debug_dir = Path.cwd()
    debug_path = debug_dir / f"vh_cli_{int(time.time())}.log"
    file_handler = logging.FileHandler(debug_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    logger.debug("CLI logging initialised – debug file at %s", debug_path)


def _parse_arguments() -> argparse.Namespace:
    """
    Build the ``argparse`` parser and return the populated namespace.
    """
    parser = argparse.ArgumentParser(
        prog="visual-harness",
        description="LLM‑driven visual UI automation CLI",
    )
    parser.add_argument(
        "--window-id",
        type=str,
        help="Identifier of the target window (required unless provided via env)",
    )
    parser.add_argument(
        "--script",
        type=Path,
        help="Path to a Python script that will be executed with engine helpers",
    )
    parser.add_argument(
        "--output-format",
        choices=["text", "json"],
        default="text",
        help="Format for the CLI output",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Explicit path to a configuration file (JSON)",
    )
    parser.add_argument(
        "--debug-dir",
        type=Path,
        help="Directory where per‑run debug logs are written",
    )
    parser.add_argument(
        "--backend",
        type=str,
        help="Force selection of a backend (e.g., macos, windows)",
    )
    parser.add_argument(
        "--ocr-provider",
        type=str,
        help="Force selection of an OCR provider (e.g., vision)",
    )
    return parser.parse_args()


def main() -> None:
    """
    Entry point for the ``visual-harness`` command line interface.
    """
    args = _parse_arguments()
    config: Dict[str, Any] = {}
    if args.config:
        try:
            with args.config.open("r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as exc:
            sys.stderr.write(f"[FATAL] Unable to load config {args.config}: {exc}\n")
            sys.exit(1)
    else:
        config = _discover_config(Path.cwd())

    _configure_logging(args.debug_dir)

    logger = logging.getLogger("visual_harness.cli")
    logger.debug("Parsed arguments: %s", args)
    logger.debug("Loaded configuration: %s", config)

    session = _build_session(args, config)
    logger.info("Session built for window %s", getattr(session, "window_id", "<unknown>"))

    try:
        engine = Engine(session)
    except AutomationError as exc:
        sys.stderr.write(f"[FATAL] Engine initialisation failed: {exc}\n")
        sys.exit(1)
    except Exception as exc:
        sys.stderr.write(f"[FATAL] Unexpected error during engine creation: {exc}\n")
        sys.exit(1)

    if args.script:
        _execute_user_script(engine, args.script)
    else:
        _run_engine_once(engine, args.output_format)


if __name__ == "__main__":
    main()