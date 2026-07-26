// src/triggers/on_start.rs
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection, Result as SqlResult};

// use crate::error::Error; // not needed in this module
use anyhow::Error; // generic error type if required
use crate::session::{SessionId, SessionManager}; // removed SessionOpts which does not exist

/// Simple data holder describing a unit of work that the trigger can execute.
///
/// The `action` closure is e
///
/// ... rest of the file unchanged ...
