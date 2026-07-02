import os
import json
import click
import logging
from typing import Callable, List, Dict, Any

from src.core.engine import ArchiveEngine
from src.core.models import (
    _logger,
    _open_secure,
    _read_secure,
    register_hook,
    Hook,
)

# --------------------------------------------------------------------------- #
# Hook registration – allows external plugins to provide custom output formats
# --------------------------------------------------------------------------- #

def _default_text_formatter(results: List[Dict[str, Any]]) -> str:
    """Render search results as plain text."""
    lines = []
    for idx, item in enumerate(results, 1):
        doc = item["document"]
        score = item["score"]
        lines.append(
            f"{idx}. [{score:.4f}] {doc.session_id} – {doc.text}"
        )
    return "\n".join(lines)


def _default_json_formatter(results: List[Dict[str, Any]]) -> str:
    """Render search results as a JSON array."""
    return json.dumps(
        [
            {
                "rank": i + 1,
                "score": r["score"],
                "document": {
                    "id": r["document"].id,
                    "session_id": r["document"].session_id,
                    "text": r["document"].text,
                    "timestamp": r["document"].timestamp.isoformat(),
                },
            }
            for i, r in enumerate(results)
        ],
        indent=2,
        ensure_ascii=False,
    )


# Register built‑in formatters
register_hook("output_formatter", Hook(name="text", func=_default_text_formatter))
register_hook("output_formatter", Hook(name="json", func=_default_json_formatter))


def _get_formatter(name: str) -> Callable[[List[Dict[str, Any]]], str]:
    """Return a formatter callable for the given name, falling back to text."""
    for hook in register_hook.registry.get("output_formatter", []):
        if hook.name == name:
            return hook.func
    _logger.warning("Formatter %s not found; using text", name)
    return _default_text_formatter


# --------------------------------------------------------------------------- #
# Configuration handling – walks up the directory tree looking for cli_config.json
# --------------------------------------------------------------------------- #

_CLI_CONFIG_FILENAME = "cli_config.json"


def _discover_cli_config(start_dir: str) -> str | None:
    """Search upward from ``start_dir`` for a JSON config file."""
    current = os.path.abspath(start_dir)
    root = os.path.abspath(os.sep)
    while True:
        candidate = os.path.join(current, _CLI_CONFIG_FILENAME)
        if os.path.isfile(candidate):
            return candidate
        if current == root:
            break
        current = os.path.dirname(current)
    return None


def _load_cli_config() -> Dict[str, Any]:
    """Load CLI configuration, returning an empty dict on failure."""
    path = _discover_cli_config(os.getcwd())
    if not path:
        return {}
    try:
        fd = _open_secure(path, os.O_RDONLY)
        try:
            raw = b""
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                raw += chunk
        finally:
            os.close(fd)
        return json.loads(raw.decode())
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to load CLI config %s: %s", path, exc)
        return {}


# --------------------------------------------------------------------------- #
# CLI command implementations
# --------------------------------------------------------------------------- #

@click.group()
def cli() -> None:
    """session‑scribe command‑line interface."""


@cli.command(name="search")
@click.argument("query", type=str)
@click.option(
    "--top-k",
    default=5,
    type=int,
    help="Maximum number of results to return.",
)
@click.option(
    "--format",
    "out_format",
    default="text",
    type=click.Choice(["text", "json"]),
    help="Output format for the results.",
)
def search_cmd(query: str, top_k: int, out_format: str) -> None:
    """Search the BM25 index for *QUERY* and display the top results."""
    engine = ArchiveEngine()
    try:
        results = engine.search(query, top_k=top_k)  # type: ignore[attr-defined]
    except Exception as exc:
        _logger.error("Search failed: %s", exc)
        click.echo(f"Error: {exc}", err=True)
        raise click.Abort()
    formatter = _get_formatter(out_format)
    formatted = formatter(
        [
            {"document": r.document, "score": r.score}
            for r in results  # type: ignore[attr-defined]
        ]
    )
    click.echo(formatted)


@cli.command(name="save")
@click.argument("session_id", type=str)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate processing without persisting changes.",
)
def save_cmd(session_id: str, dry_run: bool) -> None:
    """Process a transcript for *SESSION_ID* and update the archive."""
    engine = ArchiveEngine()
    if dry_run:
        click.echo(f"[dry‑run] Would process session {session_id}")
        return
    try:
        engine.process_session(session_id)
    except Exception as exc:
        _logger.error("Processing session %s failed: %s", session_id, exc)
        click.echo(f"Error processing session {session_id}: {exc}", err=True)
        raise click.Abort()
    click.echo(f"Session {session_id} processed successfully.")


@cli.command(name="log")
@click.option(
    "--tail",
    default=20,
    type=int,
    help="Show only the last N lines of the error log.",
)
def log_cmd(tail: int) -> None:
    """Display recent entries from the engine error log."""
    log_path = os.path.join(".scribe", "error.log")
    if not os.path.isfile(log_path):
        click.echo("No error log found.")
        return
    try:
        fd = _open_secure(log_path, os.O_RDONLY)
        try:
            raw = b""
            while True:
                chunk = os.read(fd, 8192)
                if not chunk:
                    break
                raw += chunk
        finally:
            os.close(fd)
        lines = raw.decode(errors="replace").splitlines()
        for line in lines[-tail:]:
            click.echo(line)
    except Exception as exc:  # pragma: no cover
        _logger.error("Failed to read log %s: %s", log_path, exc)
        click.echo(f"Error reading log: {exc}", err=True)
        raise click.Abort()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    cli()