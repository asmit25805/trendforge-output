// tests/integration_test.rs
use std::env;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;

use tempfile::TempDir;

// use crate::error::Error; // removed invalid import
use anyhow::Error; // generic error type for tests
use crate::session::{SessionId, SessionManager}; // removed SessionOpts which does not exist

/// Creates a temporary executable that simply exits with status 0.
/// The file is placed inside `dir` and made executable
///
/// ... rest of the file unchanged ...
