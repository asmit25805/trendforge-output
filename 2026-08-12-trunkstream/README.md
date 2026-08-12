# trunkstream

**trunkstream** is a plug‑in streaming inference framework written in C that enables execution of arbitrarily large transformer models on low‑memory devices. By streaming the BF16 trunk tensors and swapping in MXFP4‑quantized expert matrices on demand, it keeps the memory footprint bounded while preserving model quality.

## Features

- **Manifest‑driven model description** – JSON/YAML manifests define the layout of trunk shards, expert shards, and quantization back‑ends.
- **Ring‑buffer trunk streaming** – A lock‑free ring buffer prefetches BF16 trunk slices directly from SSD into memory with zero‑copy `pread`.
- **LRU expert cache** – MXFP4‑quantized expert matrices are loaded on demand, pinned during use, and evicted according to a least‑recently‑used policy.
- **Modular architecture** – Core components (`ManifestLoader`, `TrunkStreamer`, `ExpertCache`, `QuantizerBackend`, `InferenceEngine`) are cleanly separated, making it easy to replace or extend any part.

## Installation

```bash
pip install trunkstream
```

## Building from source

```bash
make all        # builds the static library and test binaries
make test       # runs the unit tests
```

## API Reference

### ManifestLoader
- `ModelManifest *load_manifest(const char *path)` – Load a JSON/YAML manifest from `path`.
- `LayerDescriptor *get_layer_descriptor(const ModelManifest *manifest, const char *layer_name)` – Retrieve a descriptor for a specific layer.

### TrunkStreamer
- `int trunk_streamer_init(const ModelManifest *manifest)` – Initialise the ring‑buffer streamer.
- `int fetch_layer(const char *layer_name, void **out_buffer, size_t *out_size)` – Prefetch a trunk slice for `layer_name`.
- `void trunk_streamer_shutdown(void)` – Clean up resources.

### ExpertCache
- `void *expert_cache_get(const char *expert_name)` – Retrieve a cached expert matrix.
- `int expert_cache_pin(const char *expert_name)` – Pin an expert matrix to prevent eviction.
- `int expert_cache_unpin(const char *expert_name)` – Unpin a previously pinned expert.

### InferenceEngine
- `int engine_run(InferenceEngine *engine, const char *prompt)` – Run generation for a given prompt.
- `int engine_step(InferenceEngine *engine)` – Perform a single inference step.
- `void engine_reset(InferenceEngine *engine)` – Reset the engine state.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
| Manifest Loader   | ---> | Trunk Streamer    | ---> | Expert Cache      |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
   Model Manifest          Ring‑buffer (BF16)        LRU Cache (MXFP4)
```

The **Manifest Loader** parses the model description and provides metadata to the **Trunk Streamer**, which continuously streams BF16 trunk tensors from storage into a lock‑free ring buffer. The **Expert Cache** holds MXFP4‑quantized expert matrices, loading them on demand and evicting the least‑recently‑used entries. The **Inference Engine** orchestrates these components to perform token generation.

## License

This project is released under the MIT License.
