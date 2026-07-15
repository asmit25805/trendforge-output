import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from loguru import logger

from src.core.models import HuntReport, ReportBundle


class ReportGenerator:
    """Generates a signed report bundle.

    The implementation is deliberately lightweight – it serialises the
    :class:`HuntReport` to JSON, optionally signs the payload (signature omitted
    for brevity), and returns a :class:`ReportBundle`.
    """

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or Path("reports")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    def generate(self, report: HuntReport) -> ReportBundle:
        self.logger.info("Generating report bundle for target %s", report.target.hostname)
        payload = report.dict()
        json_bytes = json.dumps(payload, indent=2).encode("utf-8")
        timestamp = datetime.utcnow().isoformat()
        filename = f"report_{report.target.hostname}_{timestamp}.json"
        path = self.output_dir / filename
        path.write_bytes(json_bytes)
        # Placeholder for a real cryptographic signature.
        signature = None
        bundle = ReportBundle(report=report, signature=signature, metadata={"path": str(path)})
        return bundle
