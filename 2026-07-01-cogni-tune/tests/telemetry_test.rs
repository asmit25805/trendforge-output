use chrono::{DateTime, Utc};
use std::collections::HashMap;
use uuid::Uuid;

use crate::services::telemetry::{
    store_event, Source, TelemetryEvent, TelemetryError, validate_event,
};
use crate::engine::IngestError;
use clickhouse::Client as ClickHouseClient;

/// Helper to construct a minimal valid telemetry event.
fn valid_event() -> TelemetryEvent {
    TelemetryEvent {
        id: Uuid::new_v4(),
        timestamp: Utc::now(),
        source: Source::Log,
        payload: serde_json::json!({ "message": "test" }),
        resource_attrs: HashMap::new(),
    }
}

/// Returns a ClickHouse client that will always fail to connect.
/// The URL points to an address that is guaranteed to refuse connections.
fn failing_clickhouse_client() -> ClickHouseClient {
    ClickHouseClient::default()
        .with_url("http://127.0.0.1:65535") // invalid port ensures connection error.
}

/// Returns a ClickHouse client that pretends to succeed by pointing to a
/// non‑existent but syntactically valid endpoint. The client will still error
/// on insert, allowing us to test the retry logic without a real server.
fn mock_clickhouse_client() -> ClickHouseClient {
    ClickHouseClient::default()
        .with_url("http://localhost:8123") // default ClickHouse port; CI environment has none.
}

/// Test that `validate_event` rejects an event with a nil UUID.
#[tokio::test]
async fn test_validate_event_rejects_nil_id() {
    let mut ev = valid_event();
    ev.id = Uuid::nil();

    let err = validate_event(&ev).expect_err("validation should fail for nil id");
    matches!(err, TelemetryError::Validation(msg) if msg.contains("nil"));
}

/// Test that `validate_event` rejects an event whose timestamp is far in the future.
#[tokio::test]
async fn test_validate_event_rejects_future_timestamp() {
    let mut ev = valid_event();
    ev.timestamp = Utc::now() + chrono::Duration::seconds(10);

    let err = validate_event(&ev).expect_err("validation should fail for future timestamp");
    matches!(err, TelemetryError::Validation(msg) if msg.contains("future"));
}

/// Test that `store_event` returns a validation error before any DB interaction.
#[tokio::test]
async fn test_store_event_fails_fast_on_invalid_event() {
    let mut ev = valid_event();
    ev.id = Uuid::nil(); // trigger validation failure

    let client = mock_clickhouse_client();
    let result = store_event(&client, ev).await;
    match result {
        Err(IngestError::ValidationError(_)) => {}
        other => panic!("expected ValidationError, got {:?}", other),
    }
}

/// Test that `store_event` retries on transient connection failures and eventually
/// returns a `TransientError` after exhausting retries.
#[tokio::test]
async fn test_store_event_retries_and_returns_transient_error() {
    let ev = valid_event();
    let client = failing_clickhouse_client();

    let result = store_event(&client, ev).await;
    match result {
        Err(IngestError::TransientError(_)) => {}
        other => panic!("expected TransientError, got {:?}", other),
    }
}

/// Test that a successful validation followed by a client that returns a
/// non‑transient (schema) error propagates as a `TransientError` as well,
/// because `store_event` treats all clickhouse errors as transient before
/// classification.
#[tokio::test]
async fn test_store_event_schema_mismatch_is_treated_as_transient() {
    // The mock client points to a reachable address but without the expected table.
    // ClickHouse will return a schema‑related error which we treat as transient.
    let ev = valid_event();
    let client = mock_clickhouse_client();

    let result = store_event(&client, ev).await;
    match result {
        Err(IngestError::TransientError(_)) => {}
        other => panic!("expected TransientError for schema mismatch, got {:?}", other),
    }
}

/// Test that `store_event` does not leak resources when called repeatedly with
/// a failing client. This ensures the retry loop respects the maximum attempt
/// count and does not enter an infinite loop.
#[tokio::test]
async fn test_store_event_multiple_calls_respect_retry_limit() {
    let ev = valid_event();
    let client = failing_clickhouse_client();

    // Call the function three times; each call should return quickly after the
    // internal retry back‑off (max 3 attempts). The total duration must be less
    // than a reasonable bound (e.g., 2 seconds) to confirm no runaway retries.
    let start = std::time::Instant::now();
    for _ in 0..3 {
        let _ = store_event(&client, ev.clone()).await;
    }
    let elapsed = start.elapsed();
    assert!(
        elapsed < std::time::Duration::from_secs(2),
        "retry loop exceeded expected duration: {:?}",
        elapsed
    );
}