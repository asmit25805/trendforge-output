import time
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from docker.errors import APIError

from src.core.models import BoxSpec, ProvisionError
from src.provisioner import (
    _container_name,
    _spec_hash,
    BoxProvisioner,
    ProvisionedBox,
)


def test_spec_hash_is_deterministic():
    spec1 = BoxSpec(
        image="python:3.12-slim",
        env={"VAR": "value"},
        ports=[8080],
        volumes=[("/host", "/container")],
        resources={"cpu": "1", "memory": "512m"},
    )
    spec2 = BoxSpec(
        image="python:3.12-slim",
        env={"VAR": "value"},
        ports=[8080],
        volumes=[("/host", "/container")],
        resources={"cpu": "1", "memory": "512m"},
    )
    hash1 = _spec_hash(spec1)
    hash2 = _spec_hash(spec2)
    assert isinstance(hash1, str) and isinstance(hash2, str)
    assert hash1 == hash2

    # Changing any field must change the hash
    spec3 = BoxSpec(
        image="python:3.12-slim",
        env={"VAR": "different"},
        ports=[8080],
        volumes=[("/host", "/container")],
        resources={"cpu": "1", "memory": "512m"},
    )
    assert _spec_hash(spec3) != hash1


def test_container_name_has_prefix_and_hash_length():
    name = _container_name("abcdef1234567890")
    assert name.startswith("devbox_")
    # hash part should be exactly the first 12 characters passed in
    assert name == "devbox_abcdef123456"


def test_provision_reuses_existing_container_when_idempotent(monkeypatch):
    mock_container = MagicMock()
    mock_container.id = "container123"
    mock_container.attrs = {"Created": 1_600_000_000.0}

    mock_client = MagicMock()
    mock_client.containers.get.return_value = mock_container

    provisioner = BoxProvisioner(docker_client=mock_client)

    # Force idempotency to be True
    monkeypatch.setattr(provisioner, "ensure_idempotent", lambda name: True)

    spec = BoxSpec(
        image="python:3.12-slim",
        env={},
        ports=[],
        volumes=[],
        resources={},
    )
    box = provisioner.provision(spec)

    assert isinstance(box, ProvisionedBox)
    assert box.container_id == "container123"
    assert box.name.startswith("devbox_")
    assert box.spec is spec
    # age_ms should be close to zero because we used a fixed timestamp
    assert 0 <= box.age_ms < 1000

    mock_client.containers.get.assert_called_once_with(box.name)


def test_provision_creates_new_container_when_not_idempotent(monkeypatch):
    mock_container = MagicMock()
    mock_container.id = "newcontainer456"
    mock_container.attrs = {"Created": 1_600_000_100.0}

    mock_client = MagicMock()
    # ensure_idempotent will be forced to False
    provisioner = BoxProvisioner(docker_client=mock_client)

    monkeypatch.setattr(provisioner, "ensure_idempotent", lambda name: False)

    # Stub the private _create_container to return our mock container
    def fake_create(name, spec):
        return mock_container

    monkeypatch.setattr(provisioner, "_create_container", fake_create)

    spec = BoxSpec(
        image="python:3.12-slim",
        env={"FOO": "bar"},
        ports=[8080],
        volumes=[("/tmp", "/data")],
        resources={"cpu": "2"},
    )
    box = provisioner.provision(spec)

    assert isinstance(box, ProvisionedBox)
    assert box.container_id == "newcontainer456"
    assert box.name.startswith("devbox_")
    assert box.spec is spec
    # Verify that the container creation stub was called with expected arguments
    assert provisioner._create_container.called  # type: ignore[attr-defined]
    # No call to containers.get because idempotent returned False
    mock_client.containers.get.assert_not_called()


def test_provision_retries_and_raises_provision_error(monkeypatch):
    mock_client = MagicMock()
    provisioner = BoxProvisioner(docker_client=mock_client)

    # Force idempotent to be False so provisioning attempts happen
    monkeypatch.setattr(provisioner, "ensure_idempotent", lambda name: False)

    # Make _create_container raise APIError each time
    def always_fail(name, spec):
        raise APIError("simulated failure")

    monkeypatch.setattr(provisioner, "_create_container", always_fail)

    spec = BoxSpec(
        image="python:3.12-slim",
        env={},
        ports=[],
        volumes=[],
        resources={},
    )
    start = time.time()
    with pytest.raises(ProvisionError) as excinfo:
        provisioner.provision(spec)
    elapsed = time.time() - start

    # Ensure that the error message contains the original Docker error text
    assert "simulated failure" in str(excinfo.value)

    # Verify that retries were attempted (3 attempts)
    # The _create_container function should have been called three times
    assert provisioner._create_container.call_count == 3  # type: ignore[attr-defined]

    # Backoff: 1s + 2s = ~3s (the third attempt has no sleep after failure)
    assert elapsed >= 3.0


def test_provisioned_box_age_ms_reflects_current_time(monkeypatch):
    mock_container = MagicMock()
    mock_container.id = "agecontainer789"
    # Use a timestamp far in the past
    mock_container.attrs = {"Created": 1_000_000_000.0}

    mock_client = MagicMock()
    provisioner = BoxProvisioner(docker_client=mock_client)

    monkeypatch.setattr(provisioner, "ensure_idempotent", lambda name: True)
    mock_client.containers.get.return_value = mock_container

    spec = BoxSpec(
        image="python:3.12-slim",
        env={},
        ports=[],
        volumes=[],
        resources={},
    )
    box = provisioner.provision(spec)

    # Age should be large (current time - old timestamp)
    assert box.age_ms > 0
    # Ensure age_ms is roughly equal to the elapsed milliseconds
    now_ms = int((time.time() - 1_000_000_000.0) * 1000)
    assert abs(box.age_ms - now_ms) < 2000  # allow 2 seconds tolerance