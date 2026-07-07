import os
import uuid
import hashlib
import hmac
import json
import pytest
from unittest.mock import AsyncMock, patch

from src.core.models import Project, Vulnerability, CVEReport, Severity
from src.report.generator import ReportGenerator

@pytest.fixture
def signing_secret():
    secret = "test-secret"
    os.environ["CG_REPORT_SIGNING_SECRET"] = secret
    return secret

@pytest.fixture
def dummy_project():
    return Project(
        id=uuid.uuid4(),
        name="demo",
        repo_url="https://github.com/example/demo",
        owner_id=uuid.uuid4(),
    )

@pytest.fixture
def dummy_vulnerabilities(dummy_project):
    return [
        Vulnerability(
            id=uuid.uuid4(),
            scan_task_id=uuid.uuid4(),
            severity=Severity.HIGH,
            description="Test vulnerability",
            file_path="app/main.py",
            line_number=42,
        )
    ]

@pytest.fixture
def templates_dir(tmp_path):
    # Create a minimal Jinja2 template that outputs JSON
    template_content = """{{ {
        'generated_at': generated_at.isoformat(),
        'vulnerabilities': [
            {
                'severity': v.severity.value,
                'description': v.description,
                'file_path': v.file_path,
                'line_number': v.line_number,
            } for v in vulnerabilities
        ]
    } | tojson }}"""
    (tmp_path / "report.json.j2").write_text(template_content)
    return tmp_path

@pytest.mark.asyncio
async def test_report_generation(signing_secret, dummy_project, dummy_vulnerabilities, templates_dir):
    generator = ReportGenerator(templates_dir)
    mock_session = AsyncMock()
    # Mock the DB query to return our dummy vulnerabilities
    mock_session.execute.return_value.scalars.return_value.all.return_value = dummy_vulnerabilities

    report = await generator.generate(mock_session, dummy_project.id)

    # Verify that the report contains the expected data
    assert isinstance(report, CVEReport)
    assert report.project_id == dummy_project.id
    assert report.vulnerabilities == dummy_vulnerabilities

    # Verify signature correctness
    report_dict = {
        "generated_at": report.generated_at.isoformat(),
        "vulnerabilities": [
            {
                "severity": v.severity.value,
                "description": v.description,
                "file_path": v.file_path,
                "line_number": v.line_number,
            }
            for v in dummy_vulnerabilities
        ],
    }
    expected_signature = hmac.new(
        signing_secret.encode(),
        json.dumps(report_dict, sort_keys=True).encode(),
        hashlib.sha256,
    ).hexdigest()
    assert report.signature == expected_signature
