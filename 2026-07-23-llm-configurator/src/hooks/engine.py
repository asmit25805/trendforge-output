import os
import json
import stat
import shlex
import logging
import pathlib
import subprocess
import typing as _t
from dataclasses import dataclass, field

from src.core.models import BackendConfig, HookSpec, TransactionIntent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Hook:
    """Concrete representation of a hook script ready for execution."""

    name: str
    script: pathlib.Path
    when: _t.Literal["pre", "post"]

    @property
    def is_executable(self) -> bool:
        """Return ``True`` if the script file has executable permission."""
        return bool(self.script.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))


@dataclass(frozen=True)
class HookResult:
    """Result of a hook execution."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def success(self) -> bool:
        """A hook is successful when it exits with a zero return code."""
        return self.returncode == 0


@dataclass(frozen=True)
class HookContext:
    """Minimal context passed to a hook execution."""

    tx_id: str
    intent: TransactionIntent
    env: _t.Mapping[str, str] = field(default_factory=dict)


class HookEngine:
    """Engine responsible for discovering, isolating and running user hooks."""

    def __init__(self, logger_: logging.Logger | None = None) -> None:
        self._logger = logger_ or logger

    # ----------------------------------------------------------------------
    # Discovery
    # ----------------------------------------------------------------------
    def load_hooks(self, directory: str) -> _t.List[Hook]:
        """
        Discover hook scripts under *directory*.

        A script is considered a hook when:
        * It is a regular file.
        * It has executable permission.
        * Its name does not end with ``.disabled``.
        * No parent directory contains a file named ``.disabled``.
        The hook's ``when`` attribute is inferred from the filename prefix
        ``pre_`` or ``post_``; otherwise ``pre`` is assumed.
        """
        base = pathlib.Path(directory).expanduser().resolve()
        if not base.is_dir():
            raise FileNotFoundError(f"Hook directory '{directory}' does not exist")

        hooks: _t.List[Hook] = []
        for entry in base.rglob("*"):
            if not entry.is_file():
                continue
            if entry.name.endswith(".disabled"):
                continue
            if any((parent / ".disabled").exists() for parent in entry.parents):
                continue
            if not entry.stat().st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                continue

            when: _t.Literal["pre", "post"]
            lower_name = entry.name.lower()
            if lower_name.startswith("pre_"):
                when = "pre"
                name = entry.name[4:]
            elif lower_name.startswith("post_"):
                when = "post"
                name = entry.name[5:]
            else:
                when = "pre"
                name = entry.name

            hook = Hook(name=name, script=entry, when=when)
            hooks.append(hook)
            self._logger.debug("Discovered hook: %s (%s)", hook.name, hook.when)

        return hooks

    # ----------------------------------------------------------------------
    # Execution
    # ----------------------------------------------------------------------
    def execute(self, hook: Hook, context: HookContext) -> HookResult:
        """
        Execute *hook* in a sandboxed subprocess.

        The subprocess receives a minimal environment consisting of:
        * ``PATH`` limited to ``/usr/bin:/bin``.
        * ``HOME`` set to a temporary directory.
        * ``TX_ID`` and any additional keys from ``context.env``.
        The working directory is the directory containing the hook script.
        stdout and stderr are captured and returned in a :class:`HookResult`.
        """
        if not hook.is_executable:
            raise PermissionError(f"Hook script '{hook.script}' is not executable")

        limited_env: dict[str, str] = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(pathlib.Path("/tmp")),
            "TX_ID": context.tx_id,
        }
        limited_env.update(context.env)

        cmd = [str(hook.script)]
        self._logger.debug(
            "Running hook %s with command %s in %s",
            hook.name,
            shlex.join(cmd),
            hook.script.parent,
        )

        try:
            completed = subprocess.run(
                cmd,
                cwd=hook.script.parent,
                env=limited_env,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
        except subprocess.SubprocessError as exc:
            self._logger.error("Hook %s failed to start: %s", hook.name, exc)
            raise RuntimeError(f"Failed to execute hook '{hook.name}': {exc}") from exc

        result = HookResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        if result.success:
            self._logger.info("Hook %s completed successfully", hook.name)
        else:
            self._logger.warning(
                "Hook %s exited with code %s. Stderr: %s",
                hook.name,
                result.returncode,
                result.stderr.strip(),
            )
        return result

    # ----------------------------------------------------------------------
    # Isolation verification
    # ----------------------------------------------------------------------
    def verify_isolation(self, hook: Hook) -> bool:
        """
        Verify that *hook* cannot affect the host beyond declared side‑effects.

        Checks performed:
        * The script is not setuid/setgid.
        * The script is not world‑writable.
        * The script resides under a directory that is not world‑writable.
        Returns ``True`` when all checks pass; otherwise ``False``.
        """
        mode = hook.script.stat().st_mode

        # Disallow setuid/setgid bits
        if mode & (stat.S_ISUID | stat.S_ISGID):
            self._logger.error("Hook %s has disallowed setuid/setgid bits", hook.script)
            return False

        # Disallow world‑write permissions on the script itself
        if mode & stat.S_IWOTH:
            self._logger.error("Hook %s is world‑writable", hook.script)
            return False

        # Ensure every parent directory up to the repository root is not world‑writable
        for parent in hook.script.parents:
            parent_mode = parent.stat().st_mode
            if parent_mode & stat.S_IWOTH:
                self._logger.error(
                    "Parent directory %s of hook %s is world‑writable", parent, hook.script
                )
                return False
            # Stop at repository root (assumed to be the project root)
            if (parent / ".git").exists():
                break

        self._logger.debug("Isolation checks passed for hook %s", hook.script)
        return True