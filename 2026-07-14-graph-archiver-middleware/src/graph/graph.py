from __future__ import annotations

import logging
from typing import Dict, Iterable, List

import networkx as nx

from src.core.models import FileNode

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """In‑memory directed graph where each vertex is a :class:`FileNode` and edges represent typed relationships such as series."""

    def __init__(self) -> None:
        self._graph = nx.DiGraph()

    def add_node(self, node: FileNode) -> None:
        """Add a :class:`FileNode` to the graph.

        The node's ``id`` attribute is used as the unique identifier.
        """
        self._graph.add_node(node.id, data=node)
        logger.debug("Added node %s to KnowledgeGraph", node.id)

    def get_node(self, node_id: str) -> FileNode | None:
        """Retrieve a node by its identifier."""
        data = self._graph.nodes.get(node_id)
        return data.get("data") if data else None

    def all_nodes(self) -> Iterable[FileNode]:
        """Yield all stored :class:`FileNode` objects."""
        for _, attrs in self._graph.nodes(data=True):
            yield attrs["data"]

    def query(self, **attributes) -> List[FileNode]:
        """Simple attribute‑based query.

        Example: ``graph.query(status="queued")`` returns all nodes whose ``status`` attribute matches.
        """
        result: List[FileNode] = []
        for node in self.all_nodes():
            if all(getattr(node, key, None) == value for key, value in attributes.items()):
                result.append(node)
        logger.debug("Query %s returned %d nodes", attributes, len(result))
        return result
