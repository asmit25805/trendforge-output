use anyhow::Result;
use std::fs::{self, File};
use std::io::Write;
use std::path::PathBuf;
use tokio::time::{sleep, Duration};

use dnswatch::engine::Engine;
use dnswatch::app_state::AppState;

/// Helper to create a temporary configuration file with the given contents.
fn write_temp_config(contents: &str) -> PathBuf {
    let mut dir = std::env::temp_dir();
    dir.push(format!("dnswatch_test_{}", uuid::Uuid::new_v4()));
    fs::create_dir_all(&dir).expect("failed to create temp dir");
    let mut file_path = dir.clone();
    file_path.push("config.toml");
    let mut file = File::create(&file_path).expect("failed to create config file");
    file.write_all(contents.as_bytes())
        .expect("failed to write config");
    file_path
}

#[tokio::test]
async fn test_engine_starts_and_stops() -> Result<()> {
    // Minimal configuration with a single resolver (loopback).
    let config = r#"
        [resolver]
        ip = "127.0.0.1"
        name = "local"
    "#;
    let config_path = write_temp_config(config);

    // Initialise shared state – in a real test we would parse the config.
    let state = Arc::new(tokio::sync::Mutex::new(AppState::new()));
    let mut engine = Engine::new(state);
    engine.start();

    // Let the engine run briefly.
    sleep(Duration::from_millis(100)).await;

    // Send a shutdown command and wait for graceful exit.
    engine.send_command(dnswatch::engine::AppCommand::Shutdown).await?;
    engine.wait().await?;

    // If we reach this point without error, the test passes.
    Ok(())
}
