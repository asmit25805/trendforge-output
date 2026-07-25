# ai-metrics-hud

## Overview
ai-metrics-hud is a low‑latency statusline generator for any editor that uses LLM‑powered features. It consumes JSON telemetry from a language‑model provider, merges user configuration, extracts displayable segments, decorates them with a theme, and renders a single line suitable for editor statusline APIs.

Key goals:

- Sub‑100 ms startup time.
- Zero runtime dependencies beyond the Rust standard library and `serde`.
- Provider‑agnostic parsing (Claude, OpenAI, Gemini, …).
- Compile‑time plugin registration for zero‑cost extensions.
- Clear, colored error messages without stack traces.

The binary can be used directly in a pipe, e.g.:

```sh
some-llm-client --telemetry | ai-metrics-hud
```

## Installation

```sh
cargo add ai-metrics-hud
```

## Usage

```rust
use ai_metrics_hud::config::loader::{load as load_config, Config};
use ai_metrics_hud::core::parser::{parse as parse_telemetry, TelemetryData};
use ai_metrics_hud::core::renderer::{StatusLineRenderer, SegmentCollector};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let config = load_config("config.toml")?;
    let mut collector = SegmentCollector::new(&config);
    let mut renderer = StatusLineRenderer::new(&config);
    let stdin = std::io::stdin();
    let telemetry = parse_telemetry(stdin.lock())?;
    collector.collect(telemetry);
    renderer.render(&collector.segments())?;
    Ok(())
}
```

## API Reference

### `ai_metrics_hud::config::loader`
- **`Config`** – Top‑level configuration structure.
- **`load(path: &str) -> Result<Config, ConfigError>`** – Load configuration from a TOML file.
- **`merge(base: Config, overlay: Config) -> Config`** – Merge two configurations.

### `ai_metrics_hud::core::parser`
- **`TelemetryData`** – Representation of raw telemetry JSON.
- **`Segment`** – A key/value pair extracted from telemetry.
- **`parse<R: Read>(reader: R) -> Result<TelemetryData, ParseError>`** – Parse telemetry stream.
- **`extract_segments(data: &TelemetryData) -> Vec<Segment>`** – Convert telemetry into displayable segments.

### `ai_metrics_hud::core::renderer`
- **`SegmentCollector`** – Collects and filters segments according to configuration.
- **`StatusLineRenderer`** – Renders the final status line string.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   CLI (main)      | ---> |   Parser          | ---> |   Collector       |
+-------------------+      +-------------------+      +-------------------+
        |                         |                         |
        v                         v                         v
+-------------------+      +-------------------+      +-------------------+
|   Config Loader   |      |   Plugin System   |      |   Renderer        |
+-------------------+      +-------------------+      +-------------------+
```

- **CLI** parses command‑line arguments and orchestrates the flow.
- **Config Loader** reads TOML configuration and provides defaults.
- **Parser** turns the incoming JSON telemetry into `TelemetryData`.
- **Plugin System** allows compile‑time registration of custom `SegmentProvider`s.
- **Collector** filters and orders segments based on the configuration.
- **Renderer** applies theming and writes the final line to stdout.
