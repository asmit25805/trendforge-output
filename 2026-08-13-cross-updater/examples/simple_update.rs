use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process;

use chrono::Utc;
use log::{error, info, warn};
use rusqlite::{params, Connection, Result as SqlResult};
use serde::Deserialize;
use serde_json::Value;
use tokio::fs::File;
use tokio::io::AsyncReadExt;

use crate::core::engine::{
    UpdateError, UpdateRequest, UpdateState, UpdaterEngine,
};
use crate::event::bus::{EventBus, UpdateEvent};

/// Simple SQLite schema for persisting update attempts.
const DB_SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS updates (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status      TEXT NOT NULL,
    error_msg   TEXT
);
"#;

/// Represents the minimal JSON request format expected by the updater binary.
///
/// The fields mirror those in `UpdateRequest`. Validation is performed after
/// deserialization to ensure required keys are present and correctly typed.
#[derive(Debug, Deserialize)]
struct JsonRequest {
    version: String,
    url: String,
    hash: String,
    #[serde(default)]
    signature: Option<String>,
    platform: PlatformInfo,
}

/// Sub‑structure describing the target platform.
#[derive(Debug, Deserialize)]
struct PlatformInfo {
    os: String,
    arch: String,
    binary_name: String,
}

/// Opens (or creates) a SQLite database in the same directory as the executable.
///
/// Returns a connection ready for inserts. Any failure aborts the process because
/// persisting update attempts is considered critical for diagnostics.
fn init_db() -> Connection {
    let exe_path = env::current_exe()
        .unwrap_or_else(|e| {
            error!("Unable to locate current executable: {}", e);
            process::exit(1);
        });
    let db_path = exe_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("cross_updater.db");

    let conn = Connection::open(&db_path).unwrap_or_else(|e| {
        error!("Failed to open SQLite DB at {:?}: {}", db_path, e);
        process::exit(1);
    });

    conn.execute_batch(DB_SCHEMA).unwrap_or_else(|e| {
        error!("Failed to initialise DB schema: {}", e);
        process::exit(1);
    });

    conn
}

/// Persists a single update attempt. The `status` argument should be one of
/// `"started"`, `"completed"` or `"failed"`.
fn log_update_attempt(
    conn: &Connection,
    request: &JsonRequest,
    status: &str,
    error_msg: Option<&str>,
) {
    let json = serde_json::to_string(request).unwrap_or_else(|e| {
        warn!("Failed to serialize request for DB logging: {}", e);
        "{}".to_string()
    });
    let ts = Utc::now().to_rfc3339();

    let _ = conn.execute(
        "INSERT INTO updates (timestamp, request_json, status, error_msg)
         VALUES (?1, ?2, ?3, ?4)",
        params![ts, json, status, error_msg],
    );
}

/// Validates a deserialized `JsonRequest` against a minimal schema. Returns
/// `Ok(())` if all required fields are non‑empty and the platform fields are
/// recognised; otherwise returns an `Err` with a descriptive message.
fn validate_request(req: &JsonRequest) -> Result<(), String> {
    if req.version.trim().is_empty() {
        return Err("field `version` must not be empty".into());
    }
    if req.url.trim().is_empty() {
        return Err("field `url` must not be empty".into());
    }
    if req.hash.trim().is_empty() {
        return Err("field `hash` must not be empty".into());
    }
    let os = req.platform.os.to_lowercase();
    if !["windows", "macos", "linux"].contains(&os.as_str()) {
        return Err(format!("unsupported os `{}`", req.platform.os));
    }
    let arch = req.platform.arch.to_lowercase();
    if !["x86_64", "arm64", "aarch64"].contains(&arch.as_str()) {
        return Err(format!("unsupported arch `{}`", req.platform.arch));
    }
    if req.platform.binary_name.trim().is_empty() {
        return Err("field `binary_name` must not be empty".into());
    }
    Ok(())
}

/// Transforms a validated `JsonRequest` into the internal `UpdateRequest` used
/// by `UpdaterEngine`. This conversion is straightforward because the structures
/// share the same field names.
fn into_update_request(req: JsonRequest) -> UpdateRequest {
    UpdateRequest {
        version: req.version,
        url: req.url,
        hash: req.hash,
        signature: req.signature,
        platform: crate::core::engine::PlatformInfo {
            os: req.platform.os,
            arch: req.platform.arch,
            binary_name: req.platform.binary_name,
        },
    }
}

/// Subscribes to the `EventBus` and prints each received event to stdout. This
/// aids developers when running the example binary manually.
fn attach_console_logger(bus: &EventBus) {
    let _handle = bus.subscribe(move |event| match event {
        UpdateEvent::Progress { state, .. } => {
            println!("[progress] State: {:?}", state);
        }
        UpdateEvent::Log { level, message } => {
            println!("[log] {}: {}", level, message);
        }
        UpdateEvent::Error { error } => {
            eprintln!("[error] {}", error);
        }
        UpdateEvent::Completed => {
            println!("[info] Update process completed successfully");
        }
        _ => {}
    });
    // The subscription handle is intentionally dropped at the end of the program;
    // the closure keeps a reference to the bus for the lifetime of the process.
}

/// Entry point for the example binary. It expects a single argument pointing to a
/// JSON file describing the update request. The function orchestrates loading,
/// validation, persistence, and execution of the updater engine.
#[tokio::main]
async fn main() {
    // Initialise a simple logger; env_logger respects the `RUST_LOG` env var.
    env_logger::init();

    // --------------------------------------------------------------------- //
    // Argument handling
    // --------------------------------------------------------------------- //
    let args: Vec<String> = env::args().collect();
    if args.len() != 2 {
        eprintln!("Usage: {} <path-to-update-request.json>", args[0]);
        process::exit(1);
    }
    let request_path = PathBuf::from(&args[1]);

    // --------------------------------------------------------------------- //
    // Load and parse JSON request
    // --------------------------------------------------------------------- //
    let mut file = match File::open(&request_path).await {
        Ok(f) => f,
        Err(e) => {
            error!("Failed to open request file {:?}: {}", request_path, e);
            process::exit(1);
        }
    };
    let mut contents = String::new();
    if let Err(e) = file.read_to_string(&mut contents).await {
        error!("Failed to read request file: {}", e);
        process::exit(1);
    }

    // Basic JSON syntax validation before deserialization.
    let raw_json: Value = match serde_json::from_str(&contents) {
        Ok(v) => v,
        Err(e) => {
            error!("Invalid JSON in request file: {}", e);
            process::exit(1);
        }
    };

    // Deserialize into the strongly‑typed struct.
    let json_req: JsonRequest = match serde_json::from_value(raw_json) {
        Ok(r) => r,
        Err(e) => {
            error!("JSON does not match expected schema: {}", e);
            process::exit(1);
        }
    };

    // --------------------------------------------------------------------- //
    // Validation against minimal business rules
    // --------------------------------------------------------------------- //
    if let Err(msg) = validate_request(&json_req) {
        error!("Request validation failed: {}", msg);
        process::exit(1);
    }

    // --------------------------------------------------------------------- //
    // Persistence: record the start of an update attempt
    // --------------------------------------------------------------------- //
    let db = init_db();
    log_update_attempt(&db, &json_req, "started", None);

    // --------------------------------------------------------------------- //
    // Engine preparation
    // --------------------------------------------------------------------- //
    let bus = EventBus::new();
    attach_console_logger(&bus);
    let mut engine = UpdaterEngine::new(bus.clone());

    // Convert to the internal request type.
    let upd_req = into_update_request(json_req);

    // --------------------------------------------------------------------- //
    // Run the update lifecycle
    // --------------------------------------------------------------------- //
    match engine.run(upd_req).await {
        Ok(_) => {
            info!("Update completed without errors");
            log_update_attempt(&db, &json_req, "completed", None);
        }
        Err(err) => {
            // Categorise the error for reporting.
            let (status, msg) = match err {
                UpdateError::Fatal(e) => ("failed", format!("Fatal: {}", e)),
                UpdateError::Retryable(e) => ("failed", format!("Retryable after retries: {}", e)),
                UpdateError::NonFatal(e) => ("failed", format!("Non‑Fatal: {}", e)),
            };
            error!("Update process terminated: {}", msg);
            log_update_attempt(&db, &json_req, status, Some(&msg));
            process::exit(1);
        }
    }
}