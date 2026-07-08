import pytest
from datetime import datetime, timedelta

from src.aggregator.engine import Aggregator
from src.core.models import ToolEntry, RepositoryInfo, Leaderboard


@pytest.mark.asyncio
async def test_aggregator_builds_leaderboard():
    # Prepare a fake repository that hosts a markdown table with two entries
    repo = RepositoryInfo(
        name="dummy-repo",
        owner="dummy-owner",
        html_url="https://github.com/dummy-owner/dummy-repo",
        description="Dummy repo",
        pushed_at=datetime.utcnow(),
    )

    # Mock the HTTP client used by Aggregator to return a markdown string
    markdown = (
        "| Name | Description | Category | Homepage | GitHub | Score |\n"
        "|------|-------------|----------|----------|--------|-------|\n"
        "| ToolA | A great tool | LLM | https://toola.com | https://github.com/dummy-owner/toola | 85 |\n"
        "| ToolB | Another tool | Dataset | https://toolb.com | https://github.com/dummy-owner/toolb | 90 |"
    )

    async def mock_fetch(_):
        return markdown

    aggregator = Aggregator()
    aggregator._fetch_markdown = mock_fetch  # type: ignore[attr-defined]

    leaderboard: Leaderboard = await aggregator.aggregate([repo])

    assert isinstance(leaderboard, Leaderboard)
    assert len(leaderboard.entries) == 2
    names = {e.name for e in leaderboard.entries}
    assert names == {"ToolA", "ToolB"}
    # Ensure sorting by score descending
    assert leaderboard.entries[0].score >= leaderboard.entries[1].score
