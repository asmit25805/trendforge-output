import os
import sys
import json
import time
from pathlib import Path
from typing import List

# Core engine and models
from src.core.engine import ArchiveEngine
from src.core.models import SearchResult

# CLI entry points (assumed to be defined in the package)
from src.cli.commands import process_cli, search_cmd

# ----------------------------------------------------------------------
# Example usage script for session-scribe
# ----------------------------------------------------------------------


def _write_transcript(session_id: str, lines: List[str], base_dir: Path) -> Path:
    """
    Write a transcript file for *session_id* under *base_dir*.
    Returns the path to the created file.
    """
    transcript_path = base_dir / f"{session_id}.txt"
    transcript_path.write_text("".join(lines), encoding="utf-8")
    return transcript_path


def _print_search_results(results: List[SearchResult]) -> None:
    """
    Pretty‑print a list of SearchResult objects.
    """
    if not results:
        print("🔍 No matching sentences found.")
        return

    print("\n🔍 Top matches:")
    for idx, res in enumerate(results, start=1):
        doc = res.document
        print(
            f"{idx}. [{doc.session_id}] {doc.timestamp.isoformat()} – {doc.text} (score: {res.score:.2f})"
        )
    print()


def main() -> None:
    """
    Run a minimal end‑to‑end demonstration:
    1. Create a transcript file.
    2. Process it via the CLI helper.
    3. Query the index for relevant sentences.
    """
    # ------------------------------------------------------------------
    # 1️⃣  Prepare a temporary project directory
    # ------------------------------------------------------------------
    project_root = Path.cwd()
    scribe_dir = project_root / ".scribe"
    scribe_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------
    # 2️⃣  Write a sample transcript
    # ------------------------------------------------------------------
    session_id = "demo-session"
    transcript_lines = [
        "User: Hello, I need help with my API key.\n",
        "Assistant: Sure, what is the key?\n",
        "User: My API_KEY=super-secret-12345, please store it.\n",
        "Assistant: Got it. I will not expose the key.\n",
        "User: Also, my token: token-abcde should be hidden.\n",
        "Assistant: Understood.\n",
    ]

    transcript_path = _write_transcript(session_id, transcript_lines, project_root)
    print(f"✅ Transcript written to {transcript_path}")

    # ------------------------------------------------------------------
    # 3️⃣  Process the transcript via the CLI wrapper
    # ------------------------------------------------------------------
    try:
        # The CLI helper is expected to forward to ArchiveEngine internally.
        process_cli(session_id)
        print("✅ process_cli completed successfully.")
    except Exception as exc:  # pragma: no cover
        print(f"❌ process_cli failed at line {exc.__traceback__.tb_lineno}: {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 4️⃣  Search the index for a secret‑related query
    # ------------------------------------------------------------------
    query = "api key"
    try:
        results = search_cmd(query, top_k=3)
        _print_search_results(results)
    except Exception as exc:  # pragma: no cover
        print(f"❌ search_cmd failed at line {exc.__traceback__.tb_lineno}: {exc}")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 5️⃣  Show the generated summary (context.md)
    # ------------------------------------------------------------------
    summary_path = scribe_dir / "context.md"
    if summary_path.is_file():
        print("📄 Generated summary (context.md):")
        print("-" * 40)
        print(summary_path.read_text(encoding="utf-8"))
        print("-" * 40)
    else:
        print("⚠️ No summary file found; summarizer may have been disabled.")


if __name__ == "__main__":
    main()