use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};
use std::io::{self, Read};
use std::process::{Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc,
};
use std::thread;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use tokio::sync::mpsc::Sender;

use crate::event::Event;
use crate::models::{CommandEvent, SessionMetadata};

/// Errors that can be produced by the command collector.
#[derive(thiserror::Error, Debug)]
pub enum CommandError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("Command execution failed: {0}")]
    Exec(String),
    #[error("Hashing error")]
    Hash,
}

/// Trait that all collectors must implement.  It lives in `crate::event` and is
/// imported by the recorder.  The collector is responsible for emitting
/// `Event`s that are later aggregated by the `SessionRecorder`.
pub trait EventCollector {
    /// Start the collector.  This may spawn background threads or async tasks.
    fn start(&mut self) -> Result<(), CommandError>;
    /// Stop the collector and clean up resources.
    fn stop(&mut self) -> Result<(), CommandError>;
    /// Poll for the next event.  Collectors that push events directly to the
    /// recorder can return `None` here.
    fn poll(&mut self) -> Option<Event>;
}

/// A concrete collector that watches commands executed in the current process
/// (or any child processes it spawns) and streams `CommandEvent`s to the
/// recorder.
///
/// The collector works by exposing a `record_command` method that can be called
/// by the surrounding application (e.g. a wrapper around the user's shell).  It
/// executes the command, captures stdout/stderr, computes lightweight hashes,
/// and sends a `CommandEvent` through the provided `Sender<Event>`.
pub struct CommandCollector {
    /// Sender used to forward events to the `SessionRecorder`.
    event_tx: Sender<Event>,
    /// Optional user‑provided metadata that is attached to each event.
    metadata: Option<SessionMetadata>,
    /// Shared flag signalling the background thread to stop.
    running: Arc<AtomicBool>,
    /// Handle of the background thread that periodically flushes pending
    /// events.  The thread is optional because the collector can also be used
    /// in a purely synchronous fashion.
    handle: Option<thread::JoinHandle<()>>,
    /// Buffer of events that have been generated but not yet sent.  The
    /// background thread drains this buffer.
    pending: Arc<std::sync::Mutex<Vec<Event>>>,
}

impl CommandCollector {
    /// Create a new `CommandCollector`.
    ///
    /// * `event_tx` – Sender used to deliver events to the recorder.
    /// * `metadata` – Optional metadata that will be attached to each event.
    pub fn new(event_tx: Sender<Event>, metadata: Option<SessionMetadata>) -> Self {
        Self {
            event_tx,
            metadata,
            running: Arc::new(AtomicBool::new(false)),
            handle: None,
            pending: Arc::new(std::sync::Mutex::new(Vec::new())),
        }
    }

    /// Record a command that the user executed.  This method runs the command,
    /// captures its output, builds a `CommandEvent`, and queues it for delivery.
    ///
    /// The command is executed with `sh -c` on Unix platforms and `cmd /C` on
    /// Windows.  The method returns an error if the command cannot be started
    /// or if the output cannot be read.
    pub fn record_command(&self, command: &str) -> Result<(), CommandError> {
        let start = Instant::now();

        // Choose the appropriate shell based on the target OS.
        #[cfg(unix)]
        let mut child = Command::new("sh")
            .arg("-c")
            .arg(command)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| CommandError::Exec(e.to_string()))?;

        #[cfg(windows)]
        let mut child = Command::new("cmd")
            .args(&["/C", command])
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| CommandError::Exec(e.to_string()))?;

        // Capture stdout.
        let mut stdout = Vec::new();
        if let Some(mut out) = child.stdout.take() {
            out.read_to_end(&mut stdout)?;
        }

        // Capture stderr.
        let mut stderr = Vec::new();
        if let Some(mut err) = child.stderr.take() {
            err.read_to_end(&mut stderr)?;
        }

        // Wait for the process to exit.
        let exit_status = child
            .wait()
            .map_err(|e| CommandError::Exec(e.to_string()))?;
        let exit_code = exit_status.code().unwrap_or(-1);

        // Compute lightweight hashes for stdout and stderr.
        let stdout_hash = hash_bytes(&stdout);
        let stderr_hash = hash_bytes(&stderr);

        // Build the event.
        let event = CommandEvent {
            timestamp: Utc::now(),
            command: command.to_string(),
            exit_code,
            stdout_hash,
            stderr_hash,
        };

        // Wrap into the generic `Event` enum (defined elsewhere).
        let generic_event = Event::Command(event);

        // Queue the event for the background thread.
        {
            let mut pending = self
                .pending
                .lock()
                .map_err(|_| CommandError::Hash)?;
            pending.push(generic_event);
        }

        let duration = start.elapsed();
        info!(
            "[CommandCollector] Executed `{}` (exit: {}, duration: {:.2?})",
            command, exit_code, duration
        );

        Ok(())
    }

    /// Internal helper that continuously drains the pending queue and forwards
    /// events to the recorder.  It runs in a dedicated thread while the collector
    /// is active.
    fn run_sender_loop(pending: Arc<std::sync::Mutex<Vec<Event>>>, tx: Sender<Event>, running: Arc<AtomicBool>) {
        while running.load(Ordering::SeqCst) {
            // Drain pending events.
            let mut batch = Vec::new();
            {
                let mut guard = pending.lock().expect("Mutex poisoned");
                if !guard.is_empty() {
                    batch.append(&mut *guard);
                }
            }

            // Send each event; if the channel is closed we abort.
            for ev in batch {
                if let Err(e) = tx.blocking_send(ev) {
                    error!("[CommandCollector] Failed to send event: {}", e);
                    // If the receiver is gone, stop the collector.
                    running.store(false, Ordering::SeqCst);
                    break;
                }
            }

            // Sleep briefly to avoid busy‑waiting.
            thread::sleep(Duration::from_millis(100));
        }

        // Flush any remaining events before exiting.
        let remaining = {
            let mut guard = pending.lock().expect("Mutex poisoned");
            std::mem::take(&mut *guard)
        };
        for ev in remaining {
            let _ = tx.blocking_send(ev);
        }
        info!("[CommandCollector] Sender loop terminated");
    }
}

impl EventCollector for CommandCollector {
    fn start(&mut self) -> Result<(), CommandError> {
        if self.running.load(Ordering::SeqCst) {
            warn!("[CommandCollector] Already running");
            return Ok(());
        }
        self.running.store(true, Ordering::SeqCst);
        let pending = Arc::clone(&self.pending);
        let tx = self.event_tx.clone();
        let running = Arc::clone(&self.running);
        let handle = thread::spawn(move || Self::run_sender_loop(pending, tx, running));
        self.handle = Some(handle);
        info!("[CommandCollector] Started");
        Ok(())
    }

    fn stop(&mut self) -> Result<(), CommandError> {
        if !self.running.load(Ordering::SeqCst) {
            warn!("[CommandCollector] Not running");
            return Ok(());
        }
        self.running.store(false, Ordering::SeqCst);
        if let Some(handle) = self.handle.take() {
            handle
                .join()
                .map_err(|_| CommandError::Exec("Thread panicked".into()))?;
        }
        info!("[CommandCollector] Stopped");
        Ok(())
    }

    fn poll(&mut self) -> Option<Event> {
        // This collector pushes events directly via the background thread,
        // therefore `poll` does not produce events.
        None
    }
}

/// Compute a deterministic, non‑cryptographic hash of a byte slice and return
/// it as a hexadecimal string.  The implementation uses `DefaultHasher` which
/// is stable for the duration of a single process.
fn hash_bytes(data: &[u8]) -> String {
    let mut hasher = DefaultHasher::new();
    data.hash(&mut hasher);
    format!("{:x}", hasher.finish())
}

// ---------------------------------------------------------------------------
// Data structures required for serialization.  They are duplicated here to
// avoid pulling in the full `models` module, but they must stay in sync with
// the definitions in `src/models.rs`.
//
// In production code these would be re‑exported from the central models file.
// ---------------------------------------------------------------------------

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CommandEvent {
    pub timestamp: DateTime<Utc>,
    pub command: String,
    pub exit_code: i32,
    pub stdout_hash: String,
    pub stderr_hash: String,
}

// The generic `Event` enum is defined elsewhere in the crate.  We re‑declare a
// minimal version here solely for type checking; the real definition lives in
// `src/event.rs`.
#[allow(dead_code)]
enum Event {
    Command(CommandEvent),
    // Other variants omitted for brevity.
}

// ---------------------------------------------------------------------------
// Unit tests for the command collector.  They exercise the core behaviour:
// * successful command execution,
// * error handling for a non‑existent command,
// * proper shutdown of the background thread.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::sync::mpsc;
    use tokio::time::timeout;

    #[tokio::test]
    async fn test_record_simple_command() {
        let (tx, mut rx) = mpsc::channel(10);
        let collector = CommandCollector::new(tx, None);
        collector.record_command("echo hello").expect("record_command failed");
        // Give the background thread a moment to forward the event.
        let ev = timeout(Duration::from_secs(1), rx.recv())
            .await
            .expect("timeout")
            .expect("no event received");
        match ev {
            Event::Command(e) => {
                assert_eq!(e.command, "echo hello");
                assert_eq!(e.exit_code, 0);
                assert!(!e.stdout_hash.is_empty());
            }
            _ => panic!("unexpected event type"),
        }
    }

    #[tokio::test]
    async fn test_record_failing_command() {
        let (tx, mut rx) = mpsc::channel(10);
        let collector = CommandCollector::new(tx, None);
        // Intentionally run a command that exits with non‑zero status.
        collector
            .record_command("false")
            .expect("record_command failed");
        let ev = timeout(Duration::from_secs(1), rx.recv())
            .await
            .expect("timeout")
            .expect("no event received");
        match ev {
            Event::Command(e) => {
                assert_eq!(e.command, "false");
                assert_ne!(e.exit_code, 0);
            }
            _ => panic!("unexpected event type"),
        }
    }

    #[tokio::test]
    async fn test_start_and_stop() {
        let (tx, _rx) = mpsc::channel(10);
        let mut collector = CommandCollector::new(tx, None);
        collector.start().expect("start failed");
        assert!(collector.running.load(Ordering::SeqCst));
        collector.stop().expect("stop failed");
        assert!(!collector.running.load(Ordering::SeqCst));
    }

    #[tokio::test]
    async fn test_double_start_is_noop() {
        let (tx, _rx) = mpsc::channel(10);
        let mut collector = CommandCollector::new(tx, None);
        collector.start().expect("first start failed");
        collector.start().expect("second start failed");
        collector.stop().expect("stop failed");
    }

    #[tokio::test]
    async fn test_double_stop_is_noop() {
        let (tx, _rx) = mpsc::channel(10);
        let mut collector = CommandCollector::new(tx, None);
        collector.start().expect("start failed");
        collector.stop().expect("first stop failed");
        collector.stop().expect("second stop failed");
    }

    #[tokio::test]
    async fn test_poll_returns_none() {
        let (tx, _rx) = mpsc::channel(10);
        let mut collector = CommandCollector::new(tx, None);
        assert!(collector.poll().is_none());
    }
}