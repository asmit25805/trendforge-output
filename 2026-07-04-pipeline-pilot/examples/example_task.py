import argparse
import logging
import os
import sys
from typing import Any, Dict

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from src.core.engine import Session, SessionManager
from src.core.models import Message
from src.tool.engine import ToolEngine

# --------------------------------------------------------------------------- #
# Logging configuration
# --------------------------------------------------------------------------- #

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #


def _expand_path(path: str) -> str:
    """Expand ``~`` and environment variables in *path*."""
    return os.path.expanduser(os.path.expandvars(path))


def _invoke_tool_with_retry(
    engine: ToolEngine,
    name: str,
    args: Dict[str, Any],
    max_retries: int = 3,
) -> Message:
    """
    Invoke a tool via *engine* with a simple retry loop.

    Returns a ``Message`` with role ``tool`` that contains the tool output.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            result = engine.invoke(name, args)
            # ``ToolResult`` is a dataclass; we convert it to a ``Message``.
            return Message(
                role="tool",
                content=result.output,
                tokens=int(result.metadata.get("token_cost", 0)),
            )
        except Exception as exc:  # pragma: no cover
            if attempt >= max_retries:
                logger.error("Tool %s failed after %d attempts: %s", name, attempt, exc)
                raise
            logger.warning(
                "Transient error invoking tool %s (attempt %d/%d): %s",
                name,
                attempt,
                max_retries,
                exc,
            )


def _build_task_description(csv_path: str, db_path: str, query: str) -> str:
    """
    Produce a concise natural‑language description of the overall task.
    """
    return (
        f"Load CSV data from '{csv_path}', execute the SQL query '{query}' "
        f"against the SQLite database at '{db_path}', and summarise the results."
    )


def _print_assistant_response(message: Message) -> None:
    """
    Render the final assistant message using ``rich`` for a pleasant terminal UI.
    """
    console = Console()
    header = Text("🧠 Assistant response", style="bold green")
    panel = Panel(message.content, title=header, border_style="green")
    console.print(panel)


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    """
    Demonstrates a minimal pipeline‑pilot workflow:

    1. Load a CSV file.
    2. Run a SQL query against a SQLite database.
    3. Feed the tool outputs to a fresh Session.
    4. Print the final assistant response.
    """
    parser = argparse.ArgumentParser(
        prog="pipeline-pilot-example",
        description="Demo: load a CSV, run a SQL query, and display the LLM answer.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--csv",
        type=str,
        required=True,
        help="Path to the CSV file to load (e.g. ~/data/input.csv).",
    )
    parser.add_argument(
        "-d",
        "--db",
        type=str,
        required=True,
        help="Path to the SQLite database file (e.g. ~/data/database.db).",
    )
    parser.add_argument(
        "-q",
        "--query",
        type=str,
        required=True,
        help="SQL query to execute against the database (e.g. \"SELECT * FROM users\").",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging for debugging.",
    )
    args = parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    # ------------------------------------------------------------------- #
    # Resolve file system paths
    # ------------------------------------------------------------------- #
    csv_path = _expand_path(args.csv)
    db_path = _expand_path(args.db)

    # ------------------------------------------------------------------- #
    # Initialise core components
    # ------------------------------------------------------------------- #
    tool_engine = ToolEngine()
    session_manager = SessionManager()

    # ------------------------------------------------------------------- #
    # Execute tools with retry semantics
    # ------------------------------------------------------------------- #
    try:
        csv_message = _invoke_tool_with_retry(
            tool_engine, "csv_load", {"path": csv_path}
        )
        sql_message = _invoke_tool_with_retry(
            tool_engine,
            "sql_run",
            {"connection": db_path, "query": args.query},
        )
    except Exception as exc:
        logger.error("Tool execution failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------- #
    # Create a fresh session and seed it with system prompt + user task
    # ------------------------------------------------------------------- #
    task_description = _build_task_description(csv_path, db_path, args.query)
    session: Session = session_manager.new_session(task_description, mode="default")

    # ------------------------------------------------------------------- #
    # Append tool messages to the session history
    # ------------------------------------------------------------------- #
    for msg in (csv_message, sql_message):
        if hasattr(session, "add_message"):
            session.add_message(msg)  # type: ignore[attr-defined]
        else:
            # Fallback to direct list manipulation if the API differs
            session.messages.append(msg)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------- #
    # Run the LLM turn loop (the Session implementation is expected to handle
    # reflection, memory retrieval, and sub‑agent delegation internally).
    # ------------------------------------------------------------------- #
    try:
        final_message: Message = session.run()  # type: ignore[attr-defined]
    except Exception as exc:
        logger.error("Session execution failed: %s", exc)
        sys.exit(1)

    # ------------------------------------------------------------------- #
    # Present the result
    # ------------------------------------------------------------------- #
    _print_assistant_response(final_message)


if __name__ == "__main__":
    main()