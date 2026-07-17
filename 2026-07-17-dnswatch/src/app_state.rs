use anyhow::{anyhow, Context, Result};
use serde::Deserialize;
use std::collections::HashMap;
use std::net::IpAddr;
use std::path::Path;
use std::sync::Arc;
use tokio::fs;
use tokio::sync::Mutex;

use crate::probe::ProbeType;
use crate::{ResolverInfo, QueryResult};

/// Representation of the mutable application state shared between the engine,
/// UI and metrics collector.  It holds the static resolver list and the most
/// recent `QueryResult` for each resolver.
pub struct AppState {
    /// All resolvers defined in the configuration file.
    pub resolvers: Vec<ResolverInfo>,
    /// Mapping from resolver identifier to the latest query result.
    pub latest_results: HashMap<usize, QueryResult>,
}

impl AppState {
    /// Creates a new `AppState` from a list of resolvers.
    ///
    /// The `latest_results` map starts empty and will be populated as probes
    /// return data.
    pub fn new(resolvers: Vec<ResolverInfo>) -> Self {
        Self {
            resolvers,
            latest_results: HashMap::new(),
        }
    }

    /// Inserts or replaces the result for a resolver.  This method is intended
    /// to be called by the engine when a probe finishes.
    pub fn update_result(&mut self, result: QueryResult) {
        self.latest_results.insert(result.resolver_id, result);
    }

    /// Returns a snapshot of the current results.  The snapshot is a shallow
    /// clone of the internal map so that callers can read without holding the
    /// mutex.
    pub fn snapshot(&self) -> HashMap<usize, QueryResult> {
        self.latest_results.clone()
    }

    /// Loads a TOML configuration file, builds the resolver list and returns
    /// both the list and an `Arc<Mutex<AppState>>` ready for use by the engine.
    ///
    /// The configuration file must contain a top‑level `resolvers` array where
    /// each entry provides the fields required by `ResolverInfo`.  Example:
    ///
    /// ```toml
    /// [[resolvers]]
    /// name = "example"
    /// ip = "1.1.1.1"
    /// probe_type = "udp"
    /// ```
    pub async fn load_config(path: &Path) -> Result<(Vec<ResolverInfo>, Arc<Mutex<AppState>>)> {
        // Read the file asynchronously.
        let raw = fs::read_to_string(path)
            .await
            .with_context(|| format!("Failed to read configuration file {:?}", path))?;

        // Parse the TOML into an intermediate structure.
        let cfg: Config = toml::from_str(&raw)
            .with_context(|| format!("Failed to parse TOML configuration at {:?}", path))?;

        // Convert each entry into a `ResolverInfo`.
        let mut resolvers = Vec::with_capacity(cfg.resolvers.len());
        for (idx, r) in cfg.resolvers.into_iter().enumerate() {
            let ip: IpAddr = r
                .ip
                .parse()
                .with_context(|| format!("Invalid IP address '{}' for resolver '{}'", r.ip, r.name))?;

            let probe_type = match r.probe_type.to_lowercase().as_str() {
                "udp" => ProbeType::Udp,
                "tcp" => ProbeType::Tcp,
                "doh" => ProbeType::Doh,
                other => {
                    return Err(anyhow!(
                        "Unsupported probe_type '{}' for resolver '{}'",
                        other,
                        r.name
                    ))
                }
            };

            let resolver = ResolverInfo {
                id: idx,
                name: r.name,
                ip,
                location: r.location.unwrap_or_default(),
                coords: r.coords,
                probe_type,
            };
            resolvers.push(resolver);
        }

        let state = Arc::new(Mutex::new(AppState::new(resolvers.clone())));
        Ok((resolvers, state))
    }
}

/// Helper structure used only for deserialising the configuration file.
#[derive(Debug, Deserialize)]
struct Config {
    #[serde(default)]
    resolvers: Vec<ResolverConfig>,
}

/// Partial representation of a resolver as it appears in the TOML file.
#[derive(Debug, Deserialize)]
struct ResolverConfig {
    name: String,
    ip: String,
    #[serde(default)]
    location: Option<String>,
    #[serde(default)]
    coords: Option<(f64, f64)>,
    #[serde(rename = "probe_type")]
    probe_type: String,
}