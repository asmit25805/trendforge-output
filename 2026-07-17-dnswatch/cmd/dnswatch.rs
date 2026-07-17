use anyhow::{Context, Result};
use clap::{Parser, ArgAction};
use std::path::PathBuf;
use std::process;
use std::time::Instant;

use crate::engine::Engine;

/// Command‑line interface for **dnswatch**.
///
/// The binary reads a configuration file, starts the engine and runs until the
/// user quits (Ctrl‑C or UI quit command).  Errors are printed with a `dnswatch:`
/// prefix to aid troubleshooting.
#[derive(Parser, Debug)]
#[command(
    name = "dnswatch",
    version,
    about = "Realtime DNS propagation monitor with TUI and Prometheus metrics",
    long_about = None,
    arg_required_else_help = true
)]
struct Cli {
    /// Path to the TOML configuration file.
    #[arg(short, long, value_name = "FILE", default_value = "~/.config/dnswatch/config.toml")]
    config: String,

    /// Increase output verbosity (can be used multiple times).
    #[arg(short, long, action = ArgAction::Count)]
    verbose: u8,
}

fn expand_path(path: &str) -> PathBuf {
    // Expand a leading `~` to the user's home directory.
    if let Some(stripped) = path.strip_prefix('~') {
        if let Some(home) = dirs::home_dir() {
            return home.join(stripped);
        }
    }
    PathBuf::from(path)
}

fn init_logging(level: u8) {
    let filter = match level {
        0 => "info",
        1 => "debug",
        _ => "trace",
    };
    env_logger::Builder::new()
        .filter_level(log::LevelFilter::Info)
        .parse_filters(filter)
        .init();
}

#[tokio::main]
async fn main() -> Result<()> {
    let start = Instant::now();

    let cli = Cli::parse();

    init_logging(cli.verbose);

    let config_path = expand_path(&cli.config);

    // Construct the engine.  All heavy lifting (loading config, spawning workers,
    // starting the UI and metrics server) is encapsulated inside `Engine`.
    let mut engine = Engine::new(config_path.clone())
        .with_context(|| format!("dnswatch: failed to initialise engine with config {:?}", config_path))?;

    // Run the engine.  The call blocks until a quit command is received or an
    // unrecoverable error occurs.
    if let Err(e) = engine.run().await {
        eprintln!("dnswatch: {}", e);
        process::exit(1);
    }

    // Graceful shutdown is performed inside `Engine::run`; however, we also
    // provide an explicit shutdown path for completeness (e.g., when Ctrl‑C
    // arrives while the UI is still active).
    if let Err(e) = engine.shutdown().await {
        eprintln!("dnswatch: shutdown error – {}", e);
        process::exit(1);
    }

    // Ensure startup latency stays well below the 100 ms target.
    let elapsed = start.elapsed();
    if elapsed.as_millis() > 100 {
        log::warn!("dnswatch: startup took {} ms, consider reducing config size", elapsed.as_millis());
    }

    Ok(())
}