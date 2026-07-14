import logging
import sys
from pathlib import Path
from typing import Any, Dict

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the router that defines all public endpoints.
from src.api.v1 import router as api_router

# Core models used for constructing payloads.
from src.core.models import ActionType, RetryPolicy, Rule, Action, FileNode, NodeStatus

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.include_router(api_router)
client = TestClient(app)

def main() -> None:
    # Create a FileNode via the API
    node_payload = {
        "id": "example-node",
        "path": "/tmp/example.txt",
        "size": 0,
        "checksum": None,
        "status": "queued",
        "metadata": {"source": "https://httpbin.org/bytes/1024"},
    }
    response = client.post("/nodes", json=node_payload)
    logger.info("Create node response: %s", response.json())

    # Define a rule that downloads the file
    rule_payload = {
        "name": "download_example",
        "condition": "lambda n: n['status'] == 'queued'",  # In real usage this would be a callable
        "actions": [{"type": "download", "params": {"retry_policy": {"max_retries": 1}}}],
        "enabled": True,
    }
    # For the purpose of the example we construct the Rule object directly
    rule = Rule(
        name="download_example",
        condition=lambda n: n.status == NodeStatus.QUEUED,
        actions=[Action(type=ActionType.DOWNLOAD, params={"retry_policy": RetryPolicy(max_retries=1)})],
    )
    client.post("/rules", json=rule.dict())

    # Trigger rule execution
    run_resp = client.post("/run")
    logger.info("Run rules response: %s", run_resp.json())

    # Verify the node status after execution
    nodes = client.get("/nodes").json()
    logger.info("All nodes: %s", nodes)

if __name__ == "__main__":
    main()
