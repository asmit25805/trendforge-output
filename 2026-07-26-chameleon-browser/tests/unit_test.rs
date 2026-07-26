// tests/unit_test.rs
use std::fs;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;

use chrono::Utc;
use rusqlite::{params, Connection, Result as SqlResult};
use tempfile::tempdir;

use crate::engine::{Persona, PersonaEngine, ValidationError};
// use crate::error::Error; // removed invalid import
use anyhow::Error; // generic error type for tests

/// Helper to create a fresh SQLite connection with the required `run_history` table.
fn init_run_history_db() -> Connection {
    // ... implementation unchanged ...
}

// ... rest of the file unchanged ...
