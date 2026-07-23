import pathlib
import json
import uuid
import hashlib
import datetime
import os
import stat
import shutil

import pytest

from src.core.models import (
    TransactionIntent,
    BackendConfig,
    TargetSpec,
    HookSpec,
)
from src.core.engine import TransactionManager, TransactionResult
from src.backends.local import LocalBackendAdapter, BackendError
from src.hooks.engine import HookEngine
from src.snapshot.store import SnapshotStore


def _sha256_path(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_target(path: pathlib.Path) -> TargetSpec:
    return TargetSpec(
        path=str(path),
        sha256=_sha256_path(path),
        size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
    )


def _create_intent(
    tmp_dir: pathlib.Path,
    targets: list[TargetSpec],
    hooks: list[HookSpec] | None = None,
) -> TransactionIntent:
    backend_cfg = BackendConfig(type="local", options={"root": str(tmp_dir)})
    return TransactionIntent(
        tx_id=str(uuid.uuid4()),
        targets=targets,
        backend=backend_cfg,
        hooks=hooks or [],
        timestamp=datetime.datetime.utcnow(),
    )


@pytest.fixture
def temp_file(tmp_path: pathlib.Path) -> pathlib.Path:
    p = tmp_path / "sample.txt"
    p.write_text("original content")
    return p


@pytest.fixture
def backend_adapter(tmp_path: pathlib.Path) -> LocalBackendAdapter:
    cfg = BackendConfig(type="local", options={"root": str(tmp_path)})
    return LocalBackendAdapter(config=cfg)


def test_transaction_manager_runs_successfully(tmp_path: pathlib.Path, temp_file: pathlib.Path):
    # Arrange
    target = _make_target(temp_file)
    intent = _create_intent(tmp_path, [target])
    manager = TransactionManager()
    # Act
    result: TransactionResult = manager.run(intent)
    # Assert
    assert getattr(result, "success", True) is True
    # The file should be updated (simulated payload is empty, so we just check existence)
    assert temp_file.is_file()
    # Transaction directory should be removed after commit
    tx_dir = tmp_path / f".llm-configurator-transaction-{intent.tx_id}"
    assert not tx_dir.exists()


def test_transaction_manager_aborts_on_pre_hook_failure(tmp_path: pathlib.Path, temp_file: pathlib.Path):
    # Create a failing pre‑hook script
    hooks_dir = tmp_path / "hooks"
    hooks_dir.mkdir()
    hook_path = hooks_dir / "pre_fail.sh"
    hook_path.write_text("#!/usr/bin/env bash\nexit 1\n")
    hook_path.chmod(hook_path.stat().st_mode | stat.S_IXUSR)

    hook_spec = HookSpec(path=str(hook_path), when="pre")
    target = _make_target(temp_file)
    intent = _create_intent(tmp_path, [target], hooks=[hook_spec])

    manager = TransactionManager()
    result: TransactionResult = manager.run(intent)

    assert getattr(result, "success", False) is False
    # Original content must be unchanged
    assert temp_file.read_text() == "original content"
    # Transaction directory must be cleaned up
    tx_dir = tmp_path / f".llm-configurator-transaction-{intent.tx_id}"
    assert not tx_dir.exists()


def test_transaction_manager_retries_transient_backend_error(monkeypatch, tmp_path: pathlib.Path, temp_file: pathlib.Path):
    # Simulate a transient OSError on the first two writes
    call_counter = {"count": 0}

    def flaky_write(self, path: str, data: bytes, atomic: bool = True):
        if call_counter["count"] < 2:
            call_counter["count"] += 1
            raise OSError("simulated transient failure")
        # After two failures, perform a real write
        dest = pathlib.Path(self.root / path).resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        # fsync parent
        os.fsync(dest.parent.open().fileno())

    monkeypatch.setattr(LocalBackendAdapter, "write", flaky_write, raising=False)

    target = _make_target(temp_file)
    intent = _create_intent(tmp_path, [target])
    manager = TransactionManager()
    result: TransactionResult = manager.run(intent)

    assert getattr(result, "success", True) is True
    # Ensure the write was eventually performed
    assert call_counter["count"] == 2
    # File should still exist
    assert temp_file.is_file()


def test_recover_resumes_leftover_transaction(tmp_path: pathlib.Path):
    # Create a dummy transaction directory with intent.json
    tx_id = str(uuid.uuid4())
    tx_dir = tmp_path / f".llm-configurator-transaction-{tx_id}"
    tx_dir.mkdir()
    intent = TransactionIntent(
        tx_id=tx_id,
        targets=[],
        backend=BackendConfig(type="local", options={"root": str(tmp_path)}),
        hooks=[],
        timestamp=datetime.datetime.utcnow(),
    )
    intent_path = tx_dir / "intent.json"
    intent_path.write_text(json.dumps(intent.model_dump()), encoding="utf-8")
    # Ensure the file is fsynced to mimic real behavior
    with open(intent_path, "rb") as f:
        os.fsync(f.fileno())

    manager = TransactionManager()
    recovered = manager.recover()

    assert any(isinstance(r, dict) and r.get("tx_id") == tx_id for r in recovered)


def test_abort_cleans_up_and_restores_snapshot(tmp_path: pathlib.Path, temp_file: pathlib.Path):
    # Prepare a file and a snapshot by running a transaction up to the snapshot stage
    target = _make_target(temp_file)
    intent = _create_intent(tmp_path, [target])
    manager = TransactionManager()
    # Run but abort manually after snapshot creation
    result: TransactionResult = manager.run(intent)
    # Force an abort (simulate a failure after snapshot)
    manager.abort(intent.tx_id)

    # Original file must be restored to its initial content
    assert temp_file.read_text() == "original content"
    # Transaction directory must be removed
    tx_dir = tmp_path / f".llm-configurator-transaction-{intent.tx_id}"
    assert not tx_dir.exists()


def test_transaction_manager_fails_on_fatal_error(tmp_path: pathlib.Path):
    # Create a target file in a read‑only directory to trigger a fatal error
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o500)  # read & execute only
    target_path = readonly_dir / "cannot_write.txt"
    target_path.write_text("data")
    target = _make_target(target_path)
    intent = _create_intent(tmp_path, [target])
    manager = TransactionManager()
    result: TransactionResult = manager.run(intent)

    assert getattr(result, "success", True) is False
    # Ensure the transaction directory is cleaned up even on fatal error
    tx_dir = tmp_path / f".llm-configurator-transaction-{intent.tx_id}"
    assert not tx_dir.exists()
    # Restore permissions for cleanup
    readonly_dir.chmod(0o700)