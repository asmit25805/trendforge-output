use std::fs::{self, File};
use std::io::Write;
use std::path::{Path, PathBuf};

use chrono::Utc;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use crate::pipeline_builder::{BuildError, PipelineBuilder};
use crate::models::{
    PipelineSpec, PipelineStep, TriggerSpec, TriggerType, Tool,
};

/// Helper to create a temporary directory that is automatically removed when
/// dropped.
fn temp_dir() -> tempfile::TempDir {
    tempfile::TempDir::new().expect("failed to create temporary directory")
}

/// Helper to write a minimal Tera template used by `PipelineBuilder`.
fn write_template(dir: &Path) {
    let tmpl_path = dir.join("pipeline.yml.tera");
    let mut file = File::create(&tmpl_path).expect("failed to create template file");
    writeln!(
        file,
        r#"intent: {{ intent }}
steps:
{% for step in steps -%}
- id: {{ step.id }}
  action: {{ step.action }}
  tool: {{ step.tool }}
  script: {{ step.script }}
{% endfor -%}
trigger: {{ trigger.trigger_type }}
"#
    )
    .expect("failed to write template content");
}

/// Construct a simple, valid `PipelineSpec` used by many tests.
fn make_valid_spec() -> PipelineSpec {
    PipelineSpec {
        intent: "Run tests".to_string(),
        steps: vec![PipelineStep {
            id: "s1".to_string(),
            action: "Execute unit tests".to_string(),
            tool: Tool::Shell,
            script: "cargo test".to_string(),
        }],
        trigger: TriggerSpec {
            trigger_type: TriggerType::Manual,
            cron: None,
            branch: None,
        },
    }
}

/// Compute the SHA‑256 hash of a `PipelineSpec` as the builder does.
fn spec_hash(spec: &PipelineSpec) -> String {
    let json = serde_json::to_string(spec).expect("failed to serialize spec");
    let mut hasher = Sha256::new();
    hasher.update(json.as_bytes());
    hex::encode(hasher.finalize())
}

#[test]
fn test_builder_new_successful() {
    let tmpl_dir = temp_dir();
    write_template(tmpl_dir.path());

    let db_path = tmpl_dir.path().join("builder.db");
    let builder = PipelineBuilder::new(tmpl_dir.path(), &db_path);
    assert!(builder.is_ok(), "Builder should be created with valid template dir");
}

#[test]
fn test_builder_new_missing_template_dir() {
    let non_existent = PathBuf::from("non_existent_dir");
    let db_path = PathBuf::from("does_not_matter.db");
    let err = PipelineBuilder::new(&non_existent, &db_path).unwrap_err();
    match err {
        BuildError::Other(msg) => {
            assert!(
                msg.contains("does not exist"),
                "Error message should indicate missing directory"
            );
        }
        _ => panic!("Unexpected error variant: {:?}", err),
    }
}

#[test]
fn test_build_creates_artifacts_and_records_history() {
    let tmpl_dir = temp_dir();
    write_template(tmpl_dir.path());

    let db_path = tmpl_dir.path().join("history.db");
    let builder = PipelineBuilder::new(tmpl_dir.path(), &db_path).expect("builder init failed");

    let spec = make_valid_spec();
    let artifacts = builder.build(&spec).expect("build failed");

    // Verify artifact directory exists.
    assert!(artifacts.dir.is_dir(), "Artifact directory should exist");

    // At least one file should be generated.
    assert!(
        !artifacts.files.is_empty(),
        "Builder should produce at least one artifact file"
    );

    // Check that the rendered file contains the intent string.
    let rendered = fs::read_to_string(&artifacts.files[0])
        .expect("failed to read rendered artifact");
    assert!(
        rendered.contains(&spec.intent),
        "Rendered artifact should contain the intent"
    );

    // Verify a history entry was inserted.
    let conn = rusqlite::Connection::open(&db_path).expect("failed to open sqlite db");
    let mut stmt = conn
        .prepare("SELECT spec_hash, result FROM build_history WHERE spec_hash = ?1")
        .expect("failed to prepare query");
    let mut rows = stmt
        .query([spec_hash(&spec)])
        .expect("failed to execute query");
    let row = rows.next().expect("no history row found").expect("error fetching row");
    let stored_hash: String = row.get(0).expect("failed to get spec_hash");
    let result: String = row.get(1).expect("failed to get result");
    assert_eq!(stored_hash, spec_hash(&spec), "Stored hash must match spec hash");
    assert_eq!(result, "Ok", "Result should be recorded as Ok");
}

#[test]
fn test_build_fails_validation_for_empty_steps() {
    let tmpl_dir = temp_dir();
    write_template(tmpl_dir.path());

    let db_path = tmpl_dir.path().join("validation.db");
    let builder = PipelineBuilder::new(tmpl_dir.path(), &db_path).expect("builder init failed");

    let mut spec = make_valid_spec();
    spec.steps.clear(); // Empty steps should trigger validation error.

    let err = builder.build(&spec).unwrap_err();
    match err {
        BuildError::Validation(msg) => {
            assert!(
                msg.to_lowercase().contains("steps"),
                "Validation message should mention steps"
            );
        }
        _ => panic!("Expected Validation error, got {:?}", err),
    }
}

#[test]
fn test_build_is_idempotent_and_creates_separate_dirs() {
    let tmpl_dir = temp_dir();
    write_template(tmpl_dir.path());

    let db_path = tmpl_dir.path().join("idempotent.db");
    let builder = PipelineBuilder::new(tmpl_dir.path(), &db_path).expect("builder init failed");

    let spec = make_valid_spec();

    let artifacts1 = builder.build(&spec).expect("first build failed");
    let artifacts2 = builder.build(&spec).expect("second build failed");

    // Directories must be distinct to avoid overwriting previous results.
    assert_ne!(
        artifacts1.dir, artifacts2.dir,
        "Each build should use a unique artifact directory"
    );

    // Both directories should contain the rendered file.
    for art in &[artifacts1, artifacts2] {
        assert!(art.dir.is_dir(), "Artifact directory should exist");
        assert!(
            !art.files.is_empty(),
            "Each build should produce at least one file"
        );
    }
}

#[test]
fn test_build_records_nonzero_duration() {
    let tmpl_dir = temp_dir();
    write_template(tmpl_dir.path());

    let db_path = tmpl_dir.path().join("duration.db");
    let builder = PipelineBuilder::new(tmpl_dir.path(), &db_path).expect("builder init failed");

    let spec = make_valid_spec();
    builder.build(&spec).expect("build failed");

    let conn = rusqlite::Connection::open(&db_path).expect("failed to open sqlite db");
    let mut stmt = conn
        .prepare(
            "SELECT duration_ms FROM build_history WHERE spec_hash = ?1 ORDER BY started_at DESC LIMIT 1",
        )
        .expect("failed to prepare duration query");
    let mut rows = stmt
        .query([spec_hash(&spec)])
        .expect("failed to execute duration query");
    let row = rows.next().expect("no duration row found").expect("error fetching row");
    let duration_ms: i64 = row.get(0).expect("failed to get duration_ms");
    assert!(
        duration_ms > 0,
        "Recorded duration should be greater than zero"
    );
}