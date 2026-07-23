import pathlib
import json
import uuid
import datetime
import hashlib
import logging
import tempfile
import shutil
import os
import sys
import traceback
from typing import List, Dict, Any

from src.core.models import (
    TransactionIntent,
    BackendConfig,
    TargetSpec,
    HookSpec,
)
from src.core.engine import TransactionManager, TransactionResult
from src.backends.local import LocalBackendAdapter
from src.hooks.engine import HookEngine
from src.snapshot.store import SnapshotStore

_logger = logging.getLogger(__name__)
_logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
)
_logger.addHandler(_handler)


def _discover_config(start_dir: pathlib.Path) -> pathlib.Path | None:
    """
    Walk upward from *start_dir* looking for a ``.llm-configurator.json`` file.
    Returns the first match or ``None`` if not found.
    """
    current = start_dir.resolve()
    while True:
        candidate = current / ".llm-configurator.json"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            return None
        current = current.parent


def _load_config(config_path: pathlib.Path) -> Dict[str, Any]:
    """
    Load a JSON configuration file and return its contents as a dictionary.
    """
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _compute_sha256(path: pathlib.Path) -> str:
    """
    Compute the SHA‑256 hex digest of the file at *path*.
    """
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def _build_target_specs(files: List[pathlib.Path]) -> List[TargetSpec]:
    """
    Convert a list of file paths into ``TargetSpec`` objects, computing the
    SHA‑256 digest and other metadata for each file.
    """
    specs: List[TargetSpec] = []
    for path in files:
        if not path.is_file():
            raise FileNotFoundError(f"Target file '{path}' does not exist")
        specs.append(
            TargetSpec(
                path=str(path),
                sha256=_compute_sha256(path),
                size=path.stat().st_size,
                mtime_ns=path.stat().st_mtime_ns,
            )
        )
    return specs


def _create_hook_dir(base_dir: pathlib.Path) -> pathlib.Path:
    """
    Create a temporary hooks directory containing a simple pre‑hook script.
    The script writes a log line and exits with status 0.
    """
    hooks_dir = base_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)

    pre_hook = hooks_dir / "pre_log.sh"
    pre_hook.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"[pre‑hook] Transaction {{TX_ID}} started at $(date)\"\n"
        "exit 0\n"
    )
    pre_hook.chmod(pre_hook.stat().st_mode | 0o111)  # Make executable

    return hooks_dir


def _build_hook_specs(hooks_dir: pathlib.Path) -> List[HookSpec]:
    """
    Scan *hooks_dir* for executable hook scripts and return a list of
    ``HookSpec`` objects describing them.
    """
    specs: List[HookSpec] = []
    for entry in hooks_dir.rglob("*"):
        if not entry.is_file():
            continue
        if entry.name.endswith(".disabled"):
            continue
        if not os.access(entry, os.X_OK):
            continue
        when = "pre"
        name = entry.name.lower()
        if name.startswith("pre_"):
            when = "pre"
        elif name.startswith("post_"):
            when = "post"
        specs.append(
            HookSpec(
                path=str(entry),
                when=when,
                env={},  # No special environment variables
            )
        )
    return specs


def _prepare_intent(
    root: pathlib.Path,
    target_files: List[pathlib.Path],
    hooks_dir: pathlib.Path | None,
) -> TransactionIntent:
    """
    Assemble a :class:`TransactionIntent` from the given root directory,
    target files, and optional hooks directory.
    """
    targets = _build_target_specs(target_files)
    backend_cfg = BackendConfig(type="local", options={"root": str(root)})
    hooks = _build_hook_specs(hooks_dir) if hooks_dir else []
    intent = TransactionIntent(
        tx_id=str(uuid.uuid4()),
        targets=targets,
        backend=backend_cfg,
        hooks=hooks,
        timestamp=datetime.datetime.utcnow(),
    )
    return intent


def _run_transaction(intent: TransactionIntent) -> TransactionResult:
    """
    Execute the transaction using the core engine components.
    """
    manager = TransactionManager()
    result = manager.run(intent)
    return result


def _print_result(result: TransactionResult) -> None:
    """
    Serialize the transaction result to JSON and write it to stdout.
    """
    # The TransactionResult may be a dataclass; we convert to dict safely.
    if hasattr(result, "model_dump"):
        data = result.model_dump()
    else:
        data = result.__dict__
    json.dump(data, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


def main(argv: List[str] | None = None) -> None:
    """
    Entry point for the example usage script.
    Demonstrates discovery, intent creation, hook handling, and transaction run.
    """
    argv = argv or sys.argv[1:]
    if not argv:
        _logger.error("Usage: example_usage.py <target-file> [<target-file> ...]")
        sys.exit(1)

    try:
        # Resolve target file paths
        target_paths = [pathlib.Path(p).expanduser().resolve() for p in argv]

        # Discover configuration file starting from the first target's directory
        config_path = _discover_config(target_paths[0].parent)
        if config_path:
            _logger.info("Found configuration at %s", config_path)
            config = _load_config(config_path)
        else:
            _logger.info("No configuration file found; using defaults")
            config = {}

        # Create a temporary working directory to host snapshots and hooks
        with tempfile.TemporaryDirectory(prefix="llm-example-") as tmp_dir_str:
            tmp_dir = pathlib.Path(tmp_dir_str)

            # Prepare a hooks directory with a simple pre‑hook
            hooks_dir = _create_hook_dir(tmp_dir)

            # Build the transaction intent
            intent = _prepare_intent(
                root=tmp_dir,
                target_files=target_paths,
                hooks_dir=hooks_dir,
            )

            # Persist the intent JSON inside the transaction directory for debugging
            # (the TransactionManager will also write its own copy)
            intent_path = tmp_dir / f"intent-{intent.tx_id}.json"
            intent_path.write_text(intent.model_dump_json(), encoding="utf-8")
            _logger.debug("Wrote intent to %s", intent_path)

            # Run the transaction
            result = _run_transaction(intent)

            # Output the result
            _print_result(result)

    except Exception as exc:
        # Capture the traceback and include the line number where the exception originated
        tb = traceback.extract_tb(exc.__traceback__)
        if tb:
            filename, lineno, func, _ = tb[-1]
            _logger.error(
                "Error in %s:%d (%s): %s",
                filename,
                lineno,
                func,
                str(exc),
            )
        else:
            _logger.error("Unexpected error: %s", str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()