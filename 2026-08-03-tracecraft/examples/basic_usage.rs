use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection};

use uuid::Uuid;

use crate::collectors::command::CommandCollector;
use crate::cache::ResourceCache;
use crate::models::{PipelineSpec, SessionBundle};
use crate::pipeline_builder::{BuildError, PipelineBuilder};
use crate::recorder::{RecorderConfig, RecorderError, SessionRecorder};
use crate::transformer::LLMTransformer;

/// Simple definition of a task that will be recorded and turned into a pipeline.
#[derive(Debug, Clone)]
struct TaskDefinition {
    /// Human readable description of the work to be performed.
    description: String,
    /// Command line that will be executed during the recording.
    command: String,
}

/// Record the execution of a single `TaskDefinition` and produce a `SessionBundle`.
fn record_task(task: &TaskDefinition, config: &RecorderConfig) -> Result<SessionBundle, RecorderError> {
    // Initialise the recorder.
    let mut recorder = SessionRecorder::default();

    // Create a command collector and register it.
    let cmd_collector = CommandCollector::new();
    recorder.add_collector(Box::new(cmd_collector));

    // Start the recording session.
    info!("Starting session for task: {}", task.description);
    recorder.start(config.clone())?;

    // Execute the command while the collector is active.
    let start = Instant::now();
    let status = Command::new("sh")
        .arg("-c")
        .arg(&task.command)
        .status()
        .map_err(|e| RecorderError::CollectorError(format!("Failed to spawn command: {}", e)))?;

    let elapsed = start.elapsed();
    info!(
        "Command '{}' finished with exit code {} in {:.2?}",
        task.command,
        status.code().unwrap_or(-1),
        elapsed
    );

    // Stop the recorder and retrieve the bundle.
    let bundle = recorder.stop()?;
    info!("Session stopped, bundle ID {}", bundle.id);
    Ok(bundle)
}

/// Persist a run record into a SQLite database for later inspection.
fn persist_run_history(
    db: &Connection,
    task: &TaskDefinition,
    bundle_id: Uuid,
    start: DateTime<Utc>,
    end: DateTime<Utc>,
    result: &str,
) -> rusqlite::Result<()> {
    db.execute(
        "CREATE TABLE IF NOT EXISTS run_history (
            id TEXT PRIMARY KEY,
            task_desc TEXT NOT NULL,
            bundle_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            duration_ms INTEGER NOT NULL,
            result TEXT NOT NULL
        )",
        [],
    )?;

    let duration_ms = (end - start).num_milliseconds();
    db.execute(
        "INSERT INTO run_history (id, task_desc, bundle_id, started_at, finished_at, duration_ms, result)
         VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
        params![
            Uuid::new_v4().to_string(),
            task.description,
            bundle_id.to_string(),
            start.to_rfc3339(),
            end.to_rfc3339(),
            duration_ms,
            result
        ],
    )?;
    Ok(())
}

/// Main entry point demonstrating the full workflow.
fn main() {
    // Initialise logger (env_logger respects RUST_LOG).
    env_logger::init();

    // Define a temporary directory for the session files.
    let session_dir = dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".tracecraft")
        .join("sessions");
    if let Err(e) = fs::create_dir_all(&session_dir) {
        error!("Failed to create session directory {}: {}", session_dir.display(), e);
        std::process::exit(1);
    }

    // Build a recorder configuration.
    let mut recorder_cfg = RecorderConfig::default();
    recorder_cfg.session_dir = Some(session_dir.clone());

    // Example task to be recorded.
    let task = TaskDefinition {
        description: "Print greeting and list files".to_string(),
        command: "echo Hello && ls -1".to_string(),
    };

    // Record the task.
    let bundle = match record_task(&task, &recorder_cfg) {
        Ok(b) => b,
        Err(e) => {
            error!("Recording failed: {}", e);
            std::process::exit(1);
        }
    };

    // Prepare SQLite connection for run history.
    let db_path = dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".tracecraft")
        .join("run_history.db");
    let conn = match Connection::open(&db_path) {
        Ok(c) => c,
        Err(e) => {
            error!("Unable to open run history DB {}: {}", db_path.display(), e);
            std::process::exit(1);
        }
    };

    // Record start/end timestamps for history.
    let start_ts = bundle.started_at;
    let end_ts = Utc::now();

    // Initialise the resource cache.
    let cache = match ResourceCache::new(&db_path) {
        Ok(c) => c,
        Err(e) => {
            error!("Cache initialisation failed: {}", e);
            std::process::exit(1);
        }
    };

    // Compute a deterministic hash of the bundle for cache lookup.
    let bundle_hash = {
        let json = serde_json::to_string(&bundle).unwrap_or_default();
        let mut hasher = sha2::Sha256::new();
        hasher.update(json.as_bytes());
        hex::encode(hasher.finalize())
    };

    // Try to retrieve a cached spec.
    let spec = match cache.get(&bundle_hash) {
        Ok(Some(s)) => {
            info!("Cache hit for bundle {}", bundle.id);
            s
        }
        Ok(None) => {
            info!("Cache miss for bundle {}, invoking LLM transformer", bundle.id);
            // Create transformer and request spec.
            let transformer = LLMTransformer::new();
            match transformer.transform(&bundle, None) {
                Ok(s) => {
                    // Insert into cache for future runs.
                    if let Err(e) = cache.insert(bundle_hash.clone(), s.clone()) {
                        warn!("Failed to insert spec into cache: {}", e);
                    }
                    s
                }
                Err(e) => {
                    error!("LLM transformation failed: {}", e);
                    let _ = persist_run_history(
                        &conn,
                        &task,
                        bundle.id,
                        start_ts,
                        end_ts,
                        "LLM error",
                    );
                    std::process::exit(1);
                }
            }
        }
        Err(e) => {
            error!("Cache lookup error: {}", e);
            std::process::exit(1);
        }
    };

    // Build pipeline artifacts.
    let template_dir = Path::new("templates");
    let artifacts_dir = dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".tracecraft")
        .join("artifacts")
        .join(bundle.id.to_string());

    // Ensure artifact directory exists.
    if let Err(e) = fs::create_dir_all(&artifacts_dir) {
        error!("Failed to create artifacts directory {}: {}", artifacts_dir.display(), e);
        std::process::exit(1);
    }

    let builder = match PipelineBuilder::new(&template_dir, &db_path) {
        Ok(b) => b,
        Err(e) => {
            error!("Failed to initialise PipelineBuilder: {}", e);
            let _ = persist_run_history(
                &conn,
                &task,
                bundle.id,
                start_ts,
                end_ts,
                "Builder init error",
            );
            std::process::exit(1);
        }
    };

    // Run the build in a separate thread to keep the UI responsive.
    let spec_arc = Arc::new(spec);
    let builder_arc = Arc::new(builder);
    let artifacts_path = artifacts_dir.clone();

    let handle = thread::spawn(move || {
        match builder_arc.build(&spec_arc) {
            Ok(artifacts) => {
                // Move generated files into the final artifacts directory.
                for file in artifacts.files {
                    if let Some(fname) = file.file_name() {
                        let dest = artifacts_path.join(fname);
                        if let Err(e) = fs::rename(&file, &dest) {
                            warn!("Failed to move artifact {}: {}", file.display(), e);
                        }
                    }
                }
                info!("Pipeline built successfully, artifacts stored at {}", artifacts_path.display());
                Ok(())
            }
            Err(BuildError::Validation(msg)) => {
                error!("Validation failed: {}", msg);
                Err(BuildError::Validation(msg))
            }
            Err(e) => {
                error!("Build error: {}", e);
                Err(e)
            }
        }
    });

    // Wait for the builder thread to finish.
    match handle.join() {
        Ok(Ok(())) => {
            let _ = persist_run_history(&conn, &task, bundle.id, start_ts, end_ts, "Success");
            println!("✅ Pipeline artifacts are ready at {}", artifacts_path.display());
        }
        Ok(Err(_)) => {
            let _ = persist_run_history(&conn, &task, bundle.id, start_ts, end_ts, "Build failure");
            eprintln!("❌ Pipeline build failed, see logs for details");
            std::process::exit(1);
        }
        Err(_) => {
            let _ = persist_run_history(&conn, &task, bundle.id, start_ts, end_ts, "Thread panic");
            eprintln!("❌ Builder thread panicked");
            std::process::exit(1);
        }
    }
}