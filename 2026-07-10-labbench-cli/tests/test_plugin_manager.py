import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from src.core.plugin_manager import (
    FatalError,
    PluginManager,
    PluginSpec,
    TransientError,
)


def _create_python_plugin(tmp_path: Path, name: str, code: str) -> Path:
    """Create an executable Python script that reads JSON from stdin and writes JSON to stdout."""
    script_path = tmp_path / f"{name}.py"
    script_path.write_text(textwrap.dedent(code))
    script_path.chmod(0o755)
    return script_path


def _register_plugin(manager: PluginManager, plugin_id: str, entry: Path) -> None:
    """Register a PluginSpec directly into the manager's private registry."""
    spec = PluginSpec(
        id=plugin_id,
        version="1.0.0",
        entry=str(entry),
        inputs={},
        outputs={},
        encrypted=False,
    )
    manager._plugins[plugin_id] = spec  # noqa: SLF001 – test accesses private attribute deliberately


def test_invoke_returns_parsed_output(tmp_path: Path) -> None:
    """A well‑behaved plugin should return the JSON object printed to stdout."""
    script = _create_python_plugin(
        tmp_path,
        "echo_plugin",
        """
        import json, sys
        data = json.load(sys.stdin)
        # Echo back the received payload with an added field
        data["echoed"] = True
        json.dump(data, sys.stdout)
        """,
    )
    manager = PluginManager()
    _register_plugin(manager, "echo", script)

    payload = {"msg": "hello"}
    result = manager.invoke("echo", payload)

    assert isinstance(result, dict)
    assert result["msg"] == "hello"
    assert result["echoed"] is True


def test_invoke_raises_fatal_when_plugin_not_registered(tmp_path: Path) -> None:
    """Invoking an unknown plugin identifier must raise a FatalError."""
    manager = PluginManager()
    with pytest.raises(FatalError, match="Plugin.*not found"):
        manager.invoke("nonexistent", {})


def test_plugin_spec_validation_fails_on_missing_entry(tmp_path: Path) -> None:
    """Creating a PluginSpec with a non‑existent entry path should raise a validation error."""
    missing_path = tmp_path / "does_not_exist.sh"
    with pytest.raises(ValueError, match="entry point"):
        PluginSpec(
            id="bad",
            version="0.1.0",
            entry=str(missing_path),
            inputs={},
            outputs={},
            encrypted=False,
        )


def test_invoke_raises_transient_on_nonzero_exit(tmp_path: Path) -> None:
    """A plugin that exits with a non‑zero status must be treated as a transient failure."""
    script = _create_python_plugin(
        tmp_path,
        "fail_plugin",
        """
        import sys
        sys.exit(1)
        """,
    )
    manager = PluginManager()
    _register_plugin(manager, "fail", script)

    with pytest.raises(TransientError, match="non‑zero exit"):
        manager.invoke("fail", {})


def test_invoke_respects_timeout_and_raises_transient(tmp_path: Path) -> None:
    """If a plugin runs longer than the configured timeout, a TransientError should be raised."""
    script = _create_python_plugin(
        tmp_path,
        "slow_plugin",
        """
        import time, sys, json
        time.sleep(5)  # longer than typical test timeout
        json.dump({"finished": True}, sys.stdout)
        """,
    )
    manager = PluginManager()
    _register_plugin(manager, "slow", script)

    # Monkey‑patch the manager's timeout to a short value for the test
    original_timeout = getattr(manager, "_timeout", 30)
    manager._timeout = 1  # noqa: SLF001 – adjust private attribute for test

    with pytest.raises(TransientError, match="timeout"):
        manager.invoke("slow", {})

    # Restore original timeout to avoid side effects
    manager._timeout = original_timeout  # noqa: SLF001


def test_invoke_validates_input_schema(tmp_path: Path) -> None:
    """When a plugin declares required inputs, missing keys must cause a FatalError."""
    script = _create_python_plugin(
        tmp_path,
        "schema_plugin",
        """
        import json, sys
        data = json.load(sys.stdin)
        json.dump({"ok": True}, sys.stdout)
        """,
    )
    manager = PluginManager()
    spec = PluginSpec(
        id="schema",
        version="1.0.0",
        entry=str(script),
        inputs={"required_key": "str"},
        outputs={},
        encrypted=False,
    )
    manager._plugins["schema"] = spec  # noqa: SLF001

    # Omit the required key – should raise a FatalError before subprocess execution
    with pytest.raises(FatalError, match="required_key"):
        manager.invoke("schema", {"other_key": 123})

    # Provide the required key – should succeed
    result = manager.invoke("schema", {"required_key": "value"})
    assert result == {"ok": True}