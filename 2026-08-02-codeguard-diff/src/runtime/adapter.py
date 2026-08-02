import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import List, Optional

from rich.console import Console
from rich.text import Text

from src.core.models import RuntimeConfig

_console = Console()


def _fatal_error(message: str) -> None:
    """Print a red, bold error message and exit with status code 1.

    This helper is used throughout the adapter to abort execution when a
    required host capability cannot be detected or when an unexpected error
    occurs.
    """
    _console.print(Text(message, style="bold red"))
    sys.exit(1)


class ContainerRuntimeAdapter:
    """Detect host security capabilities and configure the container runtime.

    The adapter inspects the current host for AppArmor, Landlock, and seccomp
    support. It then builds a list of runtime arguments that can be passed to
    ``subprocess.run`` when launching the sandboxed scanner.
    """

    def __init__(self, cfg: RuntimeConfig):
        self.cfg = cfg
        self.runtime_args: List[str] = []
        self._detect_capabilities()

    def _detect_capabilities(self) -> None:
        if self.cfg.use_apparmor and self._has_apparmor():
            self.runtime_args.append("--security-opt=apparmor=codeguard-profile")
        if self.cfg.use_landlock and self._has_landlock():
            self.runtime_args.append("--security-opt=landlock")
        if self.cfg.use_seccomp and self._has_seccomp():
            self.runtime_args.append("--security-opt=seccomp=codeguard-seccomp.json")

    def _has_apparmor(self) -> bool:
        return Path("/sys/module/apparmor/parameters/enabled").exists()

    def _has_landlock(self) -> bool:
        # Simple heuristic: presence of the landlock syscall file in /proc
        return any(
            "landlock" in line for line in Path("/proc/filesystems").read_text().splitlines()
        )

    def _has_seccomp(self) -> bool:
        return Path("/proc/self/status").read_text().find("Seccomp:") != -1

    def build_command(self, cmd: List[str]) -> List[str]:
        """Return the full command line with sandbox arguments applied.
        """
        return ["docker", "run", "--rm"] + self.runtime_args + cmd
