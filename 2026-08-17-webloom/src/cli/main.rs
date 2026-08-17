use std::net::SocketAddr;
use std::process::exit;
use std::sync::Arc;

use clap::Parser;
use log::{error, info};
use tokio::signal;
use tokio::sync::Notify;

use crate::engine::{BrowserEngine, EngineConfig, EngineError, LogLevel};

/// Command‑line arguments for the WebLoom server.
///
/// The CLI mirrors the fields of `EngineConfig` and adds a `--log-level` flag
/// to control internal diagnostics.
#[derive(Parser, Debug)]
#[command(name = "webloom")]
#[command(author = "")]
#[command(version = env!("CARGO_PKG_VERSION"))]
#[command(about = "On‑demand headless browser that streams a semantic DOM tree")]
struct Cli {
    /// Address on which the engine will listen for CDP / WebDriver connections.
    #[arg(long, default_value = "127.0.0.1:9222")]
    listen_addr: SocketAddr,

    /// Maximum memory (bytes) allocated per session if a policy is not supplied.
    #[arg(long, default_value_t = 256 * 1024 * 1024)]
    max_memory: usize,

    /// Maximum CPU share (0.0‑1.0) allocated per session if a policy is not supplied.
    #[arg(long, default_value_t = 0.5)]
    max_cpu: f32,

    /// Schemes that are allowed for network requests.
    #[arg(long, value_delimiter = ',', default_value = "http,https,data")]
    allowed_schemes: Vec<String>,

    /// Block third‑party requests when true.
    #[arg(long, default_value_t = false)]
    block_third_party: bool,

    /// Verbosity of internal diagnostics.
    #[arg(long, default_value = "info")]
    log_level: LogLevel,
}

/// Constructs an `EngineConfig` from the parsed CLI arguments.
///
/// This function isolates the conversion logic so that the `main` function
/// remains focused on orchestration.
fn build_config(cli: Cli) -> EngineConfig {
    EngineConfig {
        listen_addr: cli.listen_addr,
        default_policy: crate::session::ResourcePolicy {
            max_memory: cli.max_memory,
            max_cpu: cli.max_cpu,
            allowed_schemes: cli.allowed_schemes,
            block_third_party: cli.block_third_party,
        },
        log_level: cli.log_level,
    }
}

/// Initializes the global logger based on the selected `LogLevel`.
///
/// The logger writes to stderr and respects the `RUST_LOG` environment variable,
/// falling back to the level supplied by the CLI.
fn init_logger(level: LogLevel) {
    let mut builder = env_logger::Builder::from_default_env();
    builder.filter_level(level.into());
    builder.init();
}

/// Entry point for the binary.
///
/// The function creates a `BrowserEngine`, starts it in a background task,
/// and then awaits either a termination signal or an engine failure.  On
/// fatal errors the process exits with a non‑zero status code.
#[tokio::main]
async fn main() {
    // Parse command‑line arguments.
    let cli = Cli::parse();

    // Initialise logging as early as possible.
    init_logger(cli.log_level);

    // Build the engine configuration.
    let config = build_config(cli);

    // A `Notify` used to signal shutdown to the background task.
    let shutdown_notify = Arc::new(Notify::new());

    // Clone for the signal handler.
    let shutdown_handle = Arc::clone(&shutdown_notify);

    // Spawn a task that listens for Ctrl‑C / SIGINT.
    tokio::spawn(async move {
        if let Err(e) = signal::ctrl_c().await {
            error!("failed to listen for shutdown signal: {}", e);
            // If we cannot listen for signals we abort immediately.
            exit(1);
        }
        info!("shutdown signal received");
        shutdown_handle.notify_one();
    });

    // Create the engine instance.
    let engine = match BrowserEngine::new(config) {
        Ok(e) => e,
        Err(e) => {
            error!("failed to initialise BrowserEngine: {}", e);
            exit(1);
        }
    };

    // Run the engine in a separate task so that we can react to shutdown.
    let engine_handle = tokio::spawn(async move {
        if let Err(e) = engine.run().await {
            error!("engine terminated with error: {}", e);
            // Propagate the error to the main task.
            Err(e)
        } else {
            Ok(())
        }
    });

    // Wait for either a shutdown request or the engine to finish.
    tokio::select! {
        _ = shutdown_notify.notified() => {
            info!("initiating graceful shutdown");
            // Attempt graceful shutdown; any error is logged but does not
            // affect the exit code because we already intend to stop.
            if let Err(e) = BrowserEngine::shutdown().await {
                error!("graceful shutdown failed: {}", e);
            }
        }
        result = engine_handle => {
            match result {
                Ok(Ok(())) => {
                    info!("engine exited cleanly");
                }
                Ok(Err(e)) => {
                    error!("engine exited with error: {}", e);
                    exit(1);
                }
                Err(join_err) => {
                    error!("engine task panicked: {}", join_err);
                    exit(1);
                }
            }
        }
    }

    info!("webloom server stopped");
}