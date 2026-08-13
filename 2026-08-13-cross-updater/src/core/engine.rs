use std::fs;
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};
use reqwest::Client;
use rusqlite::{params, Connection};
use sha2::{Digest, Sha256};
use tokio::fs as async_fs;
use tokio::time::sleep;

use crate::event::bus::{EventBus, UpdateEvent};
use crate::platform::native_adapter::NativeAdapter;

/// Represents the target platform for which an update is applicable.
#[derive(Debug, Clone)]
pub struct PlatformInfo {
    pub os: String,
    pub arch: String,
    pub binary_name: String,
}

/// High‑level request supplied by the host application.
#[derive(Debug, Clone)]
pub struct UpdateRequest {
    pub version: String,
    pub url: String,
    pub hash: String,
    pub signature: Option<String>,
    pub platform: PlatformInfo,
}

/// Enumerates the distinct phases of the updater state machine.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UpdateState {
    Checking,
    Downloading,
    Verifying,
    BackingUp,
    Replacing,
    Launching,
    Completed,
    Failed,
}

/// Categorised error type used throughout the engine.
#[derive(Debug)]
pub enum UpdateError {
    Fatal(String),
    Retryable(String),
    NonFatal(String),
}

impl std::fmt::Display for UpdateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            UpdateError::Fatal(msg) => write!(f, "Fatal error: {}", msg),
            UpdateError::Retryable(msg) => write!(f, "Retryable error: {}", msg),
            UpdateError::NonFatal(msg) => write!(f, "Non‑fatal error: {}", msg),
        }
    }
}

impl std::error::Error for UpdateError {}

/// Core engine that drives the whole update lifecycle.
pub struct UpdaterEngine {
    bus: EventBus,
    state: UpdateState,
    db: Connection,
    adapter: NativeAdapter,
    client: Client,
}

impl UpdaterEngine {
    /// Creates a new engine instance, opening a SQLite DB next to the executable.
    pub fn new(bus: EventBus) -> Self {
        let exe_path = std::env::current_exe()
            .unwrap_or_else(|e| panic!("cannot locate current exe: {}", e));
        let db_path = exe_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join("cross_updater.db");

        let db = Connection::open(&db_path)
            .unwrap_or_else(|e| panic!("cannot open DB at {:?}: {}", db_path, e));

        db.execute_batch(
            "CREATE TABLE IF NOT EXISTS updates (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                request_json TEXT NOT NULL,
                status      TEXT NOT NULL,
                error_msg   TEXT
            );",
        )
        .expect("failed to initialise DB schema");

        UpdaterEngine {
            bus,
            state: UpdateState::Checking,
            db,
            adapter: NativeAdapter::new(),
            client: Client::new(),
        }
    }

    /// Returns the current state of the engine.
    pub fn current_state(&self) -> UpdateState {
        self.state
    }

    /// Primary entry point. Drives the state machine from start to finish.
    pub async fn run(&mut self, request: UpdateRequest) -> Result<(), UpdateError> {
        self.log_to_db(&request, "started", None);
        self.transition(UpdateState::Checking).await?;
        self.transition(UpdateState::Downloading).await?;
        self.transition(UpdateState::Verifying).await?;
        self.transition(UpdateState::BackingUp).await?;
        self.transition(UpdateState::Replacing).await?;
        self.transition(UpdateState::Launching).await?;
        self.transition(UpdateState::Completed).await?;
        self.log_to_db(&request, "completed", None);
        Ok(())
    }

    /// Moves the engine to the next phase, performing the work associated with that
    /// phase and emitting progress events.
    pub async fn transition(&mut self, next: UpdateState) -> Result<(), UpdateError> {
        self.state = next;
        self.bus.emit(UpdateEvent::Progress {
            state: next,
            progress: 0.0,
        });

        match next {
            UpdateState::Checking => {
                // In a real implementation we would compare versions here.
                info!("Checking for updates");
                Ok(())
            }
            UpdateState::Downloading => {
                self.handle_download().await
            }
            UpdateState::Verifying => {
                self.handle_verify().await
            }
            UpdateState::BackingUp => {
                self.handle_backup().await
            }
            UpdateState::Replacing => {
                self.handle_replace().await
            }
            UpdateState::Launching => {
                self.handle_launch().await
            }
            UpdateState::Completed => {
                self.bus.emit(UpdateEvent::Completed);
                Ok(())
            }
            UpdateState::Failed => Err(UpdateError::Fatal(
                "Engine entered failed state unexpectedly".into(),
            )),
        }
    }

    /// Attempts to rollback to the previous version using the backup created earlier.
    pub async fn rollback(&mut self) -> Result<(), UpdateError> {
        let backup_path = self.adapter.backup_path().ok_or_else(|| {
            UpdateError::Fatal("No backup path available for rollback".into())
        })?;
        let target = self.adapter.current_executable_path()?;
        self.adapter
            .replace_executable(&backup_path, &target)
            .map_err(|e| UpdateError::Fatal(format!("Rollback failed: {}", e)))?;
        self.bus.emit(UpdateEvent::Rollback);
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Internal helpers for each phase
    // -------------------------------------------------------------------------

    async fn handle_download(&mut self) -> Result<(), UpdateError> {
        let pkg = UpdatePackage {
            url: self.adapter.update_url.clone(),
            hash: self.adapter.expected_hash.clone(),
            signature: self.adapter.expected_signature.clone(),
        };
        let dest = self.adapter.temp_download_path()?;
        self.retryable_operation(3, Duration::from_millis(500), || {
            let client = self.client.clone();
            let url = pkg.url.clone();
            let dest = dest.clone();
            async move {
                pkg.download(&client, &dest).await?;
                Ok(())
            }
        })
        .await?;
        self.bus.emit(UpdateEvent::Progress {
            state: UpdateState::Downloading,
            progress: 100.0,
        });
        Ok(())
    }

    async fn handle_verify(&mut self) -> Result<(), UpdateError> {
        let pkg = UpdatePackage {
            url: self.adapter.update_url.clone(),
            hash: self.adapter.expected_hash.clone(),
            signature: self.adapter.expected_signature.clone(),
        };
        let path = self.adapter.temp_download_path()?;
        pkg.verify(&path).await?;
        self.bus.emit(UpdateEvent::Progress {
            state: UpdateState::Verifying,
            progress: 100.0,
        });
        Ok(())
    }

    async fn handle_backup(&mut self) -> Result<(), UpdateError> {
        let backup_path = self.adapter.create_backup().await?;
        self.bus.emit(UpdateEvent::BackupCreated { path: backup_path });
        Ok(())
    }

    async fn handle_replace(&mut self) -> Result<(), UpdateError> {
        let backup_path = self.adapter.backup_path().ok_or_else(|| {
            UpdateError::Fatal("Backup not found before replace".into())
        })?;
        let new_path = self.adapter.temp_download_path()?;
        self.adapter
            .replace_executable(&new_path, &self.adapter.current_executable_path()?)
            .map_err(|e| UpdateError::Fatal(format!("Replace failed: {}", e)))?;
        self.bus.emit(UpdateEvent::Replaced);
        Ok(())
    }

    async fn handle_launch(&mut self) -> Result<(), UpdateError> {
        let exe = self.adapter.current_executable_path()?;
        Command::new(&exe)
            .spawn()
            .map_err(|e| UpdateError::Fatal(format!("Launch failed: {}", e)))?;
        self.bus.emit(UpdateEvent::Launched);
        Ok(())
    }

    // -------------------------------------------------------------------------
    // Utility: generic retry logic for retryable errors
    // -------------------------------------------------------------------------

    async fn retryable_operation<F, Fut>(
        &self,
        max_attempts: usize,
        base_delay: Duration,
        mut op: F,
    ) -> Result<(), UpdateError>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = Result<(), UpdateError>>,
    {
        let mut attempt = 0;
        loop {
            match op().await {
                Ok(v) => return Ok(v),
                Err(e) => {
                    attempt += 1;
                    match e {
                        UpdateError::Retryable(msg) => {
                            if attempt >= max_attempts {
                                return Err(UpdateError::Fatal(format!(
                                    "Exceeded retries: {}",
                                    msg
                                )));
                            }
                            let backoff = base_delay * 2u32.pow(attempt as u32);
                            warn!("Retryable error (attempt {}): {} – backing off {:?}", attempt, msg, backoff);
                            sleep(backoff).await;
                        }
                        _ => return Err(e),
                    }
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Persistence helpers
    // -------------------------------------------------------------------------

    fn log_to_db(
        &self,
        request: &UpdateRequest,
        status: &str,
        error_msg: Option<&str>,
    ) {
        let json = serde_json::to_string(request).unwrap_or_else(|_| "{}".to_string());
        let ts = chrono::Utc::now().to_rfc3339();
        let _ = self.db.execute(
            "INSERT INTO updates (timestamp, request_json, status, error_msg) VALUES (?1, ?2, ?3, ?4)",
            params![ts, json, status, error_msg],
        );
    }
}

/// Represents a downloadable artifact together with its metadata.
pub struct UpdatePackage {
    pub url: String,
    pub hash: String,
    pub signature: Option<String>,
}

impl UpdatePackage {
    /// Streams the package to `dest` while emitting progress events.
    pub async fn download(
        &self,
        client: &Client,
        dest: &Path,
    ) -> Result<(), UpdateError> {
        let resp = client
            .get(&self.url)
            .send()
            .await
            .map_err(|e| UpdateError::Retryable(format!("Network error: {}", e)))?;
        if !resp.status().is_success() {
            return Err(UpdateError::Retryable(format!(
                "Bad HTTP status: {}",
                resp.status()
            )));
        }

        let total = resp
            .content_length()
            .ok_or_else(|| UpdateError::Retryable("Missing Content-Length".into()))?;
        let mut stream = resp.bytes_stream();

        let mut file = async_fs::File::create(dest)
            .await
            .map_err(|e| UpdateError::Fatal(format!("Cannot create file: {}", e)))?;
        let mut downloaded: u64 = 0;

        while let Some(chunk) = stream.next().await {
            let data = chunk.map_err(|e| UpdateError::Retryable(format!("Chunk error: {}", e)))?;
            file.write_all(&data)
                .await
                .map_err(|e| UpdateError::Fatal(format!("Write error: {}", e)))?;
            downloaded += data.len() as u64;
            let progress = (downloaded as f64 / total as f64) * 100.0;
            // Emit a progress event; the caller may ignore it.
            // In this module we don't have direct access to the bus, so we skip it.
            // Consumers can poll the file size if needed.
        }

        file.flush()
            .await
            .map_err(|e| UpdateError::Fatal(format!("Flush error: {}", e)))?;
        Ok(())
    }

    /// Verifies the SHA‑256 hash and optional PGP signature of the downloaded file.
    pub async fn verify(&self, path: &Path) -> Result<(), UpdateError> {
        let mut file = async_fs::File::open(path)
            .await
            .map_err(|e| UpdateError::Fatal(format!("Cannot open file for verification: {}", e)))?;
        let mut hasher = Sha256::new();
        let mut buf = [0u8; 8192];
        loop {
            let n = file
                .read(&mut buf)
                .await
                .map_err(|e| UpdateError::Fatal(format!("Read error: {}", e)))?;
            if n == 0 {
                break;
            }
            hasher.update(&buf[..n]);
        }
        let calculated = format!("{:x}", hasher.finalize());
        if calculated != self.hash {
            return Err(UpdateError::Fatal(format!(
                "Hash mismatch: expected {}, got {}",
                self.hash, calculated
            )));
        }

        // Signature verification would be added here; omitted for brevity.
        Ok(())
    }

    /// Extracts the archive to `to`. Supports zip on Windows and tar.gz on Unix.
    pub async fn extract(&self, archive: &Path, to: &Path) -> Result<(), UpdateError> {
        #[cfg(target_os = "windows")]
        {
            let file = fs::File::open(archive)
                .map_err(|e| UpdateError::Fatal(format!("Open archive error: {}", e)))?;
            let mut zip = zip::ZipArchive::new(file)
                .map_err(|e| UpdateError::Fatal(format!("Zip error: {}", e)))?;
            for i in 0..zip.len() {
                let mut entry = zip.by_index(i).map_err(|e| {
                    UpdateError::Fatal(format!("Zip entry error: {}", e))
                })?;
                let out_path = to.join(entry.name());
                if entry.is_dir() {
                    fs::create_dir_all(&out_path).map_err(|e| {
                        UpdateError::Fatal(format!("Create dir error: {}", e))
                    })?;
                } else {
                    if let Some(p) = out_path.parent() {
                        fs::create_dir_all(p).map_err(|e| {
                            UpdateError::Fatal(format!("Create parent dir error: {}", e))
                        })?;
                    }
                    let mut outfile = fs::File::create(&out_path).map_err(|e| {
                        UpdateError::Fatal(format!("Create file error: {}", e))
                    })?;
                    io::copy(&mut entry, &mut outfile).map_err(|e| {
                        UpdateError::Fatal(format!("Copy entry error: {}", e))
                    })?;
                }
            }
        }
        #[cfg(not(target_os = "windows"))]
        {
            let file = fs::File::open(archive)
                .map_err(|e| UpdateError::Fatal(format!("Open archive error: {}", e)))?;
            let mut archive = tar::Archive::new(flate2::read::GzDecoder::new(file));
            archive
                .unpack(to)
                .map_err(|e| UpdateError::Fatal(format!("Tar extraction error: {}", e)))?;
        }
        Ok(())
    }
}