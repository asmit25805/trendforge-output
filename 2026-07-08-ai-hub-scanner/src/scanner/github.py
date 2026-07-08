from __future__ import annotations

import datetime
import json
import logging
import time
from typing import List, Optional

import httpx
from gql import Client, gql
from gql.transport.httpx import HTTPXTransport

from src.core.models import RepositoryInfo

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)


class GitHubScanner:
    """Scans GitHub for repositories containing an `.awesome-ai.md` file.

    The implementation uses the public GitHub GraphQL API. For the purpose of
    this open‑source package we keep the logic simple and robust – network errors
    are retried with exponential back‑off and the result is a list of
    :class:`RepositoryInfo` objects.
    """

    GITHUB_API_URL = "https://api.github.com/graphql"
    QUERY = gql(
        """
        query($cursor: String) {
          search(query: \"filename:.awesome-ai.md\", type: REPOSITORY, first: 50, after: $cursor) {
            repositoryCount
            pageInfo { hasNextPage endCursor }
            nodes {
              ... on Repository {
                name
                owner { login }
                url
                description
                pushedAt
              }
            }
          }
        }
        """
    )

    def __init__(self, token: Optional[str] = None, max_retries: int = 3, backoff_factor: float = 0.5):
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.transport = HTTPXTransport(url=self.GITHUB_API_URL, headers=self._auth_header())
        self.client = Client(transport=self.transport, fetch_schema_from_transport=True)

    def _auth_header(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {}

    def _execute_query(self, cursor: Optional[str] = None) -> dict:
        variables = {"cursor": cursor}
        for attempt in range(self.max_retries + 1):
            try:
                return self.client.execute(self.QUERY, variable_values=variables)
            except Exception as exc:
                logger.warning("GitHub query failed (attempt %s): %s", attempt + 1, exc)
                if attempt == self.max_retries:
                    raise
                time.sleep(self.backoff_factor * (2 ** attempt))

    def scan(self) -> List[RepositoryInfo]:
        """Return a list of repositories that contain an `.awesome-ai.md` file.

        The method paginates through all results and converts each node into a
        :class:`RepositoryInfo` instance.
        """
        results: List[RepositoryInfo] = []
        cursor: Optional[str] = None
        while True:
            data = self._execute_query(cursor)
            search = data.get("search", {})
            for node in search.get("nodes", []):
                repo = RepositoryInfo(
                    name=node["name"],
                    owner=node["owner"]["login"],
                    html_url=node["url"],
                    description=node.get("description"),
                    pushed_at=node["pushedAt"],
                )
                results.append(repo)
            page_info = search.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")
        logger.info("Found %s repositories with .awesome-ai.md", len(results))
        return results
