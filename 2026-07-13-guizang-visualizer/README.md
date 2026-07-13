# guizang-visualizer

## Overview

guizang-visualizer is a service that transforms textual descriptions, CSV tables, or screenshot images into Chinese‑labeled Guizang‑style illustrations. The system extracts semantic intent, builds a deterministic prompt, generates an image with a configurable diffusion model, and validates the result against a QA checklist. All pipeline stages are persisted for auditability and can be replayed for debugging.

## Features
- Supports three input modalities: free‑form text, CSV tables, and bitmap screenshots.
- Semantic extraction determines chart type, titles, data points, and visual cues.
- Deterministic prompt construction using markdown templates that can be edited without code changes.
- Integration with diffusion models for image generation.
- QA validation ensures the output meets the required standards.
- Full audit trail stored in a lightweight SQLite store.

## Installation
```bash
pip install guizang-visualizer
```

## Quick Start
```python
from src.core.models import IllustrationRequest
from src.core.engine import SkillEngine
from src.memory import MemoryStore

# Create a request
request = IllustrationRequest(
    request_id="example-001",
    description="A bar chart showing quarterly sales for 2023",
    data=[["Q1", 120], ["Q2", 150], ["Q3", 130], ["Q4", 170]],
)

# Initialise engine and memory store
memory = MemoryStore()
engine = SkillEngine(memory_store=memory)

# Process the request (this will raise NotImplementedError until image generation is implemented)
# result = engine.process(request)
```

## Architecture

```
+----------------+      +----------------+      +-------------------+
| Illustration   | ---> | PromptBuilder  | ---> | Diffusion Model   |
| Request Model  |      | (deterministic) |      | (image generation) |
+----------------+      +----------------+      +-------------------+
        |                       |                         |
        v                       v                         v
+----------------+      +----------------+      +-------------------+
| ImageValidator | <--- | QAReport Model | <--- | Generated Image   |
+----------------+      +----------------+      +-------------------+
        |
        v
+----------------+
| MemoryStore    |
+----------------+
```

The diagram above illustrates the flow from an `IllustrationRequest` through prompt construction, image generation, validation, and persistence.

## API Reference

### Core Models (`src/core/models.py`)
- **IllustrationRequest** – Input model containing `request_id`, `description`, optional `data`, and other metadata.
- **IllustrationResult** – Output model containing `request_id`, generated `image_data` (bytes), `qa_report`, and timestamps.
- **QAReport** – Validation report with fields such as `passed`, `issues`, and `validated_at`.

### Engine (`src/core/engine.py`)
- **SkillEngine** – Main class exposing the `process(request: IllustrationRequest) -> IllustrationResult` method.

### Prompt Builder (`src/prompt_builder.py`)
- **PromptBuilder** – Constructs a deterministic prompt from an `IllustrationRequest`.

### Validator (`src/validator.py`)
- **ImageValidator** – Validates generated images against the QA checklist.

### Memory Store (`src/memory/__init__.py`)
- **MemoryStore** – Simple SQLite‑backed persistence layer for requests and results.

## Contributing
Contributions are welcome! Please open issues or submit pull requests on the repository.

## License
This project is licensed under the MIT License.
