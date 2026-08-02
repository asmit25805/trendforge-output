import subprocess
import re
from typing import List, Dict, Any

import requests
from rich.console import Console

from src.core.models import FilePatch, Finding, RuntimeConfig, ScanResult

_console = Console()


class DiffScanner:
    """Computes changed file patches and scans them with an LLM endpoint.

    The scanner relies on ``git diff`` to obtain the patch information. It then
    sends each patch to a configurable LLM endpoint (simulated via HTTP POST in
    this minimal implementation) and builds :class:`Finding` objects from the
    response.
    """

    def __init__(self, runtime_cfg: RuntimeConfig) -> None:
        self.runtime_cfg = runtime_cfg
        self.llm_endpoint = os.getenv("CODEGUARD_LLM_ENDPOINT", "https://example.com/scan")

    def _git_diff(self, base: str, head: str) -> str:
        """Return the raw diff between two git references.
        """
        result = subprocess.run(
            ["git", "diff", f"{base}..{head}"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    def _parse_diff(self, diff_text: str) -> List[FilePatch]:
        """Parse a unified diff into a list of :class:`FilePatch` objects.
        """
        patches: List[FilePatch] = []
        current_file: str | None = None
        added: List[int] = []
        removed: List[int] = []
        diff_lines: List[str] = []
        line_num = 0
        for line in diff_text.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[6:]
                continue
            if line.startswith("@@"):
                # Example: @@ -1,3 +1,4 @@
                m = re.search(r"\+([0-9]+),", line)
                if m:
                    line_num = int(m.group(1)) - 1
                continue
            if line.startswith("+") and not line.startswith("+++"):
                line_num += 1
                added.append(line_num)
                diff_lines.append(line)
            elif line.startswith("-") and not line.startswith("---"):
                removed.append(line_num)
                diff_lines.append(line)
            else:
                line_num += 1
        if current_file:
            patches.append(
                FilePatch(
                    file_path=Path(current_file),
                    added_lines=added,
                    removed_lines=removed,
                    diff="\n".join(diff_lines),
                )
            )
        return patches

    def _scan_patch(self, patch: FilePatch) -> List[Finding]:
        """Send a patch to the LLM endpoint and parse the response into findings.
        """
        try:
            resp = requests.post(self.llm_endpoint, json={"diff": patch.diff}, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            _console.print(f"LLM request failed: {exc}", style="bold red")
            return []
        findings: List[Finding] = []
        for item in data.get("findings", []):
            findings.append(
                Finding(
                    file_path=patch.file_path,
                    line=item.get("line", 0),
                    severity=item.get("severity", "low"),
                    title=item.get("title", "Untitled"),
                    description=item.get("description", ""),
                )
            )
        return findings

    def scan(self, base: str, head: str) -> ScanResult:
        diff_text = self._git_diff(base, head)
        patches = self._parse_diff(diff_text)
        all_findings: List[Finding] = []
        for patch in patches:
            all_findings.extend(self._scan_patch(patch))
        return ScanResult(patches=patches, findings=all_findings, runtime_config=self.runtime_cfg)


def run_scan(scanner: DiffScanner, base: str, head: str) -> ScanResult:
    """Convenience wrapper used by the CLI.
    """
    return scanner.scan(base, head)
