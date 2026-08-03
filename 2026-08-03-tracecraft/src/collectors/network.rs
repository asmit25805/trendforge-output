use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::io;
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::thread;
use std::time::Duration;

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use thiserror::Error;
use tokio::sync::mpsc::Sender;
use tokio::task::JoinHandle;

use crate::event::Event;
use crate::models::{NetworkEvent, SessionMetadata};

/// Errors that can be produced by the network collector.
#[derive(Error, Debug)]
pub enum NetworkError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("Hashing error")]
    Hash,
    #[error("Collector was not started")]
    NotStarted,
    #[error("Channel send error")]
    ChannelSend,
}

/// Collector that watches outgoing HTTP requests made via `reqwest` and streams
/// `NetworkEvent`s to the recorder.
///
/// The collector does not perform real packet sniffing; instead it provides a
/// static `record` function that can be called by any part of the application
/// that performs a request.  Recorded events are buffered and flushed to the
/// recorder in a background thread.
pub struct NetworkCollector {
    /// Sender used to forward events to the `SessionRecorder`.
    event_tx: Sender<Event>,
    /// Optional user‑provided metadata attached to each event.
    metadata: Option<SessionMetadata>,
    /// Shared flag signalling the background thread to stop.
    running: Arc<AtomicBool>,
    /// Handle of the background thread.
    handle: Option<JoinHandle<()>>,
    /// Buffer of pending network events.
    pending: Arc<Mutex<Vec<NetworkEvent>>>,
}

impl NetworkCollector {
    /// Create a new `NetworkCollector`.
    ///
    /// * `event_tx` – Sender used to deliver events to the recorder.
    /// * `metadata` – Optional metadata that will be attached to each event.
    pub fn new(event_tx: Sender<Event>, metadata: Option<SessionMetadata>) -> Self {
        Self {
            event_tx,
            metadata,
            running: Arc::new(AtomicBool::new(false)),
            handle: None,
            pending: Arc::new(Mutex::new(Vec::new())),
        }
    }

    /// Record a network interaction.  This function can be called from anywhere
    /// in the code base that performs an HTTP request.
    ///
    /// The function computes lightweight hashes of the request and response bodies
    /// (if present) and stores a `NetworkEvent` in the collector's pending buffer.
    pub fn record(
        pending: &Arc<Mutex<Vec<NetworkEvent>>>,
        timestamp: DateTime<Utc>,
        method: impl Into<String>,
        url: impl Into<String>,
        status: u16,
        request_body: Option<&[u8]>,
        response_body: Option<&[u8]>,
    ) -> Result<(), NetworkError> {
        let request_hash = match request_body {
            Some(data) => Some(Self::hash_bytes(data)?),
            None => None,
        };
        let response_hash = match response_body {
            Some(data) => Some(Self::hash_bytes(data)?),
            None => None,
        };

        let event = NetworkEvent {
            timestamp,
            method: method.into(),
            url: url.into(),
            status,
            request_body_hash: request_hash,
            response_body_hash: response_hash,
        };

        let mut guard = pending
            .lock()
            .map_err(|_| NetworkError::Io(io::Error::new(io::ErrorKind::Other, "Mutex poisoned")))?;
        guard.push(event);
        Ok(())
    }

    /// Compute a deterministic hash for a byte slice using the default hasher.
    fn hash_bytes(data: &[u8]) -> Result<String, NetworkError> {
        let mut hasher = DefaultHasher::new();
        data.hash(&mut hasher);
        Ok(format!("{:x}", hasher.finish()))
    }

    /// Flush all pending events to the recorder channel.
    fn flush_pending(&self) -> Result<(), NetworkError> {
        let mut pending = self
            .pending
            .lock()
            .map_err(|_| NetworkError::Io(io::Error::new(io::ErrorKind::Other, "Mutex poisoned")))?;
        while let Some(net_event) = pending.pop() {
            let event = Event::Network(net_event);
            self.event_tx
                .blocking_send(event)
                .map_err(|_| NetworkError::ChannelSend)?;
        }
        Ok(())
    }
}

impl crate::collectors::command::EventCollector for NetworkCollector {
    /// Start the collector.  Spawns a background thread that periodically flushes
    /// pending network events to the recorder.
    fn start(&mut self) -> Result<(), NetworkError> {
        if self.running.load(Ordering::SeqCst) {
            warn!("NetworkCollector already started");
            return Ok(());
        }
        self.running.store(true, Ordering::SeqCst);
        let running = self.running.clone();
        let pending = self.pending.clone();
        let event_tx = self.event_tx.clone();

        // Use a Tokio task to avoid blocking the async runtime.
        let handle = tokio::spawn(async move {
            info!("NetworkCollector background task started");
            while running.load(Ordering::SeqCst) {
                // Flush pending events every 500 ms.
                {
                    let mut guard = match pending.lock() {
                        Ok(g) => g,
                        Err(_) => {
                            error!("Failed to lock pending network events");
                            continue;
                        }
                    };
                    while let Some(net_event) = guard.pop() {
                        let event = Event::Network(net_event);
                        if let Err(e) = event_tx.send(event).await {
                            error!("Failed to send network event: {}", e);
                        }
                    }
                }
                tokio::time::sleep(Duration::from_millis(500)).await;
            }
            // Final flush after stop signal.
            let mut guard = match pending.lock() {
                Ok(g) => g,
                Err(_) => {
                    error!("Failed to lock pending network events on shutdown");
                    return;
                }
            };
            while let Some(net_event) = guard.pop() {
                let event = Event::Network(net_event);
                if let Err(e) = event_tx.send(event).await {
                    error!("Failed to send network event during shutdown: {}", e);
                }
            }
            info!("NetworkCollector background task stopped");
        });

        self.handle = Some(handle);
        Ok(())
    }

    /// Stop the collector and wait for the background task to finish.
    fn stop(&mut self) -> Result<(), NetworkError> {
        if !self.running.load(Ordering::SeqCst) {
            return Err(NetworkError::NotStarted);
        }
        self.running.store(false, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            // Wait for the task to complete; ignore any panic.
            let _ = tokio::runtime::Handle::current().block_on(handle);
        }
        Ok(())
    }

    /// The collector pushes events asynchronously; `poll` always returns `None`.
    fn poll(&mut self) -> Option<Event> {
        None
    }
}