# ai-hub-scanner

## Overview
Continuously scans public GitHub repositories for `.awesome-ai.md` files, aggregates the entries, and publishes a live leaderboard of AI tools on GitHub Pages.

The project is fully automated via GitHub Actions and provides a tiny FastAPI health endpoint for monitoring.

## Features
- GraphQL‑based discovery of repositories that contain the target markdown file.
- Robust markdown parsing with strict schema validation using Pydantic.
- Automatic de‑duplication, scoring, and sorting of tool entries.
- Dual snapshot format: human‑readable Markdown and machine‑readable JSON.
- Zero‑cost static site hosted on GitHub Pages.
- Health check endpoint exposing last run status, counts, and error list.
- Exponential back‑off retry logic for transient network failures.

## Installation
```bash
pip install ai-hub-scanner
```

## Quick Start
```python
from src.scanner.github import GitHubScanner
from src.aggregator.engine import Aggregator
from src.cache.store import CacheStore
from src.web.renderer import render_markdown, render_json

# Scan GitHub for repositories containing `.awesome-ai.md`
scanner = GitHubScanner()
repos = scanner.scan()

# Aggregate the entries into a leaderboard
aggregator = Aggregator()
leaderboard = aggregator.aggregate(repos)

# Cache the result (optional)
cache = CacheStore()
cache.set('leaderboard', leaderboard)

# Render outputs
md = render_markdown(leaderboard)
json_output = render_json(leaderboard)
print(md)
print(json_output)
```

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
|   GitHubScanner   | ---> |   Aggregator      | ---> |   CacheStore      |
+-------------------+      +-------------------+      +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   Renderer        |
                         +-------------------+
                                 |
                                 v
                         +-------------------+
                         |   FastAPI Health  |
                         +-------------------+
```

- **GitHubScanner** – Uses the GitHub GraphQL API to discover repositories that contain an `.awesome-ai.md` file.
- **Aggregator** – Parses the markdown files, validates entries with Pydantic models, de‑duplicates, scores and sorts them.
- **CacheStore** – Simple in‑memory cache (can be swapped for Redis, file‑based cache, etc.).
- **Renderer** – Provides `render_markdown` and `render_json` helpers to generate the two snapshot formats.
- **HealthChecker** – FastAPI app exposing `/health` with the latest run status.

## API Reference
### `src.core.models`
- **RepositoryInfo** – Pydantic model representing a discovered repository.
- **ToolEntry** – Pydantic model representing a single AI tool entry.
- **Leaderboard** – Pydantic model containing a list of `ToolEntry` objects and a generation timestamp.

### `src.scanner.github`
- **GitHubScanner** – Class with a `scan()` method returning `list[RepositoryInfo]`.

### `src.aggregator.engine`
- **Aggregator** – Class with an `aggregate(repos: list[RepositoryInfo]) -> Leaderboard` method.

### `src.web.renderer`
- **render_markdown(leaderboard: Leaderboard) -> str** – Returns a markdown table representation.
- **render_json(leaderboard: Leaderboard) -> str** – Returns a JSON string representation.

### `src.cache.store`
- **CacheStore** – Simple key/value store with `get(key)` and `set(key, value)` methods.

### `src.health.check`
- **HealthChecker** – FastAPI application exposing a `/health` endpoint.

## Contributing
Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## License
This project is released under the MIT License.
