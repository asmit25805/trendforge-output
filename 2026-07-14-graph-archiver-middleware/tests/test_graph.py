import pytest
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4

from src.graph.graph import KnowledgeGraph
from src.core.models import FileNode, NodeStatus

@pytest.fixture
def graph() -> KnowledgeGraph:
    """Provide a fresh KnowledgeGraph for each test."""
    return KnowledgeGraph()

def _make_node() -> FileNode:
    """Create a minimal FileNode with uninitialized metadata for testing."""
    return FileNode(
        id=str(uuid4()),
        path=Path(f"/tmp/{uuid4()}.txt"),
        size=123,
        checksum=None,
        status=NodeStatus.QUEUED,
        metadata={"source": "http://example.com/file.txt"},
    )

def test_add_and_query_node(graph: KnowledgeGraph):
    node = _make_node()
    graph.add_node(node)
    result = graph.query(status=NodeStatus.QUEUED)
    assert len(result) == 1
    assert result[0].id == node.id
