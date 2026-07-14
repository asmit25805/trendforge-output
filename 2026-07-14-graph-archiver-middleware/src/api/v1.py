from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiojobs
import networkx as nx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.core.models import FileNode, NodeStatus, Rule, Action, ActionType, RetryPolicy
from src.core.engine import RuleEngine, apply_rules
from src.graph.graph import KnowledgeGraph
from src.downloader.http_client import Downloader

logger = logging.getLogger(__name__)

router = APIRouter()

# Dependency that provides a shared KnowledgeGraph instance
def get_graph() -> KnowledgeGraph:
    # In a real application this would be a singleton or injected via FastAPI's state.
    return router.state.graph  # type: ignore[attr-defined]

# Dependency that provides a shared Downloader instance
def get_downloader() -> Downloader:
    return router.state.downloader  # type: ignore[attr-defined]

@router.on_event("startup")
async def startup_event() -> None:
    router.state.graph = KnowledgeGraph()
    router.state.downloader = Downloader()
    router.state.engine = RuleEngine(router.state.graph, router.state.downloader)

@router.on_event("shutdown")
async def shutdown_event() -> None:
    await router.state.downloader.close()

@router.get("/nodes", response_model=List[Dict[str, Any]])
def list_nodes(graph: KnowledgeGraph = Depends(get_graph)) -> List[Dict[str, Any]]:
    return [node.dict() for node in graph.all_nodes()]

@router.post("/nodes", status_code=status.HTTP_201_CREATED)
def create_node(node: FileNode, graph: KnowledgeGraph = Depends(get_graph)) -> Dict[str, Any]:
    graph.add_node(node)
    return node.dict()

@router.get("/rules", response_model=List[Dict[str, Any]])
def list_rules(rules: List[Rule] = Depends(lambda: router.state.rules if hasattr(router.state, "rules") else [])) -> List[Dict[str, Any]]:
    return [rule.dict() for rule in rules]

@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(rule: Rule, request: Request) -> Dict[str, Any]:
    if not hasattr(request.app.state, "rules"):
        request.app.state.rules = []
    request.app.state.rules.append(rule)
    return rule.dict()

@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def run_rules(
    graph: KnowledgeGraph = Depends(get_graph),
    downloader: Downloader = Depends(get_downloader),
    request: Request,
) -> Dict[str, str]:
    rules = getattr(request.app.state, "rules", [])
    apply_rules(rules, graph, downloader)
    return {"detail": "Rules executed"}
