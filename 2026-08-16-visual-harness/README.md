# visual‑harness

**visual‑harness** is an LLM‑driven visual UI automation framework that works on any on‑screen application via OCR and synthetic input.  It requires no device‑specific SDKs, no accessibility services beyond the minimal OS permissions, and runs entirely from user space.

## Features

- **Cross‑platform** – Supports macOS, Windows, and Linux through dedicated backend implementations.
- **Vision‑first** – Uses OCR as the primary transport layer, enabling automation of any visible UI, including emulators and remote desktops.
- **Pluggable OCR** – Apple Vision on macOS, Tesseract on other platforms.
- **Extensible** – Backends, OCR providers, and reporters can be added via a simple plugin system.

## Installation

```bash
pip install visual-harness
```

## Quick Start

```bash
visual-harness run --script examples/example_script.py
```

The command above runs the example script which demonstrates a zero‑configuration workflow that opens the *Settings* screen by locating a visible “Settings” icon and tapping it.

## API Reference

### Core Classes

- **Engine** – Orchestrates capture, OCR, and backend actions.
- **Backend** – Platform‑specific implementation that provides ``capture`` and ``click`` methods.
- **OCRProvider** – Performs OCR on captured frames and returns a list of :class:`UIElement` objects.
- **Session** – Holds configuration and state for a single automation run.

### Data Models

- **UIElement** – Represents a UI element discovered via OCR (identifier, bounds, text).
- **CaptureFrame** – Wrapper around a screenshot file with a timestamp.
- **AutomationCommand** – High‑level command (e.g., ``{"action": "click", "target": "Settings"}``).

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   Engine          | ---> |   Backend         | ---> |   Input Events    |
+-------------------+      +-------------------+      +-------------------+
        |                         |
        v                         v
+-------------------+      +-------------------+
|   OCRProvider     | ---> |   CaptureFrame    |
+-------------------+      +-------------------+
        |
        v
+-------------------+
|   UIElement List  |
+-------------------+
```

- **Engine** receives a list of :class:`AutomationCommand` objects.
- It asks the **Backend** to capture the current screen, producing a **CaptureFrame**.
- The **OCRProvider** processes the frame and returns a list of **UIElement** objects.
- The Engine matches commands to UIElements and instructs the Backend to emit the appropriate input events.

## Contributing

Contributions are welcome!  Please open issues or pull requests on the
[GitHub repository](https://github.com/asmit25805/visual-harness).

## License

This project is licensed under the MIT License.
