import argparse
import os
import sys
import time
from datetime import datetime, timezone
from typing import List

from rich.console import Console
from rich.table import Table

from src.core.models import FilePatch, Finding, ScanResult, RuntimeConfig
from src.engine.scanner import DiffScanner
from src.runtime.adapter import ContainerRuntimeAdapter
from src.store.sqlite import FindingsStore, initialize_db
from src.remediation.planner import RemediationPlanner

_console = Console()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="codeguard-diff-example",
        description="Programmatic example of scanning a Git diff and persisting findings.",
    )
    parser.add_argument(
        "-w",
        "--workspace",
        required=True,
        help="Path to the workspace (Git repository) to scan.",
    )
    parser.add_argument(
        "-b",
        "--base",
        required=True,
        help="Base Git ref (e.g., main) for the diff.",
    )
    parser.add_argument(
        "-h",
        "--head",
        required=True,
        help="Head Git ref (e.g., feature branch) for the diff.",
    )
    parser.add_argument(
        "-d",
        "--db",
        default="~/.codeguard-diff/findings.db",
        help="SQLite database file to store scan results.",
    )
    parser.add_argument(
        "--plan-remediation",
        action="store_true",
        help="After scanning, generate remediation actions for each finding.",
    )
    return parser.parse_args()


def _retry(attempts: int, func, *args, **kwargs):
    for attempt in range(attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if attempt == attempts - 1:
                raise
            delay = 1.0 * (2 ** attempt)
            _console.log(f"[yellow]Transient error ({exc}); retrying in {delay}s[/]")
            time.sleep(delay)


def _display_findings(findings: List[Finding]) -> None:
    table = Table(title="Scan Findings")
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Severity", style="magenta")
    table.add_column("File", style="green")
    table.add_column("Line", justify="right")
    table.add_column("Title", style="white")
    for f in findings:
        table.add_row(
            f.id,
            f.severity,
            f.file_path,
            str(f.line),
            f.title,
        )
    _console.print(table)


def main() -> None:
    args = _parse_args()

    # Resolve paths
    workspace_path = os.path.abspath(os.path.expanduser(args.workspace))
    db_path = os.path.expanduser(os.path.expandvars(args.db))

    # Detect runtime capabilities
    runtime_adapter = ContainerRuntimeAdapter()
    runtime_cfg: RuntimeConfig = runtime_adapter.detect_capabilities()

    # Initialise scanner
    scanner = DiffScanner(runtime_cfg=runtime_cfg)

    # Collect changed files
    patches: List[FilePatch] = scanner.collect_changes(
        repo_path=workspace_path,
        base_ref=args.base,
        head_ref=args.head,
    )
    if not patches:
        _console.print("[green]No changes detected; nothing to scan.[/]")
        sys.exit(0)

    # Scan each patch, handling transient LLM errors
    findings: List[Finding] = []
    for patch in patches:
        try:
            patch_findings = _retry(3, scanner.run_llm_scan, patch)
            findings.extend(patch_findings)
        except Exception as e:
            _console.print(
                f"[red]Failed to scan {patch.path}: {e}[/] (continuing with other patches)"
            )

    # Build ScanResult
    scan_result = ScanResult(
        scan_id=str(uuid.uuid4()),
        workspace_id=workspace_path,
        timestamp=datetime.now(timezone.utc),
        base_ref=args.base,
        head_ref=args.head,
        findings=findings,
    )

    # Persist results
    store = FindingsStore(db_path=db_path)
    store.init_schema()
    store.upsert_scan(scan_result)

    _display_findings(findings)

    # Optional remediation planning
    if args.plan_remediation and findings:
        planner = RemediationPlanner(db_path=db_path, runtime_cfg=runtime_cfg)
        for f in findings:
            try:
                action = planner.plan(f)
                _console.print(
                    f"[blue]Remediation planned for {f.id}: {action.action_id}[/]"
                )
            except Exception as e:
                _console.print(
                    f"[red]Failed to plan remediation for {f.id}: {e}[/]"
                )


if __name__ == "__main__":
    main()