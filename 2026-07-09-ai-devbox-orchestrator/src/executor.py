from __future__ import annotations

import datetime
import json
import pathlib
import time
from typing import Dict, Iterator, List, Tuple

import docker
from docker.errors import APIError, NotFound

from src.core.models import (
    ExecutionResult,
    ExecutionTimeout,
    ProvisionError,
    SkillLoadError,
    SkillMeta,
)
from src.provisioner import ProvisionedBox, BoxSpec


class SkillExecutor:
    """
    Executes a skill inside a provisioned dev box, streams logs, and records the
    execution outcome as markdown artifacts.
    """

    def __init__(self, docker_client: docker.DockerClient | None = None) -> None:
        """
        Initialise the executor with an optional Docker client. If none is supplied,
        a client is created from the environment.
        """
        self.docker = docker_client or docker.from_env()
        self._timeline_path = self._discover_log_path()

    @staticmethod
    def _discover_log_path() -> pathlib.Path:
        """
        Walk upward from the current directory looking for a LOG.md file.
        If none is found, create one in the current working directory.
        """
        cwd = pathlib.Path.cwd()
        for parent in [cwd, *cwd.parents]:
            candidate = parent / "LOG.md"
            if candidate.is_file():
                return candidate
        # No existing LOG.md – create a new one in cwd
        new_path = cwd / "LOG.md"
        new_path.touch()
        return new_path

    def stream_logs(self, box: ProvisionedBox) -> Iterator[str]:
        """
        Yield live log lines from the container associated with ``box``.
        """
        try:
            container = self.docker.containers.get(box.container_id)
        except NotFound as exc:
            raise ProvisionError(f"Container {box.container_id} not found") from exc

        log_stream = container.logs(stream=True, follow=True)
        for raw in log_stream:
            try:
                line = raw.decode("utf-8", errors="replace")
            except AttributeError:
                line = str(raw)
            yield line.rstrip("\n")

    def record_timeline(self, event: str, details: Dict) -> None:
        """
        Append a structured timeline entry to LOG.md. The entry is a single JSON
        object on its own line, prefixed with an ISO‑8601 timestamp.
        """
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "event": event,
            "details": details,
        }
        line = json.dumps(entry, ensure_ascii=False)
        self._timeline_path.open("a", encoding="utf-8").write(line + "\n")

    def _build_env(self, skill: SkillMeta, inputs: Dict) -> Dict[str, str]:
        """
        Merge the environment defined in the skill's ``box_spec`` with the
        ``inputs`` dictionary supplied by the caller. ``inputs`` overrides any
        conflicting keys.
        """
        spec_env: Dict[str, str] = {}
        box_spec = skill.metadata.get("box_spec", {})
        if isinstance(box_spec, dict):
            spec_env = {k: str(v) for k, v in box_spec.get("env", {}).items()}
        merged = {**spec_env, **{k: str(v) for k, v in inputs.items()}}
        return merged

    def execute(
        self, skill: SkillMeta, box: ProvisionedBox, inputs: Dict
    ) -> ExecutionResult:
        """
        Run the skill's entrypoint script inside ``box``. Captures stdout/stderr,
        writes a RESULT.md artifact, records a timeline entry and returns an
        ``ExecutionResult``.
        """
        start_ts = time.time()
        script_path = skill.script_path
        if not script_path:
            raise SkillLoadError(f"Skill {skill.name} missing ``script_path``")

        env = self._build_env(skill, inputs)

        try:
            container = self.docker.containers.get(box.container_id)
        except NotFound as exc:
            raise ProvisionError(f"Container {box.container_id} not found") from exc

        exec_cmd = ["/bin/sh", script_path]
        exec_opts = {
            "cmd": exec_cmd,
            "environment": env,
            "stdout": True,
            "stderr": True,
            "stream": True,
            "demux": True,
        }

        # Execute with a hard timeout (default 15 min)
        timeout_seconds = 15 * 60
        deadline = start_ts + timeout_seconds
        output_chunks: List[str] = []
        exit_code: int | None = None

        try:
            exec_instance = container.exec_run(**exec_opts)
            for stdout, stderr in exec_instance.output:
                now = time.time()
                if now > deadline:
                    raise ExecutionTimeout(
                        f"Skill {skill.name} exceeded timeout of {timeout_seconds}s"
                    )
                if stdout:
                    output_chunks.append(stdout.decode("utf-8", errors="replace"))
                if stderr:
                    output_chunks.append(stderr.decode("utf-8", errors="replace"))
            exit_code = exec_instance.exit_code
        except APIError as exc:
            raise ProvisionError(f"Docker API error while executing {script_path}") from exc
        except ExecutionTimeout:
            # Capture whatever we have and continue to write the result file
            exit_code = -1
            self.record_timeline(
                "execution_timeout",
                {"skill": skill.name, "box": box.name, "timeout_seconds": timeout_seconds},
            )
            raise

        duration_ms = int((time.time() - start_ts) * 1000)
        combined_output = "".join(output_chunks)

        # Determine artifact location – a sibling RESULT.md next to LOG.md
        artifact_path = (
            self._timeline_path.parent
            / f"{skill.name}_{box.name}_RESULT.md"
        )
        result_md = self._render_result_md(
            skill=skill,
            success=exit_code == 0,
            exit_code=exit_code,
            duration_ms=duration_ms,
            output=combined_output,
        )
        artifact_path.write_text(result_md, encoding="utf-8")

        # Record timeline entry
        self.record_timeline(
            "skill_executed",
            {
                "skill": skill.name,
                "box": box.name,
                "exit_code": exit_code,
                "duration_ms": duration_ms,
                "artifact_path": str(artifact_path),
            },
        )

        return ExecutionResult(
            success=exit_code == 0,
            exit_code=exit_code,
            output=combined_output,
            duration_ms=duration_ms,
            artifact_path=str(artifact_path),
        )

    @staticmethod
    def _render_result_md(
        *,
        skill: SkillMeta,
        success: bool,
        exit_code: int,
        duration_ms: int,
        output: str,
    ) -> str:
        """
        Produce a markdown document summarising the execution. The front‑matter
        contains the metadata required for later parsing.
        """
        front = {
            "skill": skill.name,
            "success": success,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
        }
        front_yaml = json.dumps(front, indent=2)
        # Simple markdown with a fenced code block for the raw output
        md = (
            f"---\n{front_yaml}\n---\n\n"
            f"# Execution Result for `{skill.name}`\n\n"
            f"```\n{output.rstrip()}\n```\n"
        )
        return md