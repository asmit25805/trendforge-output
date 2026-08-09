use std::ops::Range;

use crate::core::engine::RopePieceTableEngine;
use crate::collab::crdt::{
    CRDTSyncEngine, DeletePayload, EditError, EditKind, InsertPayload, OperationKind,
    OperationPayload, SyncError, VersionVector,
};

#[test]
fn test_engine_insert_single_piece() {
    let mut engine = RopePieceTableEngine::new();
    engine
        .insert(0, "Hello")
        .expect("insert should succeed");
    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "Hello");
}

#[test]
fn test_engine_insert_and_delete_sequence() {
    let mut engine = RopePieceTableEngine::new();
    engine
        .insert(0, "Rust")
        .expect("first insert should succeed");
    engine
        .insert(4, "acean")
        .expect("second insert should succeed");
    let range = Range { start: 4, end: 9 };
    engine
        .delete(range.clone())
        .expect("delete should succeed");
    let markdown = engine
        .render_markdown()
        .expect("engine should produce markdown");
    assert_eq!(markdown, "Rust");
}

#[test]
fn test_engine_delete_out_of_range_returns_error() {
    let mut engine = RopePieceTableEngine::new();
    engine
        .insert(0, "short")
        .expect("insert should succeed");
    let out_of_range = Range { start: 2, end: 10 };
    let err = engine.delete(out_of_range).unwrap_err();
    assert!(matches!(err, EditError::InvalidRange));
}

#[test]
fn test_crdt_local_op_generates_unique_id() {
    let mut sync = CRDTSyncEngine::new();
    let edit = EditKind::Insert {
        pos: 0,
        text: "data".to_string(),
    };
    let op1 = sync.local_op(edit);
    let edit2 = EditKind::Insert {
        pos: 4,
        text: "more".to_string(),
    };
    let op2 = sync.local_op(edit2);
    assert_ne!(op1.op_id, op2.op_id, "operation IDs must be unique");
    assert!(op2.timestamp > op1.timestamp, "Lamport timestamps must increase");
}

#[test]
fn test_crdt_remote_op_causality_enforced() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    // Apply a valid insert.
    let insert = EditKind::Insert {
        pos: 0,
        text: "First".to_string(),
    };
    let op = sync.local_op(insert);
    sync.remote_op(op.clone(), &mut engine)
        .expect("first remote_op should succeed");

    // Create an out‑of‑order operation with an older timestamp.
    let mut out_of_order = op.clone();
    out_of_order.timestamp = 0; // older than current timestamp
    let result = sync.remote_op(out_of_order, &mut engine);
    assert!(matches!(result, Err(SyncError::InvalidOperation)));
}

#[test]
fn test_version_vector_updates_after_successful_remote_op() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    let edit = EditKind::Insert {
        pos: 0,
        text: "Version".to_string(),
    };
    let op = sync.local_op(edit);
    let author = op.author;
    let timestamp = op.timestamp;

    sync.remote_op(op, &mut engine)
        .expect("remote_op should succeed");
    let recorded = sync.version_vector().get(author);
    assert_eq!(recorded, timestamp);
}

#[test]
fn test_crdt_duplicate_operation_is_rejected() {
    let mut engine = RopePieceTableEngine::new();
    let mut sync = CRDTSyncEngine::new();

    let edit = EditKind::Insert {
        pos: 0,
        text: "Dup".to_string(),
    };
    let op = sync.local_op(edit);
    sync.remote_op(op.clone(), &mut engine)
        .expect("first remote_op should succeed");
    let duplicate_result = sync.remote_op(op, &mut engine);
    assert!(matches!(duplicate_result, Err(SyncError::InvalidOperation)));
}