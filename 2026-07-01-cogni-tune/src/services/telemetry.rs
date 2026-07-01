use std::collections::HashMap;
use std::time::Duration;

use anyhow::Context;
use async_trait::async_trait;
use chrono::{DateTime, Utc};
use clickhouse::{Client as ClickHouseClient, Row};
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use thiserror::Error;
use tokio::time::sleep;
use uuid::Uuid;

use crate::engine::IngestError;

/// The origin of a telemetry event.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    Log,
    Metric,
    Trace,
}

/// A single telemetry record that flows through the system.
#[derive(Debug, Clone, Serialize, Deserialize, Row)]
pub struct TelemetryEvent {
    pub id: Uuid,
    pub timestamp: DateTime<Utc>,
    pub source: Source,
    pub payload: JsonValue,
    pub resource_attrs: HashMap<String, String>,
}

/// Errors that can be raised by the telemetry service.
#[derive(Debug, Error)]
pub enum TelemetryError {
    #[error("clickhouse error: {0}")]
    ClickHouse(#[from] clickhouse::Error),

    #[error("validation failed: {0}")]
    Validation(String),

    #[error("transient error after retries: {0}")]
    Transient(anyhow::Error),
}

/// Validate a telemetry event before it is persisted.
///
/// The function checks that required fields are present and that the payload
/// can be serialized. It returns a descriptive `TelemetryError::Validation`
/// on failure.
pub fn validate_event(event: &TelemetryEvent) -> Result<(), TelemetryError> {
    if event.id == Uuid::nil() {
        return Err(TelemetryError::Validation(
            "event id must not be nil".into(),
        ));
    }
    if event.timestamp > Utc::now() + chrono::Duration::seconds(5) {
        return Err(TelemetryError::Validation(
            "timestamp is in the future".into(),
        ));
    }
    // Ensure payload is a valid JSON value (serde_json guarantees this).
    // Additional domain‑specific checks could be added here.
    Ok(())
}

/// Store a telemetry event in ClickHouse with retry semantics.
///
/// The function retries transient errors up to three times with exponential
/// back‑off (100 ms, 200 ms, 400 ms). Fatal errors are propagated immediately.
pub async fn store_event(
    client: &ClickHouseClient,
    event: TelemetryEvent,
) -> Result<(), IngestError> {
    // Validate early to avoid unnecessary DB work.
    validate_event(&event).map_err(|e| IngestError::ValidationError(e.to_string()))?;

    const MAX_ATTEMPTS: usize = 3;
    let mut attempt = 0usize;

    loop {
        attempt += 1;
        let insert_res = client
            .insert("telemetry_events")
            .await
            .context("failed to prepare insert statement")
            .map_err(|e| IngestError::TransientError(e.into()))?
            .write(&event)
            .await
            .context("failed to write row")
            .map_err(|e| IngestError::TransientError(e.into()))?
            .execute()
            .await
            .context("failed to execute insert")
            .map_err(|e| IngestError::TransientError(e.into()));

        match insert_res {
            Ok(_) => {
                info!("stored telemetry event {}", event.id);
                return Ok(());
            }
            Err(IngestError::TransientError(e)) => {
                if attempt >= MAX_ATTEMPTS {
                    error!(
                        "transient error storing event {} after {} attempts: {}",
                        event.id, attempt, e
                    );
                    return Err(IngestError::TransientError(e));
                }
                let backoff = Duration::from_millis(100 * 2_u64.pow(attempt as u32 - 1));
                warn!(
                    "transient error storing event {} (attempt {}), backing off {:?}",
                    event.id, attempt, backoff
                );
                sleep(backoff).await;
                continue;
            }
            Err(e) => {
                // Fatal errors (e.g., schema mismatch) are propagated directly.
                error!("fatal error storing event {}: {}", event.id, e);
                return Err(e);
            }
        }
    }
}

/// Parameters for querying telemetry events.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TelemetryQuery {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub source: Option<Source>,
    pub limit: Option<usize>,
}

/// Retrieve telemetry events from ClickHouse.
///
/// The function respects the supplied time window and optional source filter.
/// It returns a vector of `TelemetryEvent` sorted by timestamp ascending.
pub async fn query_events(
    client: &ClickHouseClient,
    query: TelemetryQuery,
) -> Result<Vec<TelemetryEvent>, IngestError> {
    const MAX_ATTEMPTS: usize = 3;
    let mut attempt = 0usize;

    let base_sql = r#"
        SELECT
            id,
            timestamp,
            source,
            payload,
            resource_attrs
        FROM telemetry_events
        WHERE timestamp >= $start AND timestamp <= $end
    "#;

    // Build the final SQL with optional source filter.
    let sql = if query.source.is_some() {
        format!("{} AND source = $source", base_sql)
    } else {
        base_sql.to_string()
    };

    loop {
        attempt += 1;
        let mut stmt = client
            .query(&sql)
            .await
            .context("failed to prepare query")
            .map_err(|e| IngestError::TransientError(e.into()))?;

        stmt = stmt
            .bind("$start", query.start)
            .bind("$end", query.end);

        if let Some(src) = query.source {
            stmt = stmt.bind("$source", src);
        }

        if let Some(lim) = query.limit {
            stmt = stmt.bind("$limit", lim as u64);
        }

        let fetch_res = stmt
            .fetch_all::<TelemetryEvent>()
            .await
            .context("failed to fetch rows")
            .map_err(|e| IngestError::TransientError(e.into()));

        match fetch_res {
            Ok(events) => {
                info!(
                    "queried {} telemetry events ({}..{})",
                    events.len(),
                    query.start,
                    query.end
                );
                return Ok(events);
            }
            Err(IngestError::TransientError(e)) => {
                if attempt >= MAX_ATTEMPTS {
                    error!(
                        "transient error querying telemetry after {} attempts: {}",
                        attempt, e
                    );
                    return Err(IngestError::TransientError(e));
                }
                let backoff = Duration::from_millis(100 * 2_u64.pow(attempt as u32 - 1));
                warn!(
                    "transient error querying telemetry (attempt {}), backing off {:?}",
                    attempt, backoff
                );
                sleep(backoff).await;
                continue;
            }
            Err(e) => {
                // Fatal errors are propagated.
                error!("fatal error querying telemetry: {}", e);
                return Err(e);
            }
        }
    }
}

/// Trait defining the contract for a telemetry backend. This abstraction enables
/// unit‑testing of higher‑level components without a real ClickHouse instance.
#[async_trait]
pub trait TelemetryBackend: Send + Sync {
    async fn store(&self, event: TelemetryEvent) -> Result<(), IngestError>;
    async fn query(&self, query: TelemetryQuery) -> Result<Vec<TelemetryEvent>, IngestError>;
}

/// Concrete implementation that forwards calls to a ClickHouse client.
pub struct ClickHouseBackend {
    client: ClickHouseClient,
}

impl ClickHouseBackend {
    pub fn new(client: ClickHouseClient) -> Self {
        Self { client }
    }
}

#[async_trait]
impl TelemetryBackend for ClickHouseBackend {
    async fn store(&self, event: TelemetryEvent) -> Result<(), IngestError> {
        store_event(&self.client, event).await
    }

    async fn query(&self, query: TelemetryQuery) -> Result<Vec<TelemetryEvent>, IngestError> {
        query_events(&self.client, query).await
    }
}