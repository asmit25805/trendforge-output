use std::error::Error;
use std::io::{self, Read, Write};
use std::process;

use clap::{Parser, ValueEnum};
use colored::Colorize;
use log::{debug, error};

use ai_metrics_hud::config::loader::{load as load_config, merge as merge_config, Config, ConfigError, Provider, ProviderConfig, SegmentConfig};
use ai_metrics_hud::core::parser::{parse as parse_telemetry, extract_segments, TelemetryData, ParseError};
use ai_metrics_hud::core::renderer::{SegmentCollector, StatusLineRenderer};

/// Simple command‑line interface for the HUD binary.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Path to the configuration file.
    #[arg(short, long, default_value = "config.toml")]
    config: String,
}

fn main() -> Result<(), Box<dyn Error>> {
    // Initialise logging (simple env logger for demonstration).
    env_logger::init();
    let cli = Cli::parse();

    // Load configuration.
    let config = load_config(&cli.config).map_err(|e| {
        error!("Failed to load config: {}", e);
        e
    })?;

    // Parse telemetry from stdin.
    let telemetry = parse_telemetry(io::stdin().lock()).map_err(|e| {
        error!("Failed to parse telemetry: {}", e);
        e
    })?;

    // Extract segments.
    let segments = extract_segments(&telemetry);

    // Collect and render.
    let mut collector = SegmentCollector::new(&config);
    collector.collect(segments);
    let mut renderer = StatusLineRenderer::new(&config);
    renderer.render(&collector.segments())?;

    Ok(())
}
