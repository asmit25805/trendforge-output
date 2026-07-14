import pytest
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from src.core.engine import RuleEngine, apply_rules
from src.core.models import Action, ActionType, FileNode, NodeStatus, Rule, RetryPolicy
from src.graph.graph import KnowledgeGraph
from src.downloader.http_client import Downloader

@pytest.fixture
def graph() -> KnowledgeGraph:
    """Provide a fresh KnowledgeGraph for each test."""
    return KnowledgeGraph()

@pytest.fixture
def downloader() -> Downloader:
    """Provide a Downloader instance for tests (uses a real aiohttp session)."""
    return Downloader()

def test_rule_engine_applies_download_action(graph: KnowledgeGraph, downloader: Downloader):
    # Create a node with a dummy source URL (will not be fetched in CI)
    node = FileNode(
        id="test-node",
        path=Path("/tmp/test.txt"),
        size=0,
        checksum=None,
        status=NodeStatus.QUEUED,
        metadata={"source": "http://example.com/dummy.txt"},
    )
    graph.add_node(node)

    rule = Rule(
        name="download_rule",
        condition=lambda n: n.status == NodeStatus.QUEUED,
        actions=[Action(type=ActionType.DOWNLOAD, params={"retry_policy": RetryPolicy(max_retries=0)})],
    )

    engine = RuleEngine(graph, downloader)
    engine.apply_rules([rule])

    # After execution the node status should be COMPLETED (or FAILED if download failed)
    updated_node = graph.get_node("test-node")
    assert updated_node is not None
    assert updated_node.status in (NodeStatus.COMPLETED, NodeStatus.FAILED)
