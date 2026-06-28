use std::fs;
use std::path::PathBuf;

use tempfile::TempDir;

use gitmind::store::{
    ArtifactId, Document, DocumentChange, KnowledgeStore, Link, StoreError,
};

/// Helper to create a simple `Document` instance.
fn make_document(path: &str, content: &str) -> Document {
    Document {
        id: String::new(),
        path: PathBuf::from(path),
        content: content.to_string(),
        metadata: Default::default(),
    }
}

/// Initialise a fresh `KnowledgeStore` backed by a temporary git repository.
fn init_store() -> (KnowledgeStore, TempDir) {
    let tmp = TempDir::new().expect("failed to create temp dir");
    let repo_path = tmp.path().to_path_buf();

    // `KnowledgeStore::new` is expected to initialise a git repository at the
    // given path and return a ready‑to‑use store.
    let store = KnowledgeStore::new(repo_path.clone())
        .expect("failed to initialise KnowledgeStore");
    (store, tmp)
}

#[test]
fn test_store_write_and_read_document() {
    let (store, _tmp) = init_store();

    let doc = make_document("notes/first.md", "# Title\n\nContent");
    let change = DocumentChange::new(doc.clone());

    let commit_hash = store
        .write_doc(&doc)
        .expect("write_doc should succeed");
    assert!(!commit_hash.is_empty(), "commit hash must be non‑empty");

    let read_back = store
        .read_doc(&doc.path)
        .expect("read_doc should succeed");
    assert_eq!(read_back.content, doc.content, "content round‑trip");
    assert_eq!(read_back.path, doc.path, "path round‑trip");
    assert_eq!(read_back.id, doc.id, "id round‑trip");
}

#[test]
fn test_store_commit_hash_changes_on_update() {
    let (store, _tmp) = init_store();

    let mut doc = make_document("notes/update.md", "Version 1");
    store
        .write_doc(&doc)
        .expect("first write_doc should succeed");
    let first_hash = store
        .read_doc(&doc.path)
        .expect("first read_doc")
        .metadata
        .commit_hash
        .clone();

    // Modify the document and write again.
    doc.content = "Version 2".to_string();
    store
        .write_doc(&doc)
        .expect("second write_doc should succeed");
    let second_hash = store
        .read_doc(&doc.path)
        .expect("second read_doc")
        .metadata
        .commit_hash
        .clone();

    assert_ne!(
        first_hash, second_hash,
        "commit hash must change after document update"
    );
}

#[test]
fn test_store_backlink_detection() {
    let (store, _tmp) = init_store();

    // Source document contains a markdown link to the target.
    let target = make_document("notes/target.md", "# Target");
    store
        .write_doc(&target)
        .expect("write target document");

    let source_content = format!(
        "# Source\n\nLink to target: [{}]({})",
        "target", "target.md"
    );
    let source = make_document("notes/source.md", &source_content);
    store
        .write_doc(&source)
        .expect("write source document");

    // The backlink list for the target should contain the source.
    let backlinks = store
        .list_backlinks(&target.id)
        .expect("list_backlinks should succeed");
    let contains_source = backlinks.iter().any(|link| link.source_id == source.id);
    assert!(
        contains_source,
        "backlinks for target must include source document"
    );
}

#[test]
fn test_store_backlink_cache_invalidation_on_edit() {
    let (store, _tmp) = init_store();

    let target = make_document("notes/target2.md", "# Target2");
    store
        .write_doc(&target)
        .expect("write target2");

    let source_content = "[link](target2.md)";
    let mut source = make_document("notes/source2.md", source_content);
    store
        .write_doc(&source)
        .expect("write source2 with link");

    // Verify backlink exists.
    let initial_backlinks = store
        .list_backlinks(&target.id)
        .expect("initial list_backlinks");
    assert!(
        initial_backlinks.iter().any(|l| l.source_id == source.id),
        "initial backlink should be present"
    );

    // Remove the link and rewrite the source.
    source.content = "# No link now".to_string();
    store
        .write_doc(&source)
        .expect("rewrite source2 without link");

    // Backlink list must be updated (source should disappear).
    let updated_backlinks = store
        .list_backlinks(&target.id)
        .expect("updated list_backlinks");
    assert!(
        !updated_backlinks.iter().any(|l| l.source_id == source.id),
        "backlink should be removed after source edit"
    );
}

#[test]
fn test_store_validation_error_on_malformed_markdown() {
    let (store, _tmp) = init_store();

    // Empty content is considered malformed for this test scenario.
    let doc = make_document("notes/bad.md", "");
    let result = store.write_doc(&doc);
    match result {
        Err(StoreError::Validation(_)) => {}
        _ => panic!("expected validation error for empty markdown"),
    }
}

#[test]
fn test_store_fatal_error_on_repository_corruption() {
    let (store, tmp) = init_store();

    // Corrupt the repository by deleting the .git directory.
    let git_dir = tmp.path().join(".git");
    fs::remove_dir_all(&git_dir).expect("failed to delete .git directory");

    let doc = make_document("notes/corrupt.md", "Content after corruption");
    let result = store.write_doc(&doc);
    match result {
        Err(StoreError::Fatal(_)) => {}
        _ => panic!("expected fatal error after repository corruption"),
    }
}