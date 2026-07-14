# Overview

graph‑archiver‑middleware is a self‑orchestrating download‑to‑archive service built with Python. Each file is represented as a node in an in‑memory knowledge graph, allowing rule‑driven, on‑demand retrieval without a heavyweight client. The system streams files, computes checksums, stores metadata, evaluates user‑defined rules, and archives the result to a configurable backend (local filesystem, S3, or WebDAV).

## Features
- **Rule Engine** – declarative JSON rules trigger download, transform, or archive actions based on file metadata.
- **Knowledge Graph** – lightweight NetworkX graph stores `FileNode` vertices and typed edges for relationships such as series or edition.
- **Downloader** – asynchronous HTTP/FTP streaming with checksum verification and exponential back‑off.
- **Archive Manager** – pluggable backends (local, S3, WebDAV) for persisting archived files.

## Installation
```bash
pip install graph-archiver-middleware
```

## Quick Start
```python
from src.core.models import FileNode, Rule, ActionType, RetryPolicy
from src.core.engine import RuleEngine, apply_rules
from src.graph.graph import KnowledgeGraph
from src.downloader.http_client import Downloader

# Create a knowledge graph
kg = KnowledgeGraph()

# Define a file node
node = FileNode(
    id="example.txt",
    path="/tmp/example.txt",
    size=0,
    checksum=None,
    status="queued",
    metadata={"source": "http://example.com/example.txt"},
)
kg.add_node(node)

# Define a simple rule that downloads the file
rule = Rule(
    name="download_example",
    condition=lambda n: n.status == "queued",
    actions=[{"type": "download", "params": {}}],
)
engine = RuleEngine(kg, Downloader())
engine.apply_rules([rule])
```

## API Reference
- **GET /nodes** – Retrieve all file nodes stored in the knowledge graph.
- **POST /nodes** – Add a new `FileNode` to the graph.
- **GET /rules** – List all configured rules.
- **POST /rules** – Create a new rule.
- **POST /run** – Manually trigger rule evaluation.

All endpoints are defined in `src/api/v1.py` and are mounted under the FastAPI application.

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
|   FastAPI API    | ---> |   Rule Engine    | ---> |   Downloader      |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
+-------------------+      +-------------------+      +-------------------+
| Knowledge Graph  | <--- |   Archive Manager | <--- |   Storage Backend |
+-------------------+      +-------------------+      +-------------------+
```

- **FastAPI API** – Exposes HTTP endpoints for managing nodes and rules.
- **Rule Engine** – Evaluates rules against nodes in the Knowledge Graph.
- **Downloader** – Handles asynchronous file retrieval with checksum verification.
- **Archive Manager** – Persists files to the configured backend.
- **Knowledge Graph** – In‑memory representation of files and their relationships using NetworkX.

## Contributing
Contributions are welcome! Please open issues or pull requests on the repository.

## License
This project is licensed under the MIT License.
