use std::io::Cursor;

use ai_metrics_hud::config::loader::Provider;
use ai_metrics_hud::core::parser::{extract_segments, parse as parse_telemetry, ParseError, Segment, TelemetryData};

/// Helper that returns true if a segment with the given key and value exists.
fn contains_segment(segments: &[Segment], key: &str, value: &str) -> bool {
    segments.iter().any(|s| s.key == key && s.value == value)
}

#[test]
fn test_parse_and_extract() -> Result<(), ParseError> {
    let json = r#"{
        "provider": "test",
        "timestamp": "2023-01-01T00:00:00Z",
        "payload": {"cpu": "5%", "mem": "128MiB"}
    }"#;
    let cursor = Cursor::new(json);
    let telemetry = parse_telemetry(cursor)?;
    assert_eq!(telemetry.provider.name, "test");
    let segments = extract_segments(&telemetry);
    assert!(contains_segment(&segments, "cpu", "5%"));
    assert!(contains_segment(&segments, "mem", "128MiB"));
    Ok(())
}
