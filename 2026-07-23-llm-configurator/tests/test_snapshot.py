import pathlib
import hashlib
import datetime
import uuid
import json
import shutil

import pytest

from src.core.models import TransactionIntent, BackendConfig, TargetSpec, HookSpec
from src.snapshot.store import SnapshotStore, SnapshotError, Snapshot


def _sha256_path(path: pathlib.Path) -> str:
    """Return the SHA‑256 hex digest of the file at *path*."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _make_target(path: pathlib.Path) -> TargetSpec:
    """Create a ``TargetSpec`` for *path* using its current metadata."""
    return TargetSpec(
        path=str(path),
        sha256=_sha256_path(path),
        size=path.stat().st_size,
        mtime_ns=path.stat().st_mtime_ns,
    )


def _make_intent(
    root: pathlib.Path,
    targets: list[TargetSpec],
    hooks: list[HookSpec] | None = None,
) -> TransactionIntent:
    """Build a minimal ``TransactionIntent`` for the given *targets*."""
    backend_cfg = BackendConfig(type="local", options={"root": str(root)})
    return TransactionIntent(
        tx_id=str(uuid.uuid4()),
        targets=targets,
        backend=backend_cfg,
        hooks=hooks or [],
        timestamp=datetime.datetime.utcnow(),
    )


@pytest.fixture
def temp_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a fresh directory that will serve as the repository root."""
    return tmp_path


@pytest.fixture
def snapshot_store(temp_dir: pathlib.Path) -> SnapshotStore:
    """Instantiate a ``SnapshotStore`` that stores snapshots under ``temp_dir/.snapshots``."""
    snapshots_root = temp_dir / ".snapshots"
    return SnapshotStore(root=snapshots_root)


def test_create_snapshot_copies_files_and_writes_manifest(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: create two files that will be snapshotted
    file_a = temp_dir / "a.txt"
    file_b = temp_dir / "b.txt"
    file_a.write_text("alpha")
    file_b.write_text("beta")
    targets = [_make_target(file_a), _make_target(file_b)]
    intent = _make_intent(temp_dir, targets)

    # Act
    snapshot = snapshot_store.create(intent)

    # Assert: snapshot directory exists and contains a manifest
    assert snapshot.snapshot_dir.is_dir()
    manifest_path = snapshot.snapshot_dir / "manifest.json"
    assert manifest_path.is_file()

    # Manifest must list both entries with correct original paths
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)
    assert manifest["tx_id"] == intent.tx_id
    entry_paths = {e["original"] for e in manifest["entries"]}
    assert {str(file_a), str(file_b)} == entry_paths

    # Each entry must have a snapshot copy that matches the original fingerprint
    for entry in manifest["entries"]:
        original = pathlib.Path(entry["original"])
        snapshot_path = pathlib.Path(entry["snapshot"])
        assert snapshot_path.is_file()
        assert _sha256_path(original) == entry["fingerprint"]["sha256"]
        assert _sha256_path(snapshot_path) == entry["fingerprint"]["sha256"]


def test_restore_snapshot_reverts_modified_files(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: create a file and snapshot it
    target_file = temp_dir / "data.txt"
    target_file.write_text("original")
    target = _make_target(target_file)
    intent = _make_intent(temp_dir, [target])
    snapshot = snapshot_store.create(intent)

    # Modify the file after snapshot creation
    target_file.write_text("tampered")

    # Act: restore the snapshot
    snapshot_store.restore(snapshot)

    # Assert: file content matches the original snapshot
    assert target_file.read_text() == "original"


def test_snapshot_is_immutable_after_creation(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: create a file and snapshot it
    source = temp_dir / "immutable.txt"
    source.write_text("first version")
    target = _make_target(source)
    intent = _make_intent(temp_dir, [target])
    snapshot = snapshot_store.create(intent)

    # Change the source file after snapshot creation
    source.write_text("second version")

    # Load the snapshot manifest and verify the stored fingerprint still matches the first version
    manifest = json.loads((snapshot.snapshot_dir / "manifest.json").read_text(encoding="utf-8"))
    fingerprint = manifest["entries"][0]["fingerprint"]
    assert fingerprint["sha256"] == hashlib.sha256(b"first version").hexdigest()


def test_prune_removes_expired_snapshots(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: create two snapshots at different times
    old_file = temp_dir / "old.txt"
    old_file.write_text("old")
    old_intent = _make_intent(temp_dir, [_make_target(old_file)])
    old_snapshot = snapshot_store.create(old_intent)

    # Manipulate its directory timestamp to simulate an old snapshot
    old_timestamp = datetime.datetime.utcnow() - datetime.timedelta(days=10)
    old_snapshot_dir = old_snapshot.snapshot_dir
    old_snapshot_dir.touch(times=(old_timestamp.timestamp(), old_timestamp.timestamp()))

    new_file = temp_dir / "new.txt"
    new_file.write_text("new")
    new_intent = _make_intent(temp_dir, [_make_target(new_file)])
    new_snapshot = snapshot_store.create(new_intent)

    # Act: prune snapshots older than 5 days
    cutoff = datetime.datetime.utcnow() - datetime.timedelta(days=5)
    snapshot_store.prune(expired_before=cutoff)

    # Assert: old snapshot directory is removed, new one remains
    assert not old_snapshot_dir.exists()
    assert new_snapshot.snapshot_dir.is_dir()


def test_create_snapshot_fails_when_target_is_missing(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: reference a non‑existent file in the intent
    missing_path = temp_dir / "does_not_exist.txt"
    target = TargetSpec(
        path=str(missing_path),
        sha256="deadbeef",
        size=0,
        mtime_ns=0,
    )
    intent = _make_intent(temp_dir, [target])

    # Act / Assert: creating a snapshot should raise ``SnapshotError``
    with pytest.raises(SnapshotError) as exc:
        snapshot_store.create(intent)
    assert "does_not_exist.txt" in str(exc.value)


def test_restore_snapshot_raises_error_when_snapshot_is_corrupted(
    temp_dir: pathlib.Path,
    snapshot_store: SnapshotStore,
):
    # Arrange: create a valid snapshot then corrupt its manifest
    file = temp_dir / "corrupt.txt"
    file.write_text("valid")
    intent = _make_intent(temp_dir, [_make_target(file)])
    snapshot = snapshot_store.create(intent)

    # Corrupt the manifest JSON
    manifest_path = snapshot.snapshot_dir / "manifest.json"
    manifest_path.write_text("not a json", encoding="utf-8")

    # Act / Assert: restoration should raise ``SnapshotError``
    with pytest.raises(SnapshotError):
        snapshot_store.restore(snapshot)