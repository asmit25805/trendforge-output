import argparse
import sys
from pathlib import Path
from typing import List

from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text

from src.core.models import FilePatch, Finding, ScanResult, RuntimeConfig
from src.engine.scanner import DiffScanner, run_scan
from src.store.sqlite import FindingsStore, initialize_db

_console = Console()


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="codeguard-diff", description="Incremental security analysis tool.")
    parser.add_argument("--base", required=True, help="Base git reference (e.g., main)")
    parser.add_argument("--head", required=True, help="Head git reference (e.g., feature branch)")
    parser.add_argument("--db", default=":memory:", help="Path to SQLite database file")
    parser.add_argument("--no-sandbox", action="store_true", help="Disable container sandboxing (for debugging)")
    return parser.parse_args(argv)


def _print_results(result: ScanResult) -> None:
    table = Table(title="Scan Findings", box=box.SIMPLE)
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Severity")
    table.add_column("Title")
    for f in result.findings:
        table.add_row(str(f.file_path), str(f.line), f.severity.value, f.title)
    _console.print(table)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    runtime_cfg = RuntimeConfig(
        use_apparmor=not args.no_sandbox,
        use_landlock=not args.no_sandbox,
        use_seccomp=not args.no_sandbox,
    )
    scanner = DiffScanner(runtime_cfg)
    try:
        result = run_scan(scanner, base=args.base, head=args.head)
    except Exception as exc:
        _console.print(Text(f"Error during scan: {exc}", style="bold red"))
        return 1
    _print_results(result)
    # Persist results
    conn = initialize_db(args.db)
    store = FindingsStore(conn)
    store.save_scan_result(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
