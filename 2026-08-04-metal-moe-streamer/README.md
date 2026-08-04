# metal-moe-streamer

metal-moe-streamer is a Swift/Metal library that streams Mixture‑of‑Experts (MoE) checkpoints from disk, generates fused kernels for arbitrary quantization, and runs large language model (LLM) inference on Apple‑silicon with sub‑2 GB RAM usage.

## Features

- **Universal checkpoint format** – A declarative JSON manifest describes expert locations, sizes, and quantization, enabling Gemma, LLaMA‑MoE, Mixtral, or any future MoE checkpoint to be loaded without code changes.
- **Pluggable abstractions** – Core abstractions (`StreamManager`, `KernelFusionBuilder`, `ExpertCache`, `QuantizationAdapter`) allow developers to extend the library without modifying the inference loop.
- **Low memory footprint** – Streaming and kernel fusion keep RAM usage below 2 GB even for multi‑gigabyte models.
- **Swift‑first API** – Fully typed Swift interfaces with detailed error handling.

## Installation

```bash
pip install metal-moe-streamer
```

## API Reference

- `StreamManager` – Manages streaming of expert tensors from disk.
- `KernelFusionBuilder` – Builds fused Metal kernels for a given quantization scheme.
- `ExpertCache` – Caches recently used expert tensors in GPU memory.
- `QuantizationAdapter` – Adapts raw tensors to the selected quantization format.
- `ModelLoader` – Parses the JSON manifest and loads expert metadata.

## Architecture

The library consists of three layers:

1. **IO Layer** – `ModelLoader` reads the manifest and provides file offsets.
2. **Streaming Layer** – `StreamManager` streams tensors on demand, optionally using `ExpertCache`.
3. **Execution Layer** – `KernelFusionBuilder` creates Metal kernels which are executed by `InferenceEngine`.

```
+-------------------+      +-------------------+      +-------------------+
|   ModelLoader     | ---> |  StreamManager    | ---> | KernelFusionBuilder|
+-------------------+      +-------------------+      +-------------------+
                                                          |
                                                          v
                                                   +-------------------+
                                                   | InferenceEngine   |
                                                   +-------------------+
```

## License

This project is licensed under the MIT License. See the LICENSE file for details.
