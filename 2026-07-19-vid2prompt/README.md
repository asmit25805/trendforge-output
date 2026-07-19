# vid2prompt

## Overview
vid2prompt is a command‑line tool that transforms any video into a compact, LLM‑ready visual prompt.  
It extracts scene‑aware keyframes, runs optional OCR, aligns Whisper transcripts, and packages everything into a single JSON payload with embedded images.  
All processing happens locally, preserving privacy and eliminating external API calls.

The project targets developers who need to feed rich visual context to large language models without dealing with heavyweight video preprocessing pipelines.

## Features
- **Scene detection** using fast perceptual‑hash analysis.  
- **Frame deduplication** to reduce token count while keeping visual continuity.  
- **Optional OCR** powered by Tesseract for on‑screen text extraction.  
- **Audio transcription** with Whisper (or faster‑whisper) aligned to frame timestamps.  
- **Self‑contained JSON output** with base64‑encoded images, ready for direct LLM ingestion.  
- **Configurable strict mode** that treats any warning as a fatal error.  
- **Automatic temporary workspace cleanup** guaranteeing no leftover artifacts.  
- **Extensible architecture** allowing custom detectors, deduplication strategies, or transcription back‑ends.

## Installation
```bash
pip install vid2prompt
```
The package requires `ffmpeg` to be available on the system path. Verify installation with:
```bash
ffmpeg -version
```
If `ffmpeg` is missing, install it via your package manager (e.g., `apt-get install ffmpeg` on Debian/Ubuntu).

## Quickstart
Run the tool on a sample video:

```bash
vid2prompt samples/example.mp4 --ocr --strict
```

Expected console output (colors omitted for brevity):

```
[INFO] Starting vid2prompt for samples/example.mp4
[INFO] Extracting frames to temporary directory...
[INFO] Detecting scenes...
[INFO] Deduplicating frames within each scene...
[INFO] Running OCR on 12 frames...
[INFO] Transcribing audio with Whisper...
[INFO] Generating prompt package...
[INFO] Writing output to output.json
[INFO] Process completed successfully
```

The resulting `output.json` contains:

```json
{
  "video_path": "samples/example.mp4",
  "frames": [
    {
      "path": "/tmp/vid2prompt/frame_001.jpg",
      "timestamp": 0.0,
      "phash": "a1b2c3d4e5f60789",
      "ocr_text": "Welcome to the tutorial",
      "scene_id": 0
    }
    // … more frames …
  ],
  "scenes": [
    {
      "id": 0,
      "start_idx": 0,
      "end_idx": 15,
      "confidence": 0.92,
      "keyframe": { /* reference to a FrameMetadata object */ }
    }
    // … more scenes …
  ],
  "transcript": [
    {
      "start": 0.0,
      "end": 3.5,
      "text": "Hello and welcome to this video.",
      "speaker": "Speaker 1"
    }
    // … more segments …
  ],
  "metadata": {
    "title": "Example Video",
    "tags": ["demo", "tutorial"]
  },
  "errors": []
}
```

### Running without OCR
```bash
vid2prompt samples/example.mp4
```
The `ocr_text` fields will be empty strings, and processing will be faster.

### Using a custom output directory
```bash
vid2prompt samples/example.mp4 --output-dir results/
```
All generated files, including the JSON payload and any auxiliary archives, will be placed under `results/`.

## Architecture
```
┌───────────────────┐
│   VideoProcessor    │
└───────────────────┘
          │          
          ▼          
┌───────────────────┐
│    SceneDetector    │
└───────────────────┘
          │          
          ▼          
┌───────────────────┐
│  FrameDeduplicator  │
└───────────────────┘
          │          
          ▼          
┌───────────────────┐
│     Transcriber     │
└───────────────────┘
          │          
          ▼          
┌───────────────────┐
│   PromptGenerator   │
└───────────────────┘
```

The diagram illustrates the linear flow of data from raw video to the final prompt package. Each component lives in its own module under `src/`, keeping responsibilities isolated and testable.

## API Reference

### `src/core/engine.py`

#### class `VideoProcessor`
```python
class VideoProcessor:
    def __init__(self, config: Config) -> None
    """
    Initialise the processor with a configuration object that controls
    extraction, scene detection, deduplication, OCR, and transcription options.
    """

    def process(self, video_path: str) -> PromptPackage
    """
    Execute the full pipeline for the given video file and return a
    PromptPackage containing frames, scenes, transcript, and any collected errors.
    """
```

**Key behaviour**
- Creates a temporary work directory using a context manager.  
- Calls `SceneDetector.detect`, `FrameDeduplicator.dedup`, `Transcriber.transcribe`, and `PromptGenerator.generate` in order.  
- Aggregates errors from each stage into the `errors` list of the final package.  
- Honors the `--strict` flag: any non‑critical warning raises a `FatalError` and aborts execution.

### `src/prompt/generator.py`

#### class `PromptGenerator`
```python
class PromptGenerator:
    def __init__(self, embed_images: bool = True) -> None
    """
    Configure whether images are embedded as base64 strings (default) or referenced
    by file path. Embedding produces a single‑file JSON payload.
    """

    def generate(self, package: PromptPackage) -> dict
    """
    Convert a PromptPackage into a serialisable dictionary ready for JSON export.
    The output includes base64‑encoded images (if enabled), OCR text, scene metadata,
    and the aligned transcript. Errors are preserved under the top‑level "errors"
    key.
    """
```

**Implementation highlights**
- Reads each `FrameMetadata.path`, encodes the image to base64, and replaces the path with the encoded string when `embed_images` is True.  
- Collates scene information, ensuring each scene’s `keyframe` references the deduplicated frame.  
- Merges transcript segments with scene boundaries to provide per‑scene subtitles.  
- Returns a plain Python `dict` that can be passed to `json.dump`.

### Supporting Types (`src/core/models.py`)

All public data models are defined in `src/core/models.py` and imported by the above classes:

- `FrameMetadata` – stores per‑frame information, including optional OCR text.  
- `Scene` – groups frames, holds confidence scores, and designates a representative keyframe.  
- `TranscriptSegment` – represents a Whisper‑generated subtitle with optional speaker label.  
- `PromptPackage` – aggregates all data for final payload generation.

## Contributing
Contributions are welcome. Follow these steps to submit a change:

1. **Fork** the repository on GitHub.  
2. **Create** a new branch for your feature or bug fix.  
3. **Run** the test suite locally: `pytest -q`. All tests must pass.  
4. **Ensure** code style compliance with `ruff check .`.  
5. **Commit** your changes with clear messages.  
6. **Open** a pull request targeting the `main` branch.  

The CI workflow automatically validates formatting, runs the test suite, and checks for type safety. Review feedback from maintainers and iterate until the PR is approved.

---  

*End of README*