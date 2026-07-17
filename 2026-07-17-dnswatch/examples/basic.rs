use anyhow::{Context, Result};
use dnswatch::engine::Engine;
use dnswatch::probe::{Probe, ProbeOpts, ProbeType};
use dnswatch::{DnssecStatus, QueryResult, ResolverInfo};
use hickory_proto::rr::record_type::RecordType;
use std::fs;
use std::net::{IpAddr, Ipv4Addr};
use std::path::PathBuf;
use std::time::Duration;
use tokio::time;

/// Writes a minimal TOML configuration containing a single resolver to a temporary
/// file and returns the file path.
///
/// The configuration is compatible with `Engine::new`.
fn write_temp_config() -> Result<PathBuf> {
    let config = r#"
[[resolvers]]
name = "cloudflare"
ip = "1.1.1.1"
probe_type = "udp"
"#;
    let mut path = std::env::temp_dir();
    let filename = format!("dnswatch_example_{}.toml", std::process::id());
    path.push(filename);
    fs::write(&path, config).with_context(|| format!("dnswatch: failed to write temporary config to {:?}", path))?;
    Ok(path)
}

/// Performs a single DNS query using a `Probe` and prints the result.
///
/// The function demonstrates how to construct a `ResolverInfo`, instantiate a
/// `Probe`, and invoke `query`.  Errors are reported with the required `dnswatch:`
/// prefix.
async fn run_one_probe() -> Result<()> {
    let resolver = ResolverInfo {
        id: 0,
        name: "cloudflare".to_string(),
        ip: IpAddr::V4(Ipv4Addr::new(1, 1, 1, 1)),
        location: String::new(),
        coords: None,
        probe_type: ProbeType::Udp,
    };

    let probe = Probe::new(resolver);
    let opts = ProbeOpts::default();

    let result: QueryResult = probe
        .query("cloudflare.com", RecordType::A, opts)
        .await
        .with_context(|| "dnswatch: probe query failed")?;

    println!("Probe result for resolver {}:", result.resolver_id);
    println!("  Records: {:?}", result.records);
    println!("  TTL: {}", result.ttl);
    println!("  DNSSEC status: {:?}", result.dnssec_status);
    println!("  Latency: {} ms", result.latency_ms);
    Ok(())
}

/// Starts the full engine for a short, bounded period.
///
/// The engine loads the temporary configuration, spawns workers, and runs the UI
/// and metrics subsystem.  After the specified duration the engine is shut down
/// gracefully.
async fn run_engine_for(duration: Duration) -> Result<()> {
    let config_path = write_temp_config()?;
    let mut engine = Engine::new(config_path.clone())
        .with_context(|| format!("dnswatch: failed to initialise engine with config {:?}", config_path))?;

    // Run the engine in a background task so we can stop it after `duration`.
    let engine_handle = tokio::spawn(async move {
        if let Err(e) = engine.run().await {
            eprintln!("dnswatch: engine run error – {}", e);
        }
    });

    // Wait for the requested monitoring window.
    time::sleep(duration).await;

    // Signal shutdown.  The engine exposes an async `shutdown` method that
    // performs a graceful stop of workers and flushes pending metrics.
    // The method is called on a new `Engine` instance that shares the same
    // internal state via static storage.
    let mut shutdown_engine = Engine::new(config_path)?;
    if let Err(e) = shutdown_engine.shutdown().await {
        eprintln!("dnswatch: shutdown error – {}", e);
    }

    // Ensure the background task finishes.
    if let Err(e) = engine_handle.await {
        eprintln!("dnswatch: engine task join error – {}", e);
    }

    Ok(())
}

/// Entry point for the example.
///
/// The program first runs a single probe to illustrate low‑level usage, then
/// starts the full engine for five seconds before exiting.
#[tokio::main]
async fn main() -> Result<()> {
    println!("=== Single probe demonstration ===");
    run_one_probe().await?;

    println!("\n=== Engine demonstration (5 s) ===");
    run_engine_for(Duration::from_secs(5)).await?;

    println!("example completed successfully");
    Ok(())
}