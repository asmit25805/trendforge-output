import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.models import Job, JobStatus
from src.jobs.scheduler import JobScheduler


@pytest.fixture(autouse=True)
def clean_environment():
    """Remove any persisted SQLite DB before each test."""
    db_path = Path("./jobs.db")
    if db_path.is_file():
        db_path.unlink()
    yield
    if db_path.is_file():
        db_path.unlink()


def test_create_job_returns_uuid_and_persists():
    scheduler = JobScheduler()
    payload = {"key": "value"}
    job_id = scheduler.create(job_type="pipeline", payload=payload)

    # Verify UUID format (simple length check)
    assert isinstance(job_id, str) and len(job_id) == 36

    active = scheduler.list_active()
    assert any(job.id == job_id for job in active)

    # Verify stored payload matches input
    stored_job = next(job for job in active if job.id == job_id)
    assert stored_job.payload == payload
    assert stored_job.type == "pipeline"
    assert stored_job.status == JobStatus.PENDING


def test_update_status_changes_state_and_merges_details():
    scheduler = JobScheduler()
    job_id = scheduler.create(job_type="pipeline", payload={"initial": 1})

    # Update status with additional details
    details = {"extra": "info", "initial": 2}
    scheduler.update_status(job_id=job_id, status=JobStatus.RUNNING, details=details)

    active = scheduler.list_active()
    job = next(j for j in active if j.id == job_id)

    assert job.status == JobStatus.RUNNING
    # Payload should be merged, with new values overriding existing keys
    expected_payload = {"initial": 2, "extra": "info"}
    assert job.payload == expected_payload


def test_persistence_across_scheduler_instances():
    # Create a job with the first scheduler instance
    scheduler1 = JobScheduler()
    job_id = scheduler1.create(job_type="pipeline", payload={"persist": True})

    # Simulate process restart by creating a new scheduler object
    scheduler2 = JobScheduler()
    active = scheduler2.list_active()
    assert any(job.id == job_id for job in active)

    # Ensure the job's metadata survived
    job = next(j for j in active if j.id == job_id)
    assert job.payload == {"persist": True}
    assert job.status == JobStatus.PENDING


def test_list_active_excludes_terminal_jobs():
    scheduler = JobScheduler()
    pending_id = scheduler.create(job_type="pipeline", payload={})
    success_id = scheduler.create(job_type="pipeline", payload={})
    failed_id = scheduler.create(job_type="pipeline", payload={})

    scheduler.update_status(pending_id, JobStatus.RUNNING)
    scheduler.update_status(success_id, JobStatus.SUCCESS)
    scheduler.update_status(failed_id, JobStatus.FAILED)

    active = scheduler.list_active()
    active_ids = {job.id for job in active}
    assert pending_id in active_ids
    assert success_id not in active_ids
    assert failed_id not in active_ids


def test_update_status_raises_on_unknown_job():
    scheduler = JobScheduler()
    unknown_id = "00000000-0000-0000-0000-000000000000"
    with pytest.raises(RuntimeError) as excinfo:
        scheduler.update_status(job_id=unknown_id, status=JobStatus.RUNNING)
    assert "Job not found" in str(excinfo.value)


def test_created_and_updated_timestamps_progress_monotonically():
    scheduler = JobScheduler()
    job_id = scheduler.create(job_type="pipeline", payload={})

    # Retrieve timestamps after creation
    job_initial = next(j for j in scheduler.list_active() if j.id == job_id)
    created_at = job_initial.created_at
    updated_at = job_initial.updated_at
    assert isinstance(created_at, datetime)
    assert isinstance(updated_at, datetime)
    assert updated_at >= created_at

    # Wait a short interval and update status
    later = datetime.utcnow() + timedelta(seconds=1)
    scheduler.update_status(job_id, JobStatus.RUNNING)

    job_after = next(j for j in scheduler.list_active() if j.id == job_id)
    assert job_after.updated_at > updated_at
    # created_at should remain unchanged
    assert job_after.created_at == created_at


def test_payload_is_serialized_and_deserialized_correctly():
    scheduler = JobScheduler()
    complex_payload = {
        "list": [1, 2, 3],
        "nested": {"a": "b"},
        "number": 42,
        "bool": True,
    }
    job_id = scheduler.create(job_type="pipeline", payload=complex_payload)

    # Directly query the SQLite DB to ensure JSON storage is valid
    conn = scheduler._conn  # Access internal connection for verification
    cur = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,))
    row = cur.fetchone()
    stored_json = row["payload"]
    assert isinstance(stored_json, str)

    # Load back and compare
    loaded_payload = json.loads(stored_json)
    assert loaded_payload == complex_payload