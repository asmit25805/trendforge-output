# dnswatch

## Overview

dnswatch is a realtime terminal user interface (TUI) that monitors DNS propagation, DNSSEC validation, and DoH endpoint health. It continuously probes a configurable list of resolvers, aggregates latency and validation metrics, and exposes them to Prometheus. The UI visualises resolver locations on a world map, shows latency spark‑lines, and highlights DNSSEC health.

The tool is written in Rust, leverages Tokio for asynchronous execution, and uses Ratatui for terminal rendering. It is intended for network operators, security engineers, and developers who need instant feedback on DNS infrastructure reliability.

## Features

- **Realtime probing** of any number of resolvers using UDP, TCP, or DNS‑over‑HTTPS.
- **DNSSEC validation** with detailed status reporting.
- **Prometheus exporter** exposing latency, success rates, and DNSSEC health.
- **Terminal UI** showing a world map, per‑resolver latency spark‑lines, and health indicators.

## Installation

```bash
cargo add dnswatch
```

## Usage

```bash
dnswatch --config path/to/config.toml
```

The configuration file defines the list of resolvers, probe intervals, and which protocols to use.

## API Reference

The public library API consists of the following key abstractions:

- **Engine** – orchestrates probing, state updates, and shutdown handling.
- **Probe** – performs a single DNS query using the selected transport (UDP, TCP, or DoH).
- **MetricsCollector** – aggregates results and serves them on an HTTP endpoint for Prometheus.
- **UI** – renders the realtime dashboard in the terminal.

Additional data models:

- **ResolverInfo** – static information about a resolver (IP, location, etc.).
- **QueryResult** – outcome of a single probe (latency, success, DNSSEC status).
- **MetricsSnapshot** – a snapshot of aggregated metrics for export.
- **ResolverMetrics** – per‑resolver aggregated statistics.

For detailed documentation, see the generated Rust docs (`cargo doc --open`).

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   Engine          | ---> |   MetricsCollector| ---> |   Prometheus      |
+-------------------+      +-------------------+      +-------------------+
        |                         |
        v                         v
+-------------------+      +-------------------+
|   Probe           |      |   UI (Ratatui)    |
+-------------------+      +-------------------+
```

- The **Engine** spawns a set of **Probe** tasks for each configured resolver.
- Probe results are written into a shared **AppState** which the **UI** reads to render the dashboard.
- The **MetricsCollector** periodically reads the same **AppState** and exposes the data via an HTTP endpoint for Prometheus scrapes.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## License

This project is dual‑licensed under the MIT or Apache‑2.0 licenses.
