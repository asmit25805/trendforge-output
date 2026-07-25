use std::fs::File;
use std::io::{self, Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::thread::sleep;
use std::time::Duration;

use ai_metrics_hud::config::loader::{load as load_config, merge as merge_config, Config, ConfigError, Provider, SegmentConfig};
use ai_metrics_hud::core::parser::{extract_segments, parse as parse_telemetry, ParseError, Segment, TelemetryData};
use ai_metrics_hud::core::renderer::{SegmentCollector, StatusLineRenderer};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Load a sample configuration.
    let config = load_config("example_config.toml")?;
    // Simulate telemetry input.
    let json = r#"{ "provider": "demo", "timestamp": "2023-01-01T00:00:00Z", "payload": {"latency": "42ms"} }"#;
    let telemetry = parse_telemetry(Cursor::new(json))?;
    let segments = extract_segments(&telemetry);
    let mut collector = SegmentCollector::new(&config);
    collector.collect(segments);
    let mut renderer = StatusLineRenderer::new(&config);
    renderer.render(&collector.segments())?;
    Ok(())
}
