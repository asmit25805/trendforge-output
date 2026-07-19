import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict

from src.core.engine import Config, VideoProcessor
from src.prompt.generator import PromptGenerator


def _configure_logging(verbose: bool) -> None:
    """
    Configure the root logger.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Suppress overly noisy third‑party loggers unless in verbose mode
    for logger_name in ("urllib3", "ffmpeg", "faster_whisper"):
        logging.getLogger(logger_name).setLevel(logging.WARNING if not verbose else logging.INFO)


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse command‑line arguments for the example script.
    """
    parser = argparse.ArgumentParser(
        prog="run_example",
        description="Run vid2prompt on a video and print the resulting JSON payload.",
    )
    parser.add_argument(
        "video",
        type=str,
        help="Path to the input video file.",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR processing for each retained frame.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat any non‑critical warning as fatal.",
    )
    parser.add_argument(
        "--embed-images",
        action="store_true",
        help="Embed extracted keyframes as base64 strings in the output JSON.",
    )
    parser.add_argument(
        "--token-estimate",
        action="store_true",
        help="Include a rough token count estimate in the output payload.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose debug logging.",
    )
    return parser.parse_args(argv)


def _build_config(args: argparse.Namespace) -> Config:
    """
    Build a Config instance from parsed arguments.
    """
    return Config(
        ocr_enabled=args.ocr,
        strict=args.strict,
        embed_images=args.embed_images,
        token_estimate=args.token_estimate,
    )


def _run_pipeline(video_path: str, cfg: Config) -> Dict[str, Any]:
    """
    Execute the full vid2prompt pipeline and return the generated payload.
    """
    logger = logging.getLogger("run_example.pipeline")
    logger.debug("Starting VideoProcessor with video_path=%s", video_path)
    processor = VideoProcessor()
    package = processor.process(video_path, cfg)

    logger.debug(
        "VideoProcessor completed: %d frames, %d scenes, %d transcript segments",
        len(package.frames),
        len(package.scenes),
        len(package.transcript),
    )

    generator = PromptGenerator(
        embed_images=cfg.embed_images,
        token_estimate=cfg.token_estimate,
    )
    payload = generator.generate(package)
    logger.debug("PromptGenerator produced payload with %d keys", len(payload))
    return payload


def _print_json(payload: Dict[str, Any]) -> None:
    """
    Pretty‑print the payload as JSON to stdout.
    """
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def _handle_fatal_error(exc: BaseException) -> None:
    """
    Log a fatal error and exit with a non‑zero status code.
    """
    logger = logging.getLogger("run_example")
    logger.error("Fatal error: %s", exc, exc_info=exc)
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    """
    Entry point for the example script.
    """
    try:
        args = _parse_arguments(argv)
        _configure_logging(args.verbose)

        video_path = Path(args.video)
        if not video_path.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        cfg = _build_config(args)
        payload = _run_pipeline(str(video_path), cfg)
        _print_json(payload)

    except Exception as exc:  # pylint: disable=broad-except
        _handle_fatal_error(exc)


if __name__ == "__main__":
    main()