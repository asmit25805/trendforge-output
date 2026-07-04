from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import pathlib
import sqlite3
import sys
import threading
from typing import Any, Callable, Dict, Tuple, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.core.models import ToolResult

logger = logging.getLogger(__name__)


class ToolEngine:
    """Executes external tools safely and returns structured :class:`ToolResult` objects.

    The engine supports three simple built‑in tools for demonstration purposes:

    - ``http_get`` – perform an HTTP GET request and return the response body.
    - ``sqlite_query`` – run a read‑only SQL query against a SQLite database.
    - ``csv_to_json`` – convert a CSV file to a JSON array.
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        logger.debug("ToolEngine created with timeout %s seconds", timeout)

    def run(self, tool_name: str, *args, **kwargs) -> ToolResult:
        """Dispatch *tool_name* to the appropriate implementation.

        Parameters
        ----------
        tool_name:
            Name of the tool to execute.
        *args, **kwargs:
            Arguments forwarded to the concrete tool implementation.
        """
        method_name = f"_tool_{tool_name}"
        if not hasattr(self, method_name):
            raise ValueError(f"Unknown tool: {tool_name}")
        method = getattr(self, method_name)
        output = method(*args, **kwargs)
        return ToolResult(tool_name=tool_name, output=output, success=True)

    # ---------------------------------------------------------------------
    # Built‑in tool implementations
    # ---------------------------------------------------------------------

    @retry(
        retry=retry_if_exception_type(httpx.HTTPError),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
    )
    def _tool_http_get(self, url: str, *, headers: Optional[Dict[str, str]] = None) -> str:
        """Perform a simple HTTP GET request and return the response text."""
        logger.info("Executing http_get for URL %s", url)
        response = httpx.get(url, headers=headers, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def _tool_sqlite_query(self, db_path: str, query: str) -> list[dict[str, Any]]:
        """Execute a read‑only SQL query against a SQLite database.

        Returns a list of rows where each row is a ``dict`` mapping column names to
        values.
        """
        logger.info("Executing sqlite_query on %s", db_path)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(query)
            rows = [dict(row) for row in cur.fetchall()]
            return rows
        finally:
            conn.close()

    def _tool_csv_to_json(self, csv_path: str) -> list[dict[str, str]]:
        """Read a CSV file and return its contents as a list of JSON objects."""
        logger.info("Converting CSV %s to JSON", csv_path)
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [row for row in reader]
