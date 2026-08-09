use std::ops::Range;

use uuid::Uuid;

use crate::core::engine::RopePieceTableEngine;
use crate::collab::crdt::{
    CRDTSyncEngine, DeletePayload, EditError, EditKind, InsertPayload, OperationKind,
    OperationPayload, DocumentOperation, SyncError, VersionVector,
};

#[test]
fn test_insert_operation_updates_markdown() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    let edit = EditKind::Insert {
        pos: 0,
        text: "Hello, world!".to_string(),
    };
    let op = sync.local_op(edit);
    sync.remote_op(op, &mut engine).expect("remote_op should succeed");

    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "Hello, world!");
}

#[test]
fn test_delete_operation_updates_markdown() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    // Insert initial text.
    let insert = EditKind::Insert {
        pos: 0,
        text: "Rustacean".to_string(),
    };
    let insert_op = sync.local_op(insert);
    sync.remote_op(insert_op, &mut engine).expect("insert should succeed");

    // Delete a slice.
    let delete_range = Range { start: 4, end: 8 };
    let delete = EditKind::Delete { range: delete_range.clone() };
    let delete_op = sync.local_op(delete);
    sync.remote_op(delete_op, &mut engine).expect("delete should succeed");

    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "Rusan");
}

#[test]
fn test_remote_operation_preserves_causality() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    // First operation.
    let first = EditKind::Insert {
        pos: 0,
        text: "First".to_string(),
    };
    let first_op = sync.local_op(first);
    sync.remote_op(first_op.clone(), &mut engine).expect("first op succeeds");

    // Simulate receiving an out‑of‑order operation with an older timestamp.
    let mut out_of_order = first_op.clone();
    out_of_order.timestamp = 0; // older than the current timestamp
    let result = sync.remote_op(out_of_order, &mut engine);
    assert!(matches!(result, Err(SyncError::InvalidOperation)));

    // State should remain unchanged.
    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "First");
}

#[test]
fn test_version_vector_advances_on_successful_remote_op() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    let edit = EditKind::Insert {
        pos: 0,
        text: "Version".to_string(),
    };
    let op = sync.local_op(edit);
    let author = op.author;
    let timestamp = op.timestamp;

    sync.remote_op(op, &mut engine).expect("remote_op succeeds");
    let recorded = sync.version_vector().get(author);
    assert_eq!(recorded, timestamp);
}

#[test]
fn test_invalid_range_is_ignored_and_does_not_corrupt_state() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    // Insert some baseline text.
    let base = EditKind::Insert {
        pos: 0,
        text: "Baseline".to_string(),
    };
    let base_op = sync.local_op(base);
    sync.remote_op(base_op, &mut engine).expect("baseline insert succeeds");

    // Attempt to delete with an out‑of‑bounds range.
    let bad_range = Range { start: 5, end: 50 };
    let bad_delete = EditKind::Delete { range: bad_range };
    let bad_op = sync.local_op(bad_delete);
    let result = sync.remote_op(bad_op, &mut engine);
    assert!(matches!(result, Err(SyncError::InvalidOperation)));

    // Markdown should remain unchanged.
    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "Baseline");
}

#[test]
fn test_transient_error_is_retried_up_to_three_times() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    // Create an operation that the sync engine will treat as transient.
    // For the purpose of the test we simulate this by manually injecting a
    // transient error after the first two attempts.
    let edit = EditKind::Insert {
        pos: 0,
        text: "Retry".to_string(),
    };
    let op = sync.local_op(edit);

    // Override the internal retry counter to force three attempts.
    sync.set_retry_limit(3);
    sync.inject_transient_failure(true);

    let result = sync.remote_op(op, &mut engine);
    // After three retries the engine should surface a non‑fatal warning,
    // which we model as a SyncError::TransientError.
    assert!(matches!(result, Err(SyncError::TransientError(_))));

    // The document should remain unchanged because the operation never succeeded.
    let markdown = engine.render_markdown();
    assert!(markdown.is_none());
}