use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tempfile::TempDir;
use tokio::sync::mpsc::{unbounded_channel, UnboundedReceiver};

use gitmind::engine::{Engine, EngineConfig, EngineError, ApplyResult};
use gitmind::store::{Document, DocumentMeta, DocumentChange};
use gitmind::collab::{CollaborationSession, ClientHandle, ClientId, CrdtOp};

/// Helper to create a minimal `Document` instance.
fn make_document(path: &str, content: &str) -> Document {
    Document {
        id: String::new(),
        path: PathBuf::from(path),
        content: content.to_string(),
        metadata: DocumentMeta::default(),
    }
}

/// Initialise an `Engine` backed by a fresh temporary git repository.
async fn init_engine() -> (Engine, TempDir) {
    let temp_dir = TempDir::new().expect("failed to create temp dir");
    let repo_path = temp_dir.path().to_path_buf();

    // EngineConfig is assumed to contain at least the repository root.
    let config = EngineConfig {
        repo_path: repo_path.clone(),
        // other fields get default values
        ..Default::default()
    };

    let engine = Engine::initialize(config)
        .await
        .expect("engine initialisation failed");
    (engine, temp_dir)
}

/// Count words in a markdown string – used to verify token usage.
fn word_count(text: &str) -> u64 {
    text.split_whitespace().count() as u64
}

#[tokio::test]
async fn test_engine_apply_change_success() {
    let (engine, _tmp) = init_engine().await;

    let doc = make_document("notes/hello.md", "# Hello\n\nThis is a test document.");
    let change = DocumentChange::new(doc.clone());

    let result: Result<ApplyResult, EngineError> = engine.apply_change(change).await;
    assert!(result.is_ok(), "apply_change should succeed");

    let apply_result = result.unwrap();
    assert_eq!(
        apply_result.token_usage,
        word_count(&doc.content),
        "token usage must equal word count"
    );
}

#[tokio::test]
async fn test_engine_validation_error_on_malformed_markdown() {
    let (engine, _tmp) = init_engine().await;

    // Empty content is considered malformed for this test scenario.
    let doc = make_document("notes/bad.md", "");
    let change = DocumentChange::new(doc);

    let result: Result<ApplyResult, EngineError> = engine.apply_change(change).await;
    match result {
        Err(EngineError::Validation(_)) => {}
        _ => panic!("expected validation error"),
    }
}

#[tokio::test]
async fn test_engine_fatal_error_on_repo_corruption() {
    let (engine, tmp) = init_engine().await;

    // Corrupt the repository by removing the .git directory.
    let git_dir = tmp.path().join(".git");
    std::fs::remove_dir_all(&git_dir).expect("failed to delete .git");

    let doc = make_document("notes/corrupt.md", "Content after corruption");
    let change = DocumentChange::new(doc);

    let result: Result<ApplyResult, EngineError> = engine.apply_change(change).await;
    match result {
        Err(EngineError::Fatal(_)) => {}
        _ => panic!("expected fatal error due to repository corruption"),
    }
}

#[tokio::test]
async fn test_engine_retries_on_transient_error() {
    let (engine, tmp) = init_engine().await;

    // Simulate a transient error by making the repository read‑only.
    let repo_path = tmp.path();
    let mut perms = std::fs::metadata(repo_path).unwrap().permissions();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        perms.set_mode(0o500); // read & execute only
    }
    std::fs::set_permissions(repo_path, perms).expect("failed to set read‑only");

    // Spawn a task that will restore write permission after a short delay.
    let restore_path = repo_path.to_path_buf();
    tokio::spawn(async move {
        tokio::time::sleep(Duration::from_millis(200)).await;
        let mut perms = std::fs::metadata(&restore_path).unwrap().permissions();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            perms.set_mode(0o700); // read, write, execute
        }
        std::fs::set_permissions(&restore_path, perms).expect("failed to restore permissions");
    });

    let doc = make_document("notes/retry.md", "Transient error test content");
    let change = DocumentChange::new(doc.clone());

    // The engine is expected to retry internally and eventually succeed.
    let result: Result<ApplyResult, EngineError> = engine.apply_change(change).await;
    assert!(result.is_ok(), "apply_change should succeed after retry");
    let apply_result = result.unwrap();
    assert_eq!(
        apply_result.token_usage,
        word_count(&doc.content),
        "token usage must match after retry"
    );
}

#[tokio::test]
async fn test_engine_updates_collaboration_session() {
    let (engine, _tmp) = init_engine().await;

    // Create a collaboration session and a client that will receive CRDT ops.
    let collab = CollaborationSession::new().expect("failed to create collab session");
    let (tx, mut rx): (tokio::sync::mpsc::UnboundedSender<CrdtOp>, UnboundedReceiver<CrdtOp>) =
        unbounded_channel();

    let client_handle = ClientHandle {
        id: ClientId(uuid::Uuid::new_v4()),
        sender: tx,
    };

    // Join the client to a document.
    let doc_id = "notes/notify.md".to_string();
    collab
        .join(&doc_id, client_handle.clone())
        .await
        .expect("client join failed");

    // Apply a change that should trigger a broadcast.
    let doc = make_document(&doc_id, "Initial content");
    let change = DocumentChange::new(doc);
    engine.apply_change(change).await.expect("apply_change failed");

    // The client should receive at least one CRDT operation.
    let received = tokio::time::timeout(Duration::from_secs(1), rx.recv())
        .await
        .expect("no CRDT op received within timeout")
        .expect("channel closed unexpectedly");

    assert_eq!(received.doc_id, doc_id, "CRDT op must target the changed document");
}

#[tokio::test]
async fn test_engine_shutdown_clean() {
    let (engine, _tmp) = init_engine().await;

    // Perform a simple operation before shutdown to ensure the engine is active.
    let doc = make_document("notes/close.md", "Shutdown test");
    let change = DocumentChange::new(doc);
    engine.apply_change(change).await.expect("apply_change failed");

    // Shutdown must complete without error.
    engine.shutdown().await.expect("engine shutdown failed");
}