// src/launcher/browser_launcher.rs
use std::collections::HashMap;
use std::ffi::OsString;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime};

use chrono::{DateTime, Utc};
use log::{error, info};
use rusqlite::{params, Connection, Result as SqlResult};
use serde::Serialize;
use tempfile::{tempdir, TempDir}; // added missing semicolon

// ... rest of the file unchanged ...
