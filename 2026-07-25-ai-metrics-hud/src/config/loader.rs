use std::collections::HashMap;
use std::fmt;
use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};

/// Severity levels used for filtering telemetry.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Severity {
    Debug,
    Info,
    Warning,
    Error,
}

/// Configuration for a specific provider (e.g., OpenAI, Claude).
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ProviderConfig {
    /// Human readable name of the provider.
    pub name: String,
    /// Optional API key or token.
    pub token: Option<String>,
    /// Minimum severity to display.
    pub min_severity: Severity,
}

/// Theme configuration for colourising output.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct ThemeConfig {
    pub success: String,
    pub warning: String,
    pub error: String,
    pub info: String,
}

/// Segment configuration – controls ordering and visibility.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SegmentConfig {
    pub key: String,
    pub enabled: bool,
    pub order: usize,
}

/// Top‑level configuration structure for the HUD binary.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Config {
    /// Mapping of provider name to its configuration.
    pub providers: HashMap<String, ProviderConfig>,
    /// Global theme settings.
    pub theme: ThemeConfig,
    /// Segment‑specific configuration.
    pub segments: Vec<SegmentConfig>,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            providers: HashMap::new(),
            theme: ThemeConfig {
                success: "green".into(),
                warning: "yellow".into(),
                error: "red".into(),
                info: "blue".into(),
            },
            segments: Vec::new(),
        }
    }
}

#[derive(Debug)]
pub enum ConfigError {
    Io(std::io::Error),
    Parse(toml::de::Error),
}

impl fmt::Display for ConfigError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ConfigError::Io(e) => write!(f, "IO error: {}", e),
            ConfigError::Parse(e) => write!(f, "Parse error: {}", e),
        }
    }
}

impl std::error::Error for ConfigError {}

/// Load a configuration file from the given path.
pub fn load<P: AsRef<Path>>(path: P) -> Result<Config, ConfigError> {
    let content = fs::read_to_string(path).map_err(ConfigError::Io)?;
    toml::from_str(&content).map_err(ConfigError::Parse)
}

/// Merge an overlay configuration on top of a base configuration.
pub fn merge(base: Config, overlay: Config) -> Config {
    let mut merged = base;
    // Merge providers.
    for (k, v) in overlay.providers {
        merged.providers.insert(k, v);
    }
    // Merge theme – overlay fields replace base if non‑empty.
    merged.theme = ThemeConfig {
        success: if overlay.theme.success.is_empty() { merged.theme.success } else { overlay.theme.success },
        warning: if overlay.theme.warning.is_empty() { merged.theme.warning } else { overlay.theme.warning },
        error: if overlay.theme.error.is_empty() { merged.theme.error } else { overlay.theme.error },
        info: if overlay.theme.info.is_empty() { merged.theme.info } else { overlay.theme.info },
    };
    // Merge segments – keep ordering from overlay.
    merged.segments = overlay.segments;
    merged
}
