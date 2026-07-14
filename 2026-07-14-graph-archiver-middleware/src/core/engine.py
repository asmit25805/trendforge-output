from __future__ import annotations

import logging
import traceback
from typing import List

from src.core.models import Action, FileNode, Rule, RetryPolicy
from src.graph.graph import KnowledgeGraph
from src.downloader.http_client import Downloader

logger = logging.getLogger(__name__)


class RuleEngine:
    """Evaluates user‑defined rules against :class:`FileNode` metadata and triggers actions."""

    def __init__(self, graph: KnowledgeGraph, downloader: Downloader) -> None:
        self.graph = graph
        self.downloader = downloader

    def apply_rules(self, rules: List[Rule]) -> None:
        """Iterate over all nodes in the graph and apply matching rules.

        For each rule that matches a node, the corresponding actions are executed.
        Currently only the ``download`` action is implemented.
        """
        for node in self.graph.all_nodes():
            for rule in rules:
                if rule.matches(node):
                    logger.info("Rule %s matched node %s", rule.name, node.id)
                    for action in rule.actions:
                        self._execute_action(node, action)

    def _execute_action(self, node: FileNode, action: Action) -> None:
        try:
            if action.type == "download":
                url = node.metadata.get("source")
                if not url:
                    raise ValueError("Source URL not defined in node metadata")
                self.downloader.download(url, node.path, retry_policy=action.params.get("retry_policy", RetryPolicy()))
                node.update_status("completed")
                logger.info("Downloaded node %s to %s", node.id, node.path)
            else:
                logger.warning("Unsupported action type: %s", action.type)
        except Exception as exc:
            logger.error("Error executing action %s for node %s: %s", action.type, node.id, exc)
            node.update_status("failed")
            traceback.print_exc()


def apply_rules(rules: List[Rule], graph: KnowledgeGraph, downloader: Downloader) -> None:
    """Convenient functional interface required by the module export list.

    This function creates a temporary :class:`RuleEngine` instance and runs the
    supplied rules.
    """
    engine = RuleEngine(graph, downloader)
    engine.apply_rules(rules)
