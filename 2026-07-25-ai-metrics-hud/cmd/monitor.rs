use std::io::{self, Read, Write};
use std::process;
use std::thread::sleep;
use std::time::Duration;

use clap::{Parser, ValueEnum};
use colored::Colorize;
use log::{debug, error};

use ai_metrics_hud::config::loader::{load as load_config, merge as merge_config, Config, ConfigError, Provider, SegmentConfig};
use ai_metrics_hud::core::parser::{parse as parse_telemetry, extract_segments, TelemetryData, ParseError};
use ai_metrics_hud::core::renderer::{SegmentCollector, StatusLineRenderer};

/// Simple monitor command that reads telemetry from a file and prints the rendered line.
#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Cli {
    /// Path to the telemetry JSON file.
    #[arg(short, long)]
    input: String,

    /// Path to the configuration file.
    #[arg(short, long, default_value = "config.toml")]
    config: String,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    env_logger::init();
    let cli = Cli::parse();
    let config = load_config(&cli.config)?;
    let file = std::fs::File::open(&cli.input)?;
    let telemetry = parse_telemetry(file)?;
    let segments = extract_segments(&telemetry);
    let mut collector = SegmentCollector::new(&config);
    collector.collect(segments);
    let mut renderer = StatusLineRenderer::new(&config);
    renderer.render(&collector.segments())?;
    Ok(())
}
