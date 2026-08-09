use std::ops::Range;
use std::sync::{Arc, Mutex};

use crate::core::engine::RopePieceTableEngine;
use crate::collab::crdt::{
    CRDTSyncEngine, DeletePayload, EditError, EditKind, InsertPayload, OperationKind,
    OperationPayload, SyncError, VersionVector,
};

/// A lightweight façade that mimics the public `EditorFacade` API for Rust examples.
///
/// It holds a piece‑table engine, a CRDT sync layer and a list of snapshot listeners.
/// All methods are synchronous for simplicity, but they return `Result` to surface
/// both fatal (`SyncError::CorruptState`) and validation (`EditError::InvalidRange`)
/// errors.
///
/// The façade can be used directly from a binary crate or from a `wasm‑bindgen`
/// binding layer without modification.
pub struct EditorFacade {
    /// Shared mutable engine protected by a mutex.
    engine: Arc<Mutex<RopePieceTableEngine>>,
    /// Shared mutable CRDT sync engine.
    sync: Arc<Mutex<CRDTSyncEngine>>,
    /// Listeners that receive a markdown snapshot after each successful operation.
    listeners: Arc<Mutex<Vec<Box<dyn Fn(String) + Send + Sync>>>>,
    /// Cached version vector for the local participant.
    version_vector: Arc<Mutex<VersionVector>>,
}

impl EditorFacade {
    /// Creates a new `EditorFacade` with fresh engine and sync components.
    pub fn new() -> Self {
        Self {
            engine: Arc::new(Mutex::new(RopePieceTableEngine::new())),
            sync: Arc::new(Mutex::new(CRDTSyncEngine::new())),
            listeners: Arc::new(Mutex::new(Vec::new())),
            version_vector: Arc::new(Mutex::new(VersionVector::new())),
        }
    }

    /// Registers a callback that will be invoked with the latest markdown after each
    /// successful edit. The callback is stored as a boxed `Fn(String)`.
    pub fn subscribe<F>(&self, callback: F)
    where
        F: Fn(String) + Send + Sync + 'static,
    {
        let mut listeners = self.listeners.lock().unwrap();
        listeners.push(Box::new(callback));
    }

    /// Applies a single edit to the document. The edit is first turned into a
    /// `DocumentOperation` by the CRDT layer, then applied to the engine. On success
    /// all registered listeners are notified with the new markdown.
    ///
    /// Returns `Ok(())` on success or an `EditError`/`SyncError` on failure.
    pub fn apply_edit(&self, edit: EditKind) -> Result<(), EditError> {
        // Convert the high‑level edit into a CRDT operation.
        let op = {
            let mut sync = self.sync.lock().unwrap();
            sync.local_op(edit)
        };

        // Apply the operation to the engine via the CRDT remote path.
        {
            let mut sync = self.sync.lock().unwrap();
            let mut engine = self.engine.lock().unwrap();
            sync.remote_op(op.clone(), &mut engine)
                .map_err(|e| match e {
                    SyncError::CorruptState => EditError::CorruptState,
                    SyncError::InvalidOperation => EditError::InvalidRange,
                    SyncError::TransientError(_) => EditError::Transient,
                })?;
        }

        // Update the local version vector.
        {
            let mut vv = self.version_vector.lock().unwrap();
            vv.update(op.author, op.timestamp);
        }

        // Notify listeners with the new markdown.
        self.notify_listeners();

        Ok(())
    }

    /// Returns the current markdown representation of the document.
    ///
    /// This method forwards to the engine's `render_markdown` implementation.
    pub fn get_markdown(&self) -> Result<String, EditError> {
        let engine = self.engine.lock().unwrap();
        engine
            .render_markdown()
            .map_err(|_| EditError::CorruptState)
    }

    /// Internal helper that walks the listeners and calls each with the latest markdown.
    fn notify_listeners(&self) {
        let markdown = match self.get_markdown() {
            Ok(md) => md,
            Err(_) => return,
        };
        let listeners = self.listeners.lock().unwrap();
        for listener in listeners.iter() {
            listener(markdown.clone());
        }
    }
}

/// Simulates a transient network failure that may occur when sending an operation
/// to a remote peer. The function returns `Ok(())` on success or `Err(())` on failure.
///
/// In a real application this would be an async network call; here we use a simple
/// deterministic pattern to illustrate retry logic.
fn simulate_transient_failure(attempt: usize) -> Result<(), ()> {
    // Fail the first two attempts, succeed on the third.
    if attempt < 3 {
        Err(())
    } else {
        Ok(())
    }
}

/// Applies an edit with automatic retries for transient errors. The function will
/// attempt the operation up to three times before propagating the error.
///
/// Returns `Ok(())` on success or the original `EditError` on permanent failure.
fn apply_with_retry(facade: &EditorFacade, edit: EditKind) -> Result<(), EditError> {
    let mut attempt = 0;
    loop {
        attempt += 1;
        match facade.apply_edit(edit.clone()) {
            Ok(()) => return Ok(()),
            Err(EditError::Transient) => {
                if attempt >= 3 {
                    return Err(EditError::Transient);
                }
                // Simulate waiting before retrying.
                std::thread::sleep(std::time::Duration::from_millis(50));
                // In a real scenario we would re‑send the operation; here we just retry.
                continue;
            }
            Err(e) => return Err(e),
        }
    }
}

fn main() {
    // Instantiate the façade.
    let facade = EditorFacade::new();

    // Register a listener that prints each markdown snapshot.
    facade.subscribe(|snapshot| {
        println!("--- Snapshot ---\n{}\n----------------", snapshot);
    });

    // Define a series of edits that mimic user actions.
    let edits = vec![
        EditKind::Insert {
            pos: 0,
            text: "Hello".to_string(),
        },
        EditKind::Insert {
            pos: 5,
            text: ", world".to_string(),
        },
        EditKind::Insert {
            pos: 12,
            text: "!".to_string(),
        },
        EditKind::Delete {
            range: Range { start: 5, end: 12 },
        },
        EditKind::Insert {
            pos: 5,
            text: " Rustacean".to_string(),
        },
    ];

    // Apply each edit, handling transient failures with retries.
    for edit in edits {
        match apply_with_retry(&facade, edit) {
            Ok(()) => {
                // Successful edit; the listener already printed the snapshot.
            }
            Err(EditError::InvalidRange) => {
                eprintln!("Warning: attempted edit with invalid range – ignored.");
            }
            Err(EditError::CorruptState) => {
                eprintln!("Fatal: engine entered a corrupt state. Exiting.");
                std::process::exit(1);
            }
            Err(EditError::Transient) => {
                eprintln!("Error: operation failed after retries. Continuing.");
            }
        }
    }

    // Retrieve the final markdown and display it.
    match facade.get_markdown() {
        Ok(md) => println!("\nFinal markdown:\n{}\n", md),
        Err(_) => eprintln!("Failed to render final markdown."),
    }
}