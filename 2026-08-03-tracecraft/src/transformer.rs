use std::sync::Arc;
use std::time::{Duration, Instant};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use reqwest::header::{HeaderMap, HeaderValue, AUTHORIZATION, CONTENT_TYPE};
use reqwest::Client;
use rusqlite::{params, Connection, NO_PARAMS};
use serde::{Deserialize, Serialize};
use serde_json::json;
use thiserror::Error;
use tokio::time::sleep;

use crate::models::{PipelineSpec, SessionBundle};

/// Configuration for retrying transient failures.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RetryPolicy {
    /// Maximum number of attempts (initial try + retries).
    pub max_attempts: u32,
    /// Base delay used for exponential back‑off.
    pub base_delay_ms: u64,
    /// Upper bound for the back‑off delay.
    pub max_delay_ms: u64,
}

impl RetryPolicy {
    /// Compute the back‑off delay for a given attempt (1‑based).
    pub fn backoff(&self, attempt: u32) -> Duration {
        let exp = 2_u64.pow(attempt.saturating_sub(1));
        let delay = self.base_delay_ms.saturating_mul(exp);
        Duration::from_millis(delay.min(self.max_delay_ms))
    }
}

/// Errors that can be produced by the LLM transformer.
#[derive(Error, Debug)]
pub enum LLMError {
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),
    #[error("Unexpected status code: {0}")]
    Status(u16),
    #[error("JSON serialization/deserialization error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Retry policy exhausted")]
    RetryExceeded,
    #[error("Configuration error: {0}")]
    Config(String),
    #[error("Database error: {0}")]
    Db(#[from] rusqlite::Error),
}

/// Persistent record of a single transformation task.
#[derive(Debug, Serialize, Deserialize)]
struct TaskRecord {
    /// SHA‑256 hash of the serialized `SessionBundle`.
    bundle_hash: String,
    /// Serialized `PipelineSpec` produced by the LLM.
    spec_json: String,
    /// When the task was started.
    started_at: DateTime<Utc>,
    /// When the task completed.
    finished_at: DateTime<Utc>,
    /// Result of the task (`Ok` or error description).
    result: String,
}

/// Core component that talks to an LLM endpoint and produces a `PipelineSpec`.
pub struct LLMTransformer {
    endpoint: String,
    api_key: String,
    client: Client,
    retry_policy: RetryPolicy,
    db: Arc<Connection>,
}

impl LLMTransformer {
    /// Create a new transformer.
    ///
    /// * `endpoint` – URL of the LLM service (e.g. https://api.openai.com/v1/chat/completions).
    /// * `api_key` – Bearer token for authentication.
    /// * `retry_policy` – Policy governing transient‑error retries.
    /// * `db_path` – Path to the SQLite file storing run history.
    pub fn new(
        endpoint: impl Into<String>,
        api_key: impl Into<String>,
        retry_policy: RetryPolicy,
        db_path: impl AsRef<std::path::Path>,
    ) -> Result<Self, LLMError> {
        let client = Client::builder()
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(LLMError::Http)?;

        let conn = Connection::open(db_path).map_err(LLMError::Db)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bundle_hash TEXT NOT NULL UNIQUE,
                spec_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                result TEXT NOT NULL
            );",
        )
        .map_err(LLMError::Db)?;

        Ok(Self {
            endpoint: endpoint.into(),
            api_key: api_key.into(),
            client,
            retry_policy,
            db: Arc::new(conn),
        })
    }

    /// Return a reference to the configured retry policy.
    pub fn retry_policy(&self) -> &RetryPolicy {
        &self.retry_policy
    }

    /// Transform a recorded session into a pipeline specification.
    ///
    /// The function first checks the SQLite cache for a previous run with the same
    /// bundle hash. If a cached entry exists, it is returned directly. Otherwise the
    /// request is sent to the LLM endpoint, respecting the retry policy for transient
    /// failures. The successful result is persisted for future reuse.
    pub async fn transform(
        &self,
        bundle: &SessionBundle,
        feedback: Option<String>,
    ) -> Result<PipelineSpec, LLMError> {
        let start_time = Utc::now();
        let bundle_json = serde_json::to_string(bundle)?;
        let bundle_hash = self.hash_bytes(bundle_json.as_bytes());

        // Check cache first.
        if let Some(spec) = self.lookup_cached_spec(&bundle_hash)? {
            info!("Cache hit for bundle {}", bundle_hash);
            return Ok(spec);
        }

        // Prepare request payload.
        let mut payload = json!({ "bundle": bundle });
        if let Some(fb) = feedback {
            payload["feedback"] = json!(fb);
        }

        // Build headers.
        let mut headers = HeaderMap::new();
        headers.insert(
            AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {}", self.api_key))
                .map_err(|e| LLMError::Config(e.to_string()))?,
        );
        headers.insert(CONTENT_TYPE, HeaderValue::from_static("application/json"));

        // Retry loop.
        let mut attempt = 0;
        loop {
            attempt += 1;
            let attempt_start = Instant::now();
            info!(
                "LLM request attempt {} for bundle {} (payload size {} bytes)",
                attempt,
                bundle_hash,
                payload.to_string().len()
            );

            let resp = self
                .client
                .post(&self.endpoint)
                .headers(headers.clone())
                .json(&payload)
                .send()
                .await;

            match resp {
                Ok(r) => {
                    let status = r.status();
                    if !status.is_success() {
                        if self.is_transient_status(status.as_u16()) && attempt < self.retry_policy.max_attempts {
                            warn!(
                                "Transient HTTP {} on attempt {} – backing off",
                                status, attempt
                            );
                            self.backoff_sleep(attempt).await;
                            continue;
                        }
                        error!("Non‑retriable HTTP {} on attempt {}", status, attempt);
                        return Err(LLMError::Status(status.as_u16()));
                    }

                    let text = r.text().await?;
                    let spec: PipelineSpec = serde_json::from_str(&text)?;
                    let finished_at = Utc::now();

                    // Persist result.
                    self.persist_run(
                        &bundle_hash,
                        &spec,
                        start_time,
                        finished_at,
                        "Ok".to_string(),
                    )?;

                    info!(
                        "LLM transformation succeeded after {} attempts (elapsed {:.2?})",
                        attempt,
                        attempt_start.elapsed()
                    );
                    return Ok(spec);
                }
                Err(e) => {
                    if self.is_transient_error(&e) && attempt < self.retry_policy.max_attempts {
                        warn!("Transient error on attempt {}: {} – backing off", attempt, e);
                        self.backoff_sleep(attempt).await;
                        continue;
                    }
                    error!("Fatal error on attempt {}: {}", attempt, e);
                    return Err(LLMError::Http(e));
                }
            }
        }
    }

    /// Determine whether an HTTP status code is considered transient.
    fn is_transient_status(&self, code: u16) -> bool {
        matches!(code, 429 | 500..=599)
    }

    /// Determine whether a `reqwest::Error` is transient (e.g., timeout or connection reset).
    fn is_transient_error(&self, err: &reqwest::Error) -> bool {
        err.is_timeout()
            || err.is_connect()
            || err
                .source()
                .map(|s| s.to_string().contains("reset"))
                .unwrap_or(false)
    }

    /// Sleep according to the retry policy's back‑off for the given attempt.
    async fn backoff_sleep(&self, attempt: u32) {
        let delay = self.retry_policy.backoff(attempt);
        info!("Sleeping for {:?} before next attempt", delay);
        sleep(delay).await;
    }

    /// Compute a hex‑encoded SHA‑256 hash of a byte slice.
    fn hash_bytes(&self, data: &[u8]) -> String {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(data);
        format!("{:x}", hasher.finalize())
    }

    /// Look up a cached `PipelineSpec` by bundle hash.
    fn lookup_cached_spec(&self, hash: &str) -> Result<Option<PipelineSpec>, LLMError> {
        let mut stmt = self
            .db
            .prepare("SELECT spec_json FROM runs WHERE bundle_hash = ?1")
            .map_err(LLMError::Db)?;
        let mut rows = stmt.query(params![hash]).map_err(LLMError::Db)?;
        if let Some(row) = rows.next()? {
            let spec_json: String = row.get(0)?;
            let spec: PipelineSpec = serde_json::from_str(&spec_json)?;
            Ok(Some(spec))
        } else {
            Ok(None)
        }
    }

    /// Persist a successful run (or error) into the SQLite database.
    fn persist_run(
        &self,
        hash: &str,
        spec: &PipelineSpec,
        started_at: DateTime<Utc>,
        finished_at: DateTime<Utc>,
        result: String,
    ) -> Result<(), LLMError> {
        let spec_json = serde_json::to_string(spec)?;
        self.db
            .execute(
                "INSERT INTO runs (bundle_hash, spec_json, started_at, finished_at, result)
                 VALUES (?1, ?2, ?3, ?4, ?5)",
                params![
                    hash,
                    spec_json,
                    started_at.to_rfc3339(),
                    finished_at.to_rfc3339(),
                    result
                ],
            )
            .map_err(LLMError::Db)?;
        Ok(())
    }
}