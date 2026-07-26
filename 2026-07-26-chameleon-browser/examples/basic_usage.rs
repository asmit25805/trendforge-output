// examples/basic_usage.rs
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

use chrono::Utc;
use env_logger::Env;
use log::{error, info, warn};

use crate::session::{SessionId, SessionManager}; // removed SessionOpts which does not exist

/// Executes a named task, logs its start and end, measures duration, and returns the inner result.
///
/// The closure must return `Result<T, E>` where `E` implements `std::fmt::Display`.
///
/// ... rest of the file unchanged ...
