use std::collections::HashMap;
use std::fs;
use std::io::Write;
use std::path::PathBuf;

use ai_metrics_hud::config::loader::{load, merge, Config, ConfigError, Provider, ProviderConfig};

/// Helper that creates a temporary file with the given contents and returns its path.
fn write_temp_file(contents: &str) -> PathBuf {
    let mut path = std::env::temp_dir();
    path.push(format!("ai-metrics-hud-{}.toml", uuid::Uuid::new_v4()));
    let mut file = fs::File::create(&path).expect("failed to create temp file");
    file.write_all(contents.as_bytes()).expect("failed to write temp file");
    path
}

#[test]
fn test_load_and_merge() -> Result<(), ConfigError> {
    let base_toml = r#"
        [providers.myprovider]
        name = "myprovider"
        token = "abc"
        min_severity = "Info"
        
        [theme]
        success = "green"
        warning = "yellow"
        error = "red"
        info = "blue"
    "#;
    let overlay_toml = r#"
        [providers.myprovider]
        token = "def"
        
        [theme]
        warning = "magenta"
    "#;
    let base_path = write_temp_file(base_toml);
    let overlay_path = write_temp_file(overlay_toml);
    let base_cfg = load(&base_path)?;
    let overlay_cfg = load(&overlay_path)?;
    let merged = merge(base_cfg, overlay_cfg);
    assert_eq!(merged.providers["myprovider"].token.as_deref(), Some("def"));
    assert_eq!(merged.theme.warning, "magenta");
    Ok(())
}
