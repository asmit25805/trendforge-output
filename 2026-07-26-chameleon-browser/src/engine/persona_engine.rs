use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime};

use chrono::{DateTime, Utc};
use log::{error, info};
use rusqlite::{params, Connection, Result as SqlResult};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tonic::transport::{Channel, Endpoint};

/// Represents a coherent fingerprint that will be injected into Chromium.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Persona {
    /// Unique identifier for caching/reuse.
    pub id: String,
    /// Realistic UA string matching OS and hardware.
    pub user_agent: String,
    /// Platform string, e.g. "Win32" or "MacIntel".
    pub platform: String,
    /// Number of logical cores reported.
    pub hardware_concurrency: u8,
    /// GB of RAM reported.
    pub device_memory: f32,
    /// GPU vendor name.
    pub gpu_vendor: String,
    /// Full GPU renderer string.
    pub gpu_renderer: String,
    /// IANA timezone name.
    pub timezone: String,
    /// BCP‑47 language tag.
    pub language: String,
    /// Subset of system fonts to expose.
    pub fonts: Vec<String>,
}

/// Errors that can be raised while validating a generated persona.
#[derive(Debug, Error)]
pub enum ValidationError {
    /// The generated fields are mutually incompatible.
    #[error("validation conflict: {0}")]
    Conflict(String),
    /// Unexpected internal error.
    #[error("internal validation error: {0}")]
    Internal(String),
}

/// Core engine that talks to the side‑car gRPC service (or falls back to a local generator).
pub struct PersonaEngine {
    /// gRPC channel to the remote service.
    channel: Option<Channel>,
    /// In‑process cache of generated personas.
    cache: Arc<Mutex<HashMap<String, Persona>>>,
    /// SQLite connection used for run‑history logging.
    db: Connection,
}

impl PersonaEngine {
    /// Creates a new `PersonaEngine`. If `grpc_endpoint` is reachable, a gRPC channel is
    /// established; otherwise the engine works in‑process.
    ///
    /// # Errors
    ///
    /// Returns an `Error` if the SQLite database cannot be opened.
    pub fn new(grpc_endpoint: &str) -> Result<Self, crate::error::Error> {
        // Initialise SQLite database in a deterministic location.
        let db_path = std::env::var("CHAMELEON_DB")
            .map(PathBuf::from)
            .unwrap_or_else(|_| std::env::temp_dir().join("chameleon_run_history.sqlite"));
        let db = Connection::open(&db_path).map_err(|e| {
            crate::error::Error::Fatal(format!(
                "failed to open run‑history DB at {}: {}",
                db_path.display(),
                e
            ))
        })?;
        db.execute_batch(
            "CREATE TABLE IF NOT EXISTS persona_generation (
                id TEXT PRIMARY KEY,
                start_ts TEXT NOT NULL,
                end_ts TEXT,
                success INTEGER NOT NULL,
                error TEXT
            );",
        )
        .map_err(|e| crate::error::Error::Fatal(format!("failed to create DB schema: {}", e)))?;

        // Attempt to create a gRPC channel; failure is non‑fatal.
        let channel = match Endpoint::from_shared(grpc_endpoint.to_string()) {
            Ok(ep) => match ep.connect_lazy() {
                Ok(ch) => {
                    info!("gRPC channel to PersonaEngine established at {}", grpc_endpoint);
                    Some(ch)
                }
                Err(e) => {
                    error!("gRPC channel creation failed (will use local fallback): {}", e);
                    None
                }
            },
            Err(e) => {
                error!("invalid gRPC endpoint '{}': {}", grpc_endpoint, e);
                None
            }
        };

        Ok(Self {
            channel,
            cache: Arc::new(Mutex::new(HashMap::new())),
            db,
        })
    }

    /// Generates a fresh `Persona`. If `persona_id` is supplied and a cached entry exists,
    /// that entry is returned. Otherwise a new persona is created, validated and cached.
    ///
    /// Transient validation failures are retried up to three times with exponential back‑off.
    ///
    /// # Errors
    ///
    /// Returns `Error::Transient` after exhausting retries, or `Error::Fatal` for unrecoverable
    /// conditions such as SQLite corruption.
    pub fn generate(&self, persona_id: Option<String>) -> Result<Persona, crate::error::Error> {
        // Fast‑path: return cached persona if ID is provided.
        if let Some(ref id) = persona_id {
            if let Some(p) = self.cache.lock().unwrap().get(id) {
                info!("Returning cached persona with id {}", id);
                return Ok(p.clone());
            }
        }

        // Record start time for logging.
        let start_ts: DateTime<Utc> = SystemTime::now().into();

        // Attempt generation with retries.
        let mut attempt = 0;
        let max_attempts = 3;
        let mut last_err: Option<ValidationError> = None;

        while attempt < max_attempts {
            attempt += 1;
            info!("Persona generation attempt {}/{}", attempt, max_attempts);

            // Generate a candidate persona.
            let candidate = self.generate_candidate(persona_id.clone())?;

            // Validate the candidate.
            match self.validate(&candidate) {
                Ok(()) => {
                    // Validation succeeded – cache and log.
                    let id = candidate.id.clone();
                    self.cache
                        .lock()
                        .unwrap()
                        .insert(id.clone(), candidate.clone());

                    self.log_generation(&candidate.id, &start_ts, &Utc::now(), true, None)?;
                    info!("Persona generation succeeded with id {}", id);
                    return Ok(candidate);
                }
                Err(e) => {
                    error!("Validation failed on attempt {}: {}", attempt, e);
                    last_err = Some(e);
                    // Back‑off before next retry.
                    let backoff = Duration::from_millis(100 * 2_u64.pow(attempt as u32));
                    thread::sleep(backoff);
                }
            }
        }

        // All retries exhausted.
        let err_msg = match last_err {
            Some(ValidationError::Conflict(ref s)) => s.clone(),
            Some(ValidationError::Internal(ref s)) => s.clone(),
            None => "unknown validation error".to_string(),
        };
        self.log_generation(
            &persona_id.unwrap_or_else(|| "generated".to_string()),
            &start_ts,
            &Utc::now(),
            false,
            Some(&err_msg),
        )?;
        Err(crate::error::Error::Transient(format!(
            "persona generation failed after {} attempts: {}",
            max_attempts, err_msg
        )))
    }

    /// Internal helper that creates a fresh `Persona`. If a gRPC channel is available,
    /// it would normally forward the request; for this implementation we synthesize
    /// a deterministic persona based on the current timestamp.
    fn generate_candidate(&self, persona_id: Option<String>) -> Result<Persona, crate::error::Error> {
        // In a real implementation this would be a gRPC call. Here we fabricate data.
        let timestamp = SystemTime::now()
            .duration_since(SystemTime::UNIX_EPOCH)
            .map_err(|e| crate::error::Error::Fatal(format!("system time error: {}", e)))?
            .as_secs();

        let id = persona_id.unwrap_or_else(|| format!("persona-{}", timestamp));

        // Deterministic but varied fields.
        let user_agent = format!(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{} Safari/537.36",
            115 + (timestamp % 10) as u32
        );
        let platform = "Win32".to_string();
        let hardware_concurrency = ((timestamp % 8) + 2) as u8;
        let device_memory = ((timestamp % 16) as f32) + 4.0;
        let gpu_vendor = "NVIDIA".to_string();
        let gpu_renderer = "NVIDIA GeForce RTX 3080".to_string();
        let timezone = "America/New_York".to_string();
        let language = "en-US".to_string();
        let fonts = vec![
            "Arial".to_string(),
            "Times New Roman".to_string(),
            "Courier New".to_string(),
        ];

        Ok(Persona {
            id,
            user_agent,
            platform,
            hardware_concurrency,
            device_memory,
            gpu_vendor,
            gpu_renderer,
            timezone,
            language,
            fonts,
        })
    }

    /// Validates that the fields of a `Persona` are mutually compatible.
    ///
    /// Returns `Ok(())` if the persona is coherent, otherwise a `ValidationError`.
    pub fn validate(&self, persona: &Persona) -> Result<(), ValidationError> {
        // Simple consistency checks – in a real system these would be far more exhaustive.
        if !persona.user_agent.contains(&persona.platform) {
            return Err(ValidationError::Conflict(
                "user_agent does not match platform".into(),
            ));
        }
        if persona.hardware_concurrency == 0 {
            return Err(ValidationError::Conflict(
                "hardware_concurrency cannot be zero".into(),
            ));
        }
        if persona.device_memory < 0.5 {
            return Err(ValidationError::Conflict(
                "device_memory unrealistically low".into(),
            ));
        }
        if persona.timezone.is_empty() {
            return Err(ValidationError::Conflict(
                "timezone must be non‑empty".into(),
            ));
        }
        if persona.language.is_empty() {
            return Err(ValidationError::Conflict(
                "language must be non‑empty".into(),
            ));
        }
        // Fonts list must contain at least one entry.
        if persona.fonts.is_empty() {
            return Err(ValidationError::Conflict(
                "fonts list cannot be empty".into(),
            ));
        }
        Ok(())
    }

    /// Persists a generation attempt to the SQLite run‑history database.
    fn log_generation(
        &self,
        id: &str,
        start: &DateTime<Utc>,
        end: &DateTime<Utc>,
        success: bool,
        error_msg: Option<&str>,
    ) -> SqlResult<()> {
        let mut stmt = self.db.prepare_cached(
            "INSERT OR REPLACE INTO persona_generation (id, start_ts, end_ts, success, error)
             VALUES (?1, ?2, ?3, ?4, ?5);",
        )?;
        stmt.execute(params![
            id,
            start.to_rfc3339(),
            end.to_rfc3339(),
            if success { 1 } else { 0 },
            error_msg
        ])?;
        Ok(())
    }

    /// Expires a cached persona, forcing regeneration on next request.
    ///
    /// # Errors
    ///
    /// Returns `Error::Transient` if the persona does not exist.
    pub fn expire(&self, persona_id: &str) -> Result<(), crate::error::Error> {
        let mut cache = self.cache.lock().unwrap();
        if cache.remove(persona_id).is_some() {
            info!("Expired persona {}", persona_id);
            Ok(())
        } else {
            Err(crate::error::Error::Transient(format!(
                "attempted to expire unknown persona {}",
                persona_id
            )))
        }
    }
}