use std::collections::{HashMap, VecDeque};
use std::fs;
use std::path::Path;
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::models::PipelineSpec;

/// Maximum number of entries the in‑memory cache can hold.
const MAX_CACHE: usize = 8;

/// Errors that can be produced by the resource cache.
#[derive(Error, Debug)]
pub enum CacheError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("SQLite error: {0}")]
    Sqlite(#[from] rusqlite::Error),

    #[error("Serialization error: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("Cache miss for key `{0}`")]
    Miss(String),
}

/// Persistent record of a cache insertion.
#[derive(Debug, Serialize, Deserialize)]
struct CacheRecord {
    /// SHA‑256 hash used as the cache key.
    key: String,
    /// Serialized `PipelineSpec`.
    spec_json: String,
    /// When the entry was inserted.
    inserted_at: DateTime<Utc>,
}

/// In‑memory LRU cache backed by a SQLite table for history.
pub struct ResourceCache {
    /// Mapping from hash → spec.
    map: Mutex<HashMap<String, PipelineSpec>>,
    /// Order of keys, oldest at the front.
    order: Mutex<VecDeque<String>>,
    /// SQLite connection used for persisting cache history.
    db: Arc<Connection>,
}

impl ResourceCache {
    /// Create a new `ResourceCache`.  The SQLite database is created if it does
    /// not exist and the required table is ensured.
    ///
    /// * `db_path` – Path to the SQLite file that stores cache history.
    pub fn new<P: AsRef<Path>>(db_path: P) -> Result<Self, CacheError> {
        // Ensure the parent directory exists.
        if let Some(parent) = db_path.as_ref().parent() {
            fs::create_dir_all(parent)?;
        }

        info!(
            "Opening cache database at {}",
            db_path.as_ref().display()
        );
        let conn = Connection::open(db_path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS cache_history (
                key TEXT PRIMARY KEY,
                spec_json TEXT NOT NULL,
                inserted_at TEXT NOT NULL
            );",
        )?;

        Ok(Self {
            map: Mutex::new(HashMap::new()),
            order: Mutex::new(VecDeque::new()),
            db: Arc::new(conn),
        })
    }

    /// Retrieve a cached `PipelineSpec` by its hash.  Returns `None` if the key
    /// is not present in the in‑memory cache.
    ///
    /// The method logs the lookup attempt.
    pub fn get(&self, hash: &str) -> Result<Option<PipelineSpec>, CacheError> {
        info!("Cache lookup for key {}", hash);
        let map = self.map.lock().unwrap();
        if let Some(spec) = map.get(hash) {
            info!("Cache hit for key {}", hash);
            Ok(Some(spec.clone()))
        } else {
            warn!("Cache miss for key {}", hash);
            Ok(None)
        }
    }

    /// Insert a new `PipelineSpec` into the cache.  If the cache already holds
    /// `MAX_CACHE` entries the oldest one is evicted.  The insertion is also
    /// persisted to the SQLite history table.
    ///
    /// * `hash` – Deterministic SHA‑256 hash of the serialized spec.
    /// * `spec` – The `PipelineSpec` to cache.
    pub fn insert(&self, hash: String, spec: PipelineSpec) -> Result<(), CacheError> {
        info!("Inserting cache entry for key {}", hash);
        // Persist to SQLite first; if that fails we abort before mutating memory.
        self.persist_to_db(&hash, &spec)?;

        let mut map = self.map.lock().unwrap();
        let mut order = self.order.lock().unwrap();

        // Evict if capacity would be exceeded.
        if map.len() >= MAX_CACHE {
            if let Some(old_key) = order.pop_front() {
                info!("Evicting oldest cache entry {}", old_key);
                map.remove(&old_key);
            }
        }

        // Insert the new entry.
        map.insert(hash.clone(), spec);
        order.push_back(hash);
        info!("Cache insertion complete");
        Ok(())
    }

    /// Persist a cache entry to the SQLite history table.  This is a separate
    /// private helper so that the in‑memory structures are only updated after
    /// the database write succeeds.
    fn persist_to_db(&self, hash: &str, spec: &PipelineSpec) -> Result<(), CacheError> {
        let spec_json = serde_json::to_string(spec)?;
        let now = Utc::now();

        info!(
            "Persisting cache entry {} to database at {}",
            hash,
            now.to_rfc3339()
        );

        self.db.execute(
            "INSERT OR REPLACE INTO cache_history (key, spec_json, inserted_at) VALUES (?1, ?2, ?3)",
            params![hash, spec_json, now.to_rfc3339()],
        )?;
        Ok(())
    }

    /// Retrieve a historic cache record from the SQLite database.  This is used
    /// by diagnostics and does not affect the in‑memory LRU state.
    ///
    /// * `hash` – The cache key to look up.
    pub fn get_persistent(&self, hash: &str) -> Result<Option<CacheRecord>, CacheError> {
        let mut stmt = self
            .db
            .prepare("SELECT key, spec_json, inserted_at FROM cache_history WHERE key = ?1")?;
        let mut rows = stmt.query(params![hash])?;

        if let Some(row) = rows.next()? {
            let key: String = row.get(0)?;
            let spec_json: String = row.get(1)?;
            let inserted_at_str: String = row.get(2)?;
            let inserted_at = DateTime::parse_from_rfc3339(&inserted_at_str)
                .map_err(|e| CacheError::Io(std::io::Error::new(std::io::ErrorKind::InvalidData, e)))?
                .with_timezone(&Utc);
            Ok(Some(CacheRecord {
                key,
                spec_json,
                inserted_at,
            }))
        } else {
            Ok(None)
        }
    }

    /// Clear the entire cache, both in‑memory and persisted history.  All
    /// entries are removed and the SQLite table is truncated.
    pub fn clear(&self) -> Result<(), CacheError> {
        info!("Clearing entire cache");
        {
            let mut map = self.map.lock().unwrap();
            let mut order = self.order.lock().unwrap();
            map.clear();
            order.clear();
        }
        self.db
            .execute_batch("DELETE FROM cache_history;")?;
        info!("Cache cleared");
        Ok(())
    }
}