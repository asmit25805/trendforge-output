use std::io::{self, Read};
use std::thread::sleep;
use std::time::Duration;

use chrono::{DateTime, Utc};
use log::{debug, error};
use serde::Deserialize;
use serde_json::Value;

use crate::config::loader::{Provider, Severity};

/// Representation of raw telemetry JSON.
#[derive(Debug, Clone, Deserialize)]
pub struct TelemetryData {
    pub provider: Provider,
    pub timestamp: DateTime<Utc>,
    pub payload: Value,
}

/// A single displayable segment extracted from telemetry.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Segment {
    pub key: String,
    pub value: String,
    pub severity: Severity,
}

/// Errors that can arise while parsing telemetry streams.
#[derive(Debug, thiserror::Error)]
pub enum ParseError {
    #[error("I/O error while reading telemetry: {0}")]
    Io(#[from] io::Error),
    #[error("Failed to deserialize JSON: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Invalid timestamp format")] 
    Timestamp,
}

/// Parse telemetry from any `Read` implementation.
pub fn parse<R: Read>(mut reader: R) -> Result<TelemetryData, ParseError> {
    let mut buf = String::new();
    reader.read_to_string(&mut buf)?;
    let json: Value = serde_json::from_str(&buf)?;
    // For demonstration we assume a fixed shape.
    let provider_name = json["provider"].as_str().unwrap_or("unknown");
    let provider = Provider { name: provider_name.into() };
    let timestamp_str = json["timestamp"].as_str().ok_or(ParseError::Timestamp)?;
    let timestamp = DateTime::parse_from_rfc3339(timestamp_str)
        .map_err(|_| ParseError::Timestamp)?
        .with_timezone(&Utc);
    Ok(TelemetryData {
        provider,
        timestamp,
        payload: json["payload"].clone(),
    })
}

/// Extract a list of `Segment`s from parsed telemetry.
pub fn extract_segments(data: &TelemetryData) -> Vec<Segment> {
    // In a real implementation this would be provider‑specific.
    let mut segments = Vec::new();
    if let Some(map) = data.payload.as_object() {
        for (k, v) in map {
            let value = v.as_str().unwrap_or(&v.to_string()).to_string();
            // Default to Info severity for all extracted keys.
            segments.push(Segment {
                key: k.clone(),
                value,
                severity: Severity::Info,
            });
        }
    }
    segments
}
