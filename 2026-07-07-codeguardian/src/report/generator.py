from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.models import CVEReport, Vulnerability

logger = logging.getLogger(__name__)


class ReportGenerator:
    """Generates a signed CVE report using a Jinja2 template.

    The generator fetches vulnerability data from the database, renders a JSON
    document, and signs it with HMAC‑SHA256 using the secret stored in the
    `CG_REPORT_SIGNING_SECRET` environment variable.
    """

    def __init__(self, templates_dir: Path):
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.secret = os.getenv("CG_REPORT_SIGNING_SECRET")
        if not self.secret:
            raise RuntimeError("CG_REPORT_SIGNING_SECRET environment variable is not set")

    async def generate(self, session: AsyncSession, project_id: uuid.UUID) -> CVEReport:
        # Retrieve vulnerabilities for the project
        stmt = select(Vulnerability).where(Vulnerability.project_id == project_id)
        result = await session.execute(stmt)
        vulns: List[Vulnerability] = result.scalars().all()

        # Render the report template (expects a JSON template named 'report.json.j2')
        template = self.env.get_template("report.json.j2")
        report_content = template.render(vulnerabilities=vulns, generated_at=datetime.datetime.utcnow())
        report_json = json.loads(report_content)

        # Compute HMAC signature
        signature = hmac.new(self.secret.encode(), json.dumps(report_json, sort_keys=True).encode(), hashlib.sha256).hexdigest()

        cve_report = CVEReport(
            id=uuid.uuid4(),
            project_id=project_id,
            generated_at=datetime.datetime.utcnow(),
            vulnerabilities=vulns,
            signature=signature,
        )
        session.add(cve_report)
        await session.commit()
        return cve_report
