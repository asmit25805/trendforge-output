import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Sequence

from rich.console import Console

from src.core.models import (
    Finding,
    ScanResult,
    RuntimeConfig,
    Severity,
    FindingStatus,
)

_console = Console()

FINDINGS_PAGE_MAX = 100


def initialize_db(db_path: str) -> sqlite3.Connection:
    """Open a SQLite connection and ensure the schema exists.

    The function creates the required tables if they are missing. It returns a
    connection object that can be used by :class:`FindingsStore`.
    """
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    _create_schema(conn)
    return conn


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS scan_results (
            id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            runtime_config TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS findings (
            id TEXT PRIMARY KEY,
            scan_id TEXT NOT NULL REFERENCES scan_results(id) ON DELETE CASCADE,
            file_path TEXT NOT NULL,
            line INTEGER NOT NULL,
            severity TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.commit()


class FindingsStore:
    """Simple SQLite‑backed store for persisting :class:`ScanResult` objects.
    """

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_scan_result(self, result: ScanResult) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO scan_results (id, timestamp, runtime_config) VALUES (?, ?, ?)",
            (str(result.id), result.timestamp.isoformat(), result.runtime_config.json()),
        )
        for f in result.findings:
            cur.execute(
                "INSERT INTO findings (id, scan_id, file_path, line, severity, title, description, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(f.id),
                    str(result.id),
                    str(f.file_path),
                    f.line,
                    f.severity.value,
                    f.title,
                    f.description,
                    f.status.value,
                    f.created_at.isoformat(),
                ),
            )
        self.conn.commit()

    def list_findings(self, limit: int = FINDINGS_PAGE_MAX) -> List[Finding]:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT id, file_path, line, severity, title, description, status, created_at FROM findings LIMIT ?",
            (limit,),
        )
        rows = cur.fetchall()
        findings = []
        for row in rows:
            (
                fid,
                file_path,
                line,
                severity,
                title,
                description,
                status,
                created_at,
            ) = row
            findings.append(
                Finding(
                    id=uuid.UUID(fid),
                    file_path=Path(file_path),
                    line=line,
                    severity=Severity(severity),
                    title=title,
                    description=description,
                    status=FindingStatus(status),
                    created_at=datetime.fromisoformat(created_at),
                )
            )
        return findings
