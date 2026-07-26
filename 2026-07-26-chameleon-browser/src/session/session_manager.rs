// src/session/session_manager.rs
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection, Result as SqlResult};

// Removed invalid import of crate::error::Error – use anyhow::Error instead if needed.
// use crate::error::Error;
use anyhow::Error; // generic error type for public API

use crate::engine::{Persona, PersonaEngine, ValidationError};
use crate::launcher::{BrowserHandle, BrowserLauncher, LaunchConfig}; // completed import list

// ... rest of the file unchanged ...
