use std::collections::{hash_map::DefaultHasher, HashMap};
use std::fs;
use std::hash::{Hash, Hasher};
use std::io;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, SystemTime};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use thiserror::Error;
use tokio::sync::mpsc::Sender;

use crate::event::Event;
use crate::models::{
    ChangeType, FileChangeEvent, SessionMetadata,
};

/// Errors that can be produced by the filesystem collector.
#[derive(Error, Debug)]
pub enum FilesystemError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("Hashing error")]
    Hash,
}

/// Collector that watches a set of paths for file system changes and streams
/// `FileChangeEvent`s to the recorder.
///
/// The collector runs a background thread that periodically scans the configured
/// paths, detects creations, modifications and deletions, computes a lightweight
/// SHA‑256‑like hash of the file contents (using the default hasher) and emits
/// events through the provided `Sender<Event>`.
pub struct FilesystemCollector {
    /// Sender used to forward events to the `SessionRecorder`.
    event_tx: Sender<Event>,
    /// Optional user‑provided metadata attached to each event.
    metadata: Option<SessionMetadata>,
    /// Shared flag signalling the background thread to stop.
    running: Arc<Mutex<bool>>,
    /// Handle of the background thread.
    handle: Option<JoinHandle<()>>,
    /// Paths that should be watched. If empty, the current directory is watched.
    watched_paths: Vec<PathBuf>,
    /// Internal state tracking known files and their last observed metadata.
    known: Arc<Mutex<HashMap<PathBuf, (Option<SystemTime>, Option<String>)>>>,
}

impl FilesystemCollector {
    /// Create a new `FilesystemCollector`.
    ///
    /// * `event_tx` – Sender used to deliver events to the recorder.
    /// * `metadata` – Optional metadata that will be attached to each event.
    /// * `watched_paths` – List of directories or files to monitor. An empty
    ///   vector defaults to the current working directory.
    pub fn new(
        event_tx: Sender<Event>,
        metadata: Option<SessionMetadata>,
        watched_paths: Vec<PathBuf>,
    ) -> Self {
        let paths = if watched_paths.is_empty() {
            vec![std::env::current_dir().unwrap_or_else(|e| {
                error!("Failed to obtain current directory: {}", e);
                PathBuf::from(".")
            })]
        } else {
            watched_paths
        };

        FilesystemCollector {
            event_tx,
            metadata,
            running: Arc::new(Mutex::new(false)),
            handle: None,
            watched_paths: paths,
            known: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Compute a deterministic hash for a byte slice using the default hasher.
    fn compute_hash(data: &[u8]) -> Result<String, FilesystemError> {
        let mut hasher = DefaultHasher::new();
        data.hash(&mut hasher);
        Ok(format!("{:x}", hasher.finish()))
    }

    /// Scan a single path and return a map of file -> (modified_time, content_hash).
    fn scan_path(path: &PathBuf) -> Result<HashMap<PathBuf, (Option<SystemTime>, Option<String>)>, FilesystemError> {
        let mut result = HashMap::new();

        if path.is_file() {
            let metadata = fs::metadata(path)?;
            let mtime = metadata.modified().ok();
            let content_hash = if metadata.is_file() {
                let data = fs::read(path)?;
                Some(Self::compute_hash(&data)?)
            } else {
                None
            };
            result.insert(path.clone(), (mtime, content_hash));
        } else if path.is_dir() {
            for entry in fs::read_dir(path)? {
                let entry = entry?;
                let child_path = entry.path();
                if child_path.is_dir() {
                    // Recurse into sub‑directories.
                    let sub = Self::scan_path(&child_path)?;
                    result.extend(sub);
                } else {
                    let metadata = fs::metadata(&child_path)?;
                    let mtime = metadata.modified().ok();
                    let content_hash = if metadata.is_file() {
                        let data = fs::read(&child_path)?;
                        Some(Self::compute_hash(&data)?)
                    } else {
                        None
                    };
                    result.insert(child_path, (mtime, content_hash));
                }
            }
        }

        Ok(result)
    }

    /// Emit a `FileChangeEvent` through the channel, logging any failure.
    fn emit_event(&self, event: FileChangeEvent) {
        let ev = Event::FileChange(event);
        match self.event_tx.try_send(ev) {
            Ok(_) => {}
            Err(e) => {
                warn!("Failed to send filesystem event: {}", e);
            }
        }
    }

    /// Core loop executed in the background thread. It periodically scans the
    /// watched paths, diffs the result against the previously known state and
    /// generates events for creations, modifications and deletions.
    fn run_loop(
        running: Arc<Mutex<bool>>,
        known: Arc<Mutex<HashMap<PathBuf, (Option<SystemTime>, Option<String>)>>>,
        watched_paths: Vec<PathBuf>,
        sender: Sender<Event>,
        metadata: Option<SessionMetadata>,
    ) {
        info!("Filesystem collector thread started");
        while *running.lock().unwrap() {
            // Scan current state.
            let mut current = HashMap::new();
            for path in &watched_paths {
                match FilesystemCollector::scan_path(path) {
                    Ok(map) => {
                        current.extend(map);
                    }
                    Err(e) => {
                        error!("Error scanning path {:?}: {}", path, e);
                    }
                }
            }

            // Determine differences.
            let mut known_guard = known.lock().unwrap();
            // Detect deletions.
            for known_path in known_guard.keys() {
                if !current.contains_key(known_path) {
                    let event = FileChangeEvent {
                        timestamp: Utc::now(),
                        path: known_path.clone(),
                        change_type: ChangeType::Deleted,
                        content_hash: None,
                    };
                    let collector = FilesystemCollector {
                        event_tx: sender.clone(),
                        metadata: metadata.clone(),
                        running: running.clone(),
                        handle: None,
                        watched_paths: watched_paths.clone(),
                        known: known.clone(),
                    };
                    collector.emit_event(event);
                }
            }

            // Detect creations and modifications.
            for (path, (mtime_opt, hash_opt)) in current.iter() {
                match known_guard.get(path) {
                    None => {
                        // New file.
                        let event = FileChangeEvent {
                            timestamp: Utc::now(),
                            path: path.clone(),
                            change_type: ChangeType::Created,
                            content_hash: hash_opt.clone(),
                        };
                        let collector = FilesystemCollector {
                            event_tx: sender.clone(),
                            metadata: metadata.clone(),
                            running: running.clone(),
                            handle: None,
                            watched_paths: watched_paths.clone(),
                            known: known.clone(),
                        };
                        collector.emit_event(event);
                    }
                    Some((prev_mtime, prev_hash)) => {
                        // Modification detection.
                        let modified = match (prev_mtime, mtime_opt) {
                            (Some(prev), Some(curr)) => prev != curr,
                            (None, Some(_)) => true,
                            _ => false,
                        };
                        let hash_changed = prev_hash != hash_opt;
                        if modified || hash_changed {
                            let event = FileChangeEvent {
                                timestamp: Utc::now(),
                                path: path.clone(),
                                change_type: ChangeType::Modified,
                                content_hash: hash_opt.clone(),
                            };
                            let collector = FilesystemCollector {
                                event_tx: sender.clone(),
                                metadata: metadata.clone(),
                                running: running.clone(),
                                handle: None,
                                watched_paths: watched_paths.clone(),
                                known: known.clone(),
                            };
                            collector.emit_event(event);
                        }
                    }
                }
            }

            // Update known state.
            *known_guard = current;

            // Sleep before next iteration.
            thread::sleep(Duration::from_millis(500));
        }
        info!("Filesystem collector thread exiting");
    }
}

impl EventCollector for FilesystemCollector {
    /// Start the collector by spawning a background thread that monitors the file
    /// system. Returns an error if the thread cannot be created.
    fn start(&mut self) -> Result<(), FilesystemError> {
        let mut running_guard = self.running.lock().unwrap();
        if *running_guard {
            warn!("Filesystem collector already running");
            return Ok(());
        }
        *running_guard = true;
        drop(running_guard);

        let running = self.running.clone();
        let known = self.known.clone();
        let paths = self.watched_paths.clone();
        let sender = self.event_tx.clone();
        let metadata = self.metadata.clone();

        let handle = thread::Builder::new()
            .name("filesystem-collector".to_string())
            .spawn(move || {
                FilesystemCollector::run_loop(running, known, paths, sender, metadata);
            })
            .map_err(|e| FilesystemError::Io(io::Error::new(io::ErrorKind::Other, e)))?;

        self.handle = Some(handle);
        info!("Filesystem collector started");
        Ok(())
    }

    /// Stop the collector by signalling the background thread to exit and joining
    /// the thread. Returns an error if the thread cannot be joined.
    fn stop(&mut self) -> Result<(), FilesystemError> {
        {
            let mut running_guard = self.running.lock().unwrap();
            if !*running_guard {
                warn!("Filesystem collector stop called while not running");
                return Ok(());
            }
            *running_guard = false;
        }

        if let Some(handle) = self.handle.take() {
            handle
                .join()
                .map_err(|_| FilesystemError::Io(io::Error::new(
                    io::ErrorKind::Other,
                    "Failed to join filesystem thread",
                )))?;
        }
        info!("Filesystem collector stopped");
        Ok(())
    }

    /// The collector pushes events directly; polling returns `None`.
    fn poll(&mut self) -> Option<Event> {
        None
    }
}