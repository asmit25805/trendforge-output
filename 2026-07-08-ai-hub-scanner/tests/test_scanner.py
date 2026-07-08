import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import pytest
from unittest.mock import MagicMock, patch

from src.core.models import RepositoryInfo
from src.scanner.github import GitHubScanner


class MockHTTPResponse:
    def __init__(self, json_data: Dict[str, Any], status_code: int = 200, headers: Optional[Dict[str, str]] = None):
        self._json = json_data
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return self._json

    def raise_for_status(self):
        if not (200 <= self.status_code < 300):
            raise httpx.HTTPStatusError("Error", request=None, response=self)


def test_github_scanner_returns_repository_info():
    # Mock the GraphQL client execute method to return a predictable payload
    mock_payload = {
        "search": {
            "nodes": [
                {
                    "name": "example-repo",
                    "owner": {"login": "example-owner"},
                    "url": "https://github.com/example-owner/example-repo",
                    "description": "An example repository",
                    "pushedAt": "2024-01-01T12:00:00Z",
                }
            ],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        }
    }

    with patch.object(GitHubScanner, "_execute_query", return_value=mock_payload):
        scanner = GitHubScanner(token="dummy")
        repos = scanner.scan()
        assert len(repos) == 1
        repo = repos[0]
        assert isinstance(repo, RepositoryInfo)
        assert repo.name == "example-repo"
        assert repo.owner == "example-owner"
        assert str(repo.html_url) == "https://github.com/example-owner/example-repo"
        assert repo.description == "An example repository"
        assert repo.pushed_at == datetime.fromisoformat("2024-01-01T12:00:00")
