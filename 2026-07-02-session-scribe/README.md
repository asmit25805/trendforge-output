# session-scribe

## Overview
session-scribe is a privacy‑first, offline tool that archives LLM‑assistant sessions incrementally.  
It captures raw transcript files, redacts secrets, builds a BM25 index, and produces a concise summary.  
All operations happen locally without external services, keeping user data under full control.  

## Features
- Incremental processing based on byte offsets to avoid re‑reading entire transcripts.  
- Configurable redaction rules that strip API keys, tokens, file paths, and other secrets.  
- Pure‑Python TextRank summarizer with an optional NumPy‑accelerated backend.  
- Lightweight BM25 index stored on disk for fast offline search.  
- Robust filesystem handling using `os.open` with `O_NOFOLLOW` and explicit permission checks.  
- Automatic retry with exponential backoff for transient I/O errors.  
- Detailed error logging to `.scribe/error.log` without interrupting the user workflow.  

## Installation
```bash
pip install session-scribe
```  

The package requires Python 3.9 or newer.  
Optional NumPy acceleration can be installed with:

```bash
pip install "session-scribe[accelerated]"
```  

## Quickstart
The following example demonstrates a typical workflow.  
Save it as `example_usage.py` and run it with `python example_usage.py`.

```python
import os
from datetime import datetime
from src.core.engine import ArchiveEngine
from src.redaction.redactor import Redactor
from src.summarization.summarizer import Summarizer
from src.indexing.bm25 import IndexBuilder

# Prepare a dummy transcript file
transcript_path = "session_transcript.txt"
with open(transcript_path, "w", encoding="utf-8") as f:
    f.write(
        "User: How do I list files in Linux?\n"
        "Assistant: You can use `ls -la` to list all files.\n"
        "User: My API key is abc123XYZ.\n"
        "Assistant: Remember to keep your API key secret.\n"
    )

# Initialize core components
engine = ArchiveEngine()
redactor = Redactor()
summarizer = Summarizer()
index_builder = IndexBuilder()

# Process the session
session_id = "example-session"
engine.process_session(session_id)

# Search the index
results = engine.search("list files")
print("Search results:")
for res in results:
    print(f"- {res.document.text} (score: {res.score:.2f})")

# Display the generated summary
summary_path = os.path.join(".scribe", "context.md")
print("\nGenerated summary:")
with open(summary_path, "r", encoding="utf-8") as f:
    print(f.read())
```

Expected output (exact wording may vary slightly):

```
Search results:
- Assistant: You can use `ls -la` to list all files. (score: 1.73)

Generated summary:
User: How do I list files in Linux?
Assistant: You can use `ls -la` to list all files.
```

The example shows how the engine reads new lines, redacts the API key, updates the BM25 index, and writes a concise context file.

## Architecture
```
┌───────────────┐
│  ArchiveEngine  │
└───────────────┘
        │        
        ▼        
┌───────────────┐
│    Redactor     │
└───────────────┘
        │        
        ▼        
┌───────────────┐
│   Summarizer    │
└───────────────┘
        │        
        ▼        
┌───────────────┐
│  IndexBuilder   │
└───────────────┘
```

## API Reference

### `src.core.models`

#### `Document`
```python
class Document:
    id: str
    session_id: str
    text: str
    timestamp: datetime
```
A lightweight container for a single redacted sentence.  
`id` is a stable UUID generated from the sentence content.

#### `CaptureState`
```python
class CaptureState:
    session_offsets: Dict[str, int]
    archive_version: int
```
Tracks the last processed byte offset for each session and the schema version.

#### `SearchResult`
```python
class SearchResult:
    document: Document
    score: float
```
Returned by `ArchiveEngine.search` to represent a matching sentence and its relevance score.

### `src.core.engine`

#### `ArchiveEngine`
```python
class ArchiveEngine:
    def process_session(self, session_id: str) -> None
    def search(self, query: str, top_k: int = 5) -> List[SearchResult]
```
Coordinates the full pipeline.  
`process_session` reads new transcript lines, redacts them, adds them to the index, and generates a summary.  
`search` performs a BM25 query over the persisted index and returns the top results.

### `src.redaction.redactor`

#### `Redactor`
```python
class Redactor:
    def redact(self, text: str) -> str
```
Applies all active regex patterns from the redaction rule file and returns a safe version of `text`.  
If a pattern fails, the original line is returned to avoid data loss.

### `src.summarization.summarizer`

#### `Summarizer`
```python
class Summarizer:
    def summarize(self, sentences: List[str], ratio: float = 0.2) -> List[str]
```
Extracts the most representative sentences using TextRank.  
When the optional NumPy backend is unavailable, a pure‑Python implementation is used automatically.

### `src.indexing.bm25`

#### `IndexBuilder`
```python
class IndexBuilder:
    def add_documents(self, docs: List[Document]) -> None
    def persist(self) -> None
```
Maintains an on‑disk BM25 index.  
`add_documents` merges new sentences while preserving existing term statistics.  
`persist` writes the updated index safely to the `.scribe` directory.

## Contributing
Contributions are welcome and encouraged.

1. Fork the repository at `github.com/asmit25805/session-scribe`.  
2. Create a new branch for your feature or bug fix.  
3. Run the test suite with `pytest -q` to ensure existing functionality remains intact.  
4. Add or update tests to cover your changes.  
5. Submit a pull request targeting the `main` branch.  

Please keep the following guidelines in mind:

- Follow the existing code style and type‑annotation conventions.  
- Write comprehensive docstrings for any new public API.  
- Ensure all new functionality is covered by unit tests.  
- Do not introduce external dependencies without a clear justification.  

Thank you for helping make session-scribe more robust and useful!