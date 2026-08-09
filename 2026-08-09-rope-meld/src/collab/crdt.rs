use std::cell::RefCell;
use std::collections::{HashMap, VecDeque};
use std::ops::Range;
use std::rc::Rc;

use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

use crate::core::engine::{EditError, RopePieceTableEngine};

/// Identifier for a participant in the collaborative session.
pub type UserId = u64;

/// The kind of operation represented by a `DocumentOperation`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum OperationKind {
    Insert,
    Delete,
}

/// Payload for an insert operation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InsertPayload {
    pub pos: usize,
    pub text: String,
}

/// Payload for a delete operation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeletePayload {
    pub range: Range<usize>,
}

/// A fully described operation that can be applied to the document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentOperation {
    pub op_id: Uuid,
    pub timestamp: u64,
    pub author: UserId,
    pub kind: OperationKind,
    #[serde(flatten)]
    pub payload: OperationPayload,
}

/// Union type for the operation payloads.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", content = "data")]
pub enum OperationPayload {
    Insert(InsertPayload),
    Delete(DeletePayload),
}

/// Version vector tracking the highest Lamport timestamp seen per participant.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct VersionVector {
    pub entries: HashMap<UserId, u64>,
}

impl VersionVector {
    /// Creates a new, empty version vector.
    pub fn new() -> Self {
        Self {
            entries: HashMap::new(),
        }
    }

    /// Updates the vector with the given author and timestamp.
    pub fn update(&mut self, author: UserId, timestamp: u64) {
        self.entries
            .entry(author)
            .and_modify(|t| {
                if *t < timestamp {
                    *t = timestamp;
                }
            })
            .or_insert(timestamp);
    }

    /// Returns the last known timestamp for `author`, or `0` if none.
    pub fn get(&self, author: UserId) -> u64 {
        *self.entries.get(&author).unwrap_or(&0)
    }
}

/// Errors that can arise while applying an edit to the piece‑table engine.
#[derive(Debug, Error)]
pub enum EditError {
    #[error("invalid range")]
    InvalidRange,
    #[error("other edit error: {0}")]
    Other(String),
}

/// Errors that can arise while synchronising operations.
#[derive(Debug, Error)]
pub enum SyncError {
    #[error("corrupt state")]
    CorruptState,
    #[error("transient error: {0}")]
    TransientError(String),
    #[error("invalid operation")]
    InvalidOperation,
}

/// Represents a local edit before it is turned into a `DocumentOperation`.
#[derive(Debug, Clone)]
pub enum EditKind {
    Insert { pos: usize, text: String },
    Delete { range: Range<usize> },
}

#[derive(Debug, Clone)]
pub struct Edit {
    pub author: UserId,
    pub kind: EditKind,
}

/// The core CRDT synchronisation engine. It is stateless with respect to the document
/// content (the mutable model lives in `RopePieceTableEngine`) but maintains causal
/// metadata such as Lamport timestamps and version vectors.
pub struct CRDTSyncEngine {
    /// Shared mutable reference to the underlying piece‑table engine.
    engine: Rc<RefCell<RopePieceTableEngine>>,
    /// The Lamport clock for this participant.
    lamport_clock: u64,
    /// Version vector tracking what we have already seen.
    version_vector: VersionVector,
    /// Log of all operations generated locally (used for merging).
    op_log: VecDeque<DocumentOperation>,
    /// Retry counters for transient remote operations.
    retry_counts: HashMap<Uuid, u8>,
    /// Maximum number of retries for a transient error.
    max_retries: u8,
}

impl CRDTSyncEngine {
    /// Creates a new synchronisation engine bound to `engine`. The caller supplies its
    /// own `author_id` which will be used for all locally generated operations.
    pub fn new(author_id: UserId, engine: Rc<RefCell<RopePieceTableEngine>>) -> Self {
        Self {
            engine,
            lamport_clock: 0,
            version_vector: VersionVector::new(),
            op_log: VecDeque::new(),
            retry_counts: HashMap::new(),
            max_retries: 3,
        }
    }

    /// Generates a `DocumentOperation` from a local `Edit`. The operation receives a fresh
    /// UUID and a Lamport timestamp that is monotonically increasing.
    pub fn local_op(&mut self, edit: Edit) -> DocumentOperation {
        // Increment our Lamport clock.
        self.lamport_clock = self.lamport_clock.saturating_add(1);
        let timestamp = self.lamport_clock;

        // Build the payload based on the edit kind.
        let (kind, payload) = match edit.kind {
            EditKind::Insert { pos, text } => (
                OperationKind::Insert,
                OperationPayload::Insert(InsertPayload { pos, text }),
            ),
            EditKind::Delete { range } => (
                OperationKind::Delete,
                OperationPayload::Delete(DeletePayload { range }),
            ),
        };

        let op = DocumentOperation {
            op_id: Uuid::new_v4(),
            timestamp,
            author: edit.author,
            kind,
            payload,
        };

        // Record the operation locally.
        self.op_log.push_back(op.clone());
        self.version_vector.update(edit.author, timestamp);
        op
    }

    /// Applies a remote `DocumentOperation` to the underlying engine after validating
    /// causality. If the operation cannot be applied because of a transient problem,
    /// it will be queued and retried up to `max_retries` times.
    pub fn remote_op(&mut self, op: DocumentOperation) -> Result<(), SyncError> {
        // Causality check: the operation's timestamp must be greater than the last
        // timestamp we have recorded for the same author.
        let last_seen = self.version_vector.get(op.author);
        if op.timestamp <= last_seen {
            // Duplicate or out‑of‑order operation – ignore it.
            return Ok(());
        }

        // Attempt to apply the operation to the engine.
        let apply_result = {
            let mut engine = self
                .engine
                .borrow_mut();
            engine.apply(op.clone())
        };

        match apply_result {
            Ok(_) => {
                // Successful application – update our version vector.
                self.version_vector.update(op.author, op.timestamp);
                // Reset any retry counter for this op.
                self.retry_counts.remove(&op.op_id);
                Ok(())
            }
            Err(EditError::InvalidRange) => {
                // Validation error – silently ignore as per design.
                self.version_vector.update(op.author, op.timestamp);
                Ok(())
            }
            Err(e) => {
                // Treat any other edit error as a transient failure.
                let count = self.retry_counts.entry(op.op_id).or_insert(0);
                if *count < self.max_retries {
                    *count += 1;
                    Err(SyncError::TransientError(format!(
                        "retry {}/{} for op {}",
                        count,
                        self.max_retries,
                        op.op_id
                    )))
                } else {
                    // Exceeded retries – surface a non‑fatal warning.
                    self.retry_counts.remove(&op.op_id);
                    Err(SyncError::InvalidOperation)
                }
            }
        }
    }

    /// Computes the list of operations that the peer, represented by `peer_state`,
    /// is missing. The returned vector is ordered by Lamport timestamp.
    pub fn merge_state(&self, peer_state: &VersionVector) -> Vec<DocumentOperation> {
        let mut missing: Vec<DocumentOperation> = self
            .op_log
            .iter()
            .filter(|op| {
                let peer_ts = peer_state.get(op.author);
                op.timestamp > peer_ts
            })
            .cloned()
            .collect();

        // Ensure deterministic ordering.
        missing.sort_by_key(|op| (op.timestamp, op.author));
        missing
    }

    /// Returns a reference to the current version vector (useful for peers).
    pub fn current_version_vector(&self) -> &VersionVector {
        &self.version_vector
    }
}