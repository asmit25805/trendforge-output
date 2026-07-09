from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
import time
from typing import Any, Dict

import yaml

from src.core.models import (
    ExecutionResult,
    ExecutionTimeout,
    ProvisionError,
    SkillLoadError,
    SkillMeta,
)
from src.executor import SkillExecutor
from src.provisioner import BoxProvisioner, BoxSpec, ProvisionedBox
from src.registry import SkillRegistry

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def _load_config(start_dir: pathlib.Path) -> Dict[str, Any]:
    """
    Walk upward from ``start_dir`` looking for a ``devbox.yaml`` configuration file.
    Returns an empty dict if none is found.
    """
    current = start_dir.resolve()
    for parent in [current, *list(current.parents)]:
        candidate = parent / "devbox.yaml"
        if candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                logger.debug("Loaded config from %s", candidate)
                return cfg
            except yaml.YAMLError as exc:
                logger.error("Failed to parse config %s: %s", candidate, exc)
                raise RuntimeError(f"Invalid YAML in config file {candidate}") from exc
    return {}


def _build_box_spec(meta: SkillMeta) -> BoxSpec:
    """
    Construct a :class:`BoxSpec` from the ``metadata`` field of a skill.
    Missing keys are replaced with sensible defaults.
    """
    spec_data = meta.metadata.get("box_spec", {})
    if not isinstance(spec_data, dict):
        raise ValueError(
            f"box_spec in skill {meta.name} must be a mapping, got {type(spec_data)}"
        )
    if "image" not in spec_data:
        raise ValueError(f"box_spec for skill {meta.name} missing required 'image'")
    return BoxSpec(
        image=spec_data["image"],
        env=spec_data.get("env", {}),
        ports=spec_data.get("ports", []),
        volumes=spec_data.get("volumes", []),
        resources=spec_data.get("resources", {}),
    )


def _format_result(result: ExecutionResult, output_format: str) -> str:
    """
    Return a string representation of ``result`` according to ``output_format``.
    Supported formats are ``text`` and ``json``.
    """
    if output_format == "json":
        payload = {
            "success": result.success,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "artifact_path": str(result.artifact_path),
        }
        return json.dumps(payload, indent=2)

    lines = [
        f"Skill execution {'succeeded' if result.success else 'failed'}",
        f"Exit code   : {result.exit_code}",
        f"Duration    : {result.duration_ms} ms",
        f"Output      :",
        result.output.rstrip(),
        f"Result file : {result.artifact_path}",
    ]
    return "\n".join(lines)


def _retry_provision(
    provisioner: BoxProvisioner,
    spec: BoxSpec,
    max_attempts: int,
    base_backoff: float,
) -> ProvisionedBox:
    """
    Attempt to provision a box up to ``max_attempts`` times.
    Uses exponential back‑off starting at ``base_backoff`` seconds.
    Raises ``ProvisionError`` if all attempts fail.
    """
    attempt = 0
    while True:
        try:
            return provisioner.provision(spec)
        except ProvisionError as exc:
            attempt += 1
            if attempt >= max_attempts:
                logger.error(
                    "Provisioning failed after %d attempts: %s", attempt, exc
                )
                raise
            backoff = base_backoff * (2 ** (attempt - 1))
            logger.warning(
                "Provisioning error (%s); retry %d/%d in %.1f s",
                exc,
                attempt,
                max_attempts,
                backoff,
            )
            time.sleep(backoff)


def main() -> None:
    """
    Entry point for the ai‑devbox‑orchestrator CLI.
    Supports ``list`` and ``run`` sub‑commands.
    """
    parser = argparse.ArgumentParser(prog="ai-devbox-orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser(
        "list", help="List all discoverable skills"
    )
    list_parser.add_argument(
        "--path",
        type=str,
        default=".",
        help="Root directory to search for skill definitions",
    )

    run_parser = subparsers.add_parser(
        "run", help="Execute a skill inside a provisioned dev box"
    )
    run_parser.add_argument(
        "skill", type=str, help="Name of the skill to execute"
    )
    run_parser.add_argument(
        "--path",
        type=str,
        default=".",
        help="Root directory to search for skill definitions",
    )
    run_parser.add_argument(
        "--inputs",
        type=str,
        default="{}",
        help="JSON string of inputs to pass to the skill",
    )
    run_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Result formatting",
    )
    run_parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Maximum provisioning attempts",
    )
    run_parser.add_argument(
        "--backoff",
        type=float,
        default=1.0,
        help="Base back‑off seconds for provisioning retries",
    )

    args = parser.parse_args()

    # Load optional configuration; currently unused but kept for future extensions
    _ = _load_config(pathlib.Path(args.path))

    registry = SkillRegistry()
    try:
        registry.load_skills(args.path)
    except SkillLoadError as exc:
        logger.error("Failed to load skills: %s", exc)
        sys.exit(1)

    if args.command == "list":
        for skill in registry._skills.values():
            print(f"{skill.name}: {skill.description}")
        return

    # ``run`` command handling
    skill_meta = registry.get_skill(args.skill)
    if skill_meta is None:
        logger.error("Skill %s not found", args.skill)
        sys.exit(1)

    try:
        box_spec = _build_box_spec(skill_meta)
    except ValueError as exc:
        logger.error("Invalid box specification: %s", exc)
        sys.exit(1)

    provisioner = BoxProvisioner()
    try:
        provisioned_box = _retry_provision(
            provisioner,
            box_spec,
            max_attempts=args.retries,
            base_backoff=args.backoff,
        )
    except ProvisionError:
        sys.exit(1)

    try:
        inputs = json.loads(args.inputs)
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON for inputs: %s", exc)
        sys.exit(1)

    executor = SkillExecutor()
    try:
        result = executor.execute(skill_meta, provisioned_box, inputs)
    except ExecutionTimeout as exc:
        logger.warning("Execution timed out: %s", exc)
        # The executor is expected to return a partial result even on timeout
        result = exc.result  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("Skill execution failed: %s", exc)
        sys.exit(1)

    formatted = _format_result(result, args.output)
    print(formatted)


if __name__ == "__main__":
    main()