use std::fs;
use std::path::PathBuf;

use chrono::Utc;
use uuid::Uuid;

use crate::recorder::{RecorderConfig, RecorderError, SessionRecorder};
use crate::models::SessionBundle;

/// Helper to construct a temporary session directory and ensure cleanup.
fn temp_session_dir() -> PathBuf {
    let mut dir = std::env::temp_dir();
    dir.push(format!("tracecraft_test_{}", Uuid::new_v4()));
    fs::create_dir_all(&dir).expect("failed to create temp session dir");
    dir
}

/// Clean up the temporary directory created by `temp_session_dir`.
fn cleanup_dir(dir: PathBuf) {
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn test_start_successful() {
    let session_dir = temp_session_dir();
    let mut recorder = SessionRecorder::default();

    let mut config = RecorderConfig::default();
    config.session_dir = Some(session_dir.clone());

    let result = recorder.start(config);
    assert!(result.is_ok(), "Recorder start should succeed");

    // Clean up
    let _ = recorder.stop();
    cleanup_dir(session_dir);
}

#[test]
fn test_stop_returns_bundle() {
    let session_dir = temp_session_dir();
    let mut recorder = SessionRecorder::default();

    let mut config = RecorderConfig::default();
    config.session_dir = Some(session_dir.clone());

    recorder.start(config).expect("start failed");
    let bundle = recorder.stop().expect("stop failed");

    // The bundle should contain a valid UUID and a start timestamp.
    assert!(Uuid::parse_str(&bundle.id.to_string()).is_ok(), "Bundle ID is not a valid UUID");
    assert!(bundle.started_at <= Utc::now(), "Bundle start time is in the future");
    // No collectors were added, so events should be empty.
    assert!(bundle.events.is_empty(), "Expected no events in the bundle");
    cleanup_dir(session_dir);
}

#[test]
fn test_bundle_written_to_file() {
    let session_dir = temp_session_dir();
    let mut recorder = SessionRecorder::default();

    let mut config = RecorderConfig::default();
    config.session_dir = Some(session_dir.clone());

    recorder.start(config).expect("start failed");
    let bundle = recorder.stop().expect("stop failed");

    let mut expected_path = session_dir;
    expected_path.push(format!("{}.json", bundle.id));
    assert!(expected_path.is_file(), "Session bundle file was not created");

    // Verify that the file can be read and parsed back into a SessionBundle.
    let data = fs::read_to_string(&expected_path).expect("failed to read bundle file");
    let parsed: SessionBundle =
        serde_json::from_str(&data).expect("failed to deserialize SessionBundle");
    assert_eq!(parsed.id, bundle.id, "Deserialized bundle ID mismatch");
    assert_eq!(parsed.events.len(), bundle.events.len(), "Deserialized events count mismatch");
}

#[test]
fn test_stop_without_start_fails() {
    let mut recorder = SessionRecorder::default();
    let result = recorder.stop();
    match result {
        Err(RecorderError::NotStarted) => {} // Expected error variant
        _ => panic!("Expected RecorderError::NotStarted when stopping without start"),
    }
}

#[test]
fn test_start_fails_with_invalid_config() {
    let mut recorder = SessionRecorder::default();

    // Create a config that points to a non‑writable directory.
    let mut config = RecorderConfig::default();
    config.session_dir = Some(PathBuf::from("/root/invalid_path"));

    let result = recorder.start(config);
    match result {
        Err(RecorderError::Io(_)) => {} // Expected I/O error
        _ => panic!("Expected I/O error when starting with invalid session directory"),
    }
}

#[test]
fn test_multiple_start_calls_error() {
    let session_dir = temp_session_dir();
    let mut recorder = SessionRecorder::default();

    let mut config = RecorderConfig::default();
    config.session_dir = Some(session_dir.clone());

    recorder.start(config.clone()).expect("first start failed");
    let second = recorder.start(config);
    match second {
        Err(RecorderError::AlreadyRunning) => {} // Expected error variant
        _ => panic!("Expected RecorderError::AlreadyRunning on second start"),
    }

    // Clean up
    let _ = recorder.stop();
    cleanup_dir(session_dir);
}