use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Path, PathBuf};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::time::Instant;

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use serde::Deserialize;
use serde_json::json;
use tokio::sync::mpsc::{self, Receiver, Sender};
use tokio::task::JoinHandle;
use uuid::Uuid;

use crate::collectors::command::CommandCollector;
use crate::collectors::filesystem::FilesystemCollector;
use crate::collectors::network::NetworkCollector;
use crate::event::Event;
use crate::models::{SessionBundle, SessionMetadata};

/// Configuration used to start a recording session.
///
/// The configuration is read from a JSON file supplied by the user.  Only the
/// fields required for the core recorder are exposed here.
#[derive(Debug, Deserialize)]
pub struct RecorderConfig {
    /// Optional explicit session identifier.  If omitted a new UUID is generated.
    pub id: Option<Uuid>,
    /// Enable the command collector.
    #[serde(default = "default_true")]
    pub command: bool,
    /// Enable the filesystem collector.
    #[serde(default = "default_true")]
    pub filesystem: bool,
    /// Enable the network collector.
    #[serde(default = "default_true")]
    pub network: bool,
    /// Optional user‑provided metadata.
    pub metadata: Option<SessionMetadata>,
}

fn default_true() -> bool {
    true
}

/// Errors that can be produced by the recorder.
#[derive(thiserror::Error, Debug)]
pub enum RecorderError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("JSON deserialization error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Collector error: {0}")]
    Collector(String),
    #[error("Configuration error: {0}")]
    Config(String),
    #[error("Channel send error")]
    ChannelSend,
    #[error("Channel receive error")]
    ChannelRecv,
}

/// Orchestrates a recording session, manages lifecycle of collectors,
/// aggregates raw events, and persists a `SessionBundle`.
pub struct SessionRecorder {
    /// Unique identifier for the current session.
    id: Uuid,
    /// Timestamp when the session started.
    started_at: DateTime<Utc>,
    /// Optional metadata supplied by the user.
    metadata: Option<SessionMetadata>,
    /// Dynamically registered collectors.
    collectors: Vec<Box<dyn EventCollector + Send + Sync>>,
    /// Sender side of the event channel.
    event_tx: Option<Sender<Event>>,
    /// Receiver side of the event channel.
    event_rx: Option<Receiver<Event>>,
    /// Handles for the async collector tasks.
    handles: Vec<JoinHandle<()>>,
    /// Flag shared with collector tasks to signal shutdown.
    running: Arc<AtomicBool>,
}

impl SessionRecorder {
    /// Creates a new recorder instance with no collectors attached.
    pub fn new() -> Self {
        SessionRecorder {
            id: Uuid::new_v4(),
            started_at: Utc::now(),
            metadata: None,
            collectors: Vec::new(),
            event_tx: None,
            event_rx: None,
            handles: Vec::new(),
            running: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Registers a new collector for the current session.
    ///
    /// The collector is stored as a boxed trait object and will be started
    /// when `start` is called.
    pub fn add_collector(&mut self, collector: Box<dyn EventCollector + Send + Sync>) {
        self.collectors.push(collector);
    }

    /// Starts the recording session according to the supplied configuration.
    ///
    /// This method spawns a task for each enabled collector, creates the event
    /// channel, and writes a header log entry.  All errors are wrapped in
    /// `RecorderError`.
    pub async fn start(&mut self, config_path: &Path) -> Result<(), RecorderError> {
        // --------------------------------------------------------------------
        // Load configuration
        // --------------------------------------------------------------------
        let config_data = fs::read_to_string(config_path).map_err(RecorderError::Io)?;
        let config: RecorderConfig = serde_json::from_str(&config_data).map_err(RecorderError::Json)?;

        // Apply configuration values
        self.id = config.id.unwrap_or_else(Uuid::new_v4);
        self.started_at = Utc::now();
        self.metadata = config.metadata.clone();

        // --------------------------------------------------------------------
        // Prepare event channel
        // --------------------------------------------------------------------
        let (tx, rx) = mpsc::channel::<Event>(1024);
        self.event_tx = Some(tx);
        self.event_rx = Some(rx);
        self.running.store(true, Ordering::SeqCst);

        // --------------------------------------------------------------------
        // Register collectors based on config
        // --------------------------------------------------------------------
        if config.command {
            self.add_collector(Box::new(CommandCollector::new()));
        }
        if config.filesystem {
            self.add_collector(Box::new(FilesystemCollector::new()));
        }
        if config.network {
            self.add_collector(Box::new(NetworkCollector::new()));
        }

        // --------------------------------------------------------------------
        // Spawn collector tasks
        // --------------------------------------------------------------------
        for mut collector in self.collectors.drain(..) {
            let tx_clone = self
                .event_tx
                .as_ref()
                .ok_or(RecorderError::ChannelSend)?
                .clone();
            let running_flag = self.running.clone();

            // Log before spawning
            info!(
                "[INFO] Starting collector {}",
                collector.name()
            );

            // Start the collector; abort if it fails
            collector.start().map_err(|e| RecorderError::Collector(e.to_string()))?;

            let handle = tokio::spawn(async move {
                while running_flag.load(Ordering::SeqCst) {
                    match collector.poll() {
                        Some(event) => {
                            if let Err(e) = tx_clone.send(event).await {
                                warn!("Failed to forward event: {}", e);
                                break;
                            }
                        }
                        None => {
                            // No new event; yield to the scheduler.
                            tokio::task::yield_now().await;
                        }
                    }
                }
                // Ensure collector is stopped even on early exit.
                if let Err(e) = collector.stop() {
                    warn!("Error stopping collector {}: {}", collector.name(), e);
                }
            });
            self.handles.push(handle);
        }

        // --------------------------------------------------------------------
        // Log session start
        // --------------------------------------------------------------------
        info!(
            "[INFO] Starting session {} with {} collectors",
            self.id,
            self.collectors.len()
        );
        self.record_run_history("started", 0)?;

        Ok(())
    }

    /// Stops all collectors, flushes buffers, aggregates events, and writes the
    /// complete `SessionBundle` to disk.
    ///
    /// Returns the constructed bundle on success.
    pub async fn stop(&mut self) -> Result<SessionBundle, RecorderError> {
        let stop_instant = Instant::now();

        // Signal collector tasks to stop
        self.running.store(false, Ordering::SeqCst);
        info!("[INFO] Stopping collectors");

        // Await all collector tasks
        for handle in self.handles.drain(..) {
            if let Err(e) = handle.await {
                warn!("Collector task panicked: {:?}", e);
            }
        }

        // Close the sender side so the receiver knows no more events will arrive
        self.event_tx.take();

        // Collect remaining events
        let mut events: Vec<Event> = Vec::new();
        if let Some(mut rx) = self.event_rx.take() {
            while let Some(event) = rx.recv().await {
                events.push(event);
            }
        }

        // Ensure chronological order
        events.sort_by_key(|e| e.timestamp());

        // Build the session bundle
        let bundle = SessionBundle {
            id: self.id,
            started_at: self.started_at,
            events,
            metadata: self.metadata.clone(),
        };

        // Persist the bundle
        let session_dir = Self::session_dir()?;
        fs::create_dir_all(&session_dir)?;
        let bundle_path = session_dir.join(format!("{}.json", self.id));
        let file = File::create(&bundle_path).map_err(RecorderError::Io)?;
        serde_json::to_writer_pretty(file, &bundle).map_err(RecorderError::Json)?;

        // Log completion
        let duration_secs = stop_instant.elapsed().as_secs();
        info!(
            "[INFO] Session {} saved to {} (duration: {}s)",
            self.id,
            bundle_path.display(),
            duration_secs
        );
        self.record_run_history("completed", duration_secs)?;

        Ok(bundle)
    }

    /// Returns the directory where session bundles are stored.
    fn session_dir() -> Result<PathBuf, RecorderError> {
        let home = std::env::var("HOME").map_err(|e| RecorderError::Config(e.to_string()))?;
        Ok(Path::new(&home).join(".tracecraft").join("sessions"))
    }

    /// Records a simple run‑history entry in a JSON lines file under
    /// `~/.tracecraft/run_history.log`.  The file is appended to atomically.
    fn record_run_history(&self, status: &str, duration_secs: u64) -> Result<(), RecorderError> {
        let home = std::env::var("HOME").map_err(|e| RecorderError::Config(e.to_string()))?;
        let log_path = Path::new(&home)
            .join(".tracecraft")
            .join("run_history.log");

        let entry = json!({
            "session_id": self.id.to_string(),
            "timestamp": Utc::now().to_rfc3339(),
            "status": status,
            "duration_seconds": duration_secs
        });

        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
            .map_err(RecorderError::Io)?;
        writeln!(file, "{}", entry).map_err(RecorderError::Io)?;
        Ok(())
    }
}

/// Trait that all event collectors must implement.
///
/// The trait is deliberately small to keep collector implementations focused.
#[async_trait::async_trait]
pub trait EventCollector {
    /// Human‑readable name used for logging.
    fn name(&self) -> &str;

    /// Begins polling or subscribing to the source.
    fn start(&mut self) -> Result<(), anyhow::Error>;

    /// Releases any allocated resources.
    fn stop(&mut self) -> Result<(), anyhow::Error>;

    /// Returns the next captured event or `None` if no new data is available.
    fn poll(&mut self) -> Option<Event>;
}