use std::fs::{self, File};
use std::io::{self, Write, Read};
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::thread;

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection};
use serde_yaml;
use tera::{Context, Tera};
use uuid::Uuid;

use crate::models::{PipelineSpec, PipelineStep, TriggerSpec};

/// Errors that can be produced by the pipeline builder.
#[derive(thiserror::Error, Debug)]
pub enum BuildError {
    #[error("I/O error: {0}")]
    Io(#[from] io::Error),
    #[error("Template rendering error: {0}")]
    Template(#[from] tera::Error),
    #[error("Validation error: {0}")]
    Validation(String),
    #[error("Database error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("Unexpected error: {0}")]
    Other(String),
}

/// Collection of generated artifact paths.
pub struct PipelineArtifacts {
    /// Directory that contains all generated files.
    pub dir: PathBuf,
    /// Individual artifact files.
    pub files: Vec<PathBuf>,
}

/// Builder that converts a `PipelineSpec` into concrete CI artifacts.
pub struct PipelineBuilder {
    /// Directory containing Tera templates.
    template_dir: PathBuf,
    /// Shared SQLite connection for persisting build history.
    db: Arc<Connection>,
}

impl PipelineBuilder {
    /// Create a new `PipelineBuilder` with a template directory and a SQLite DB path.
    pub fn new(
        template_dir: impl Into<PathBuf>,
        db_path: impl AsRef<Path>,
    ) -> Result<Self, BuildError> {
        let tmpl_dir = template_dir.into();
        if !tmpl_dir.is_dir() {
            return Err(BuildError::Other(format!(
                "Template directory does not exist: {}",
                tmpl_dir.display()
            )));
        }

        let conn = Connection::open(db_path)?;
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS build_history (
                id TEXT PRIMARY KEY,
                spec_hash TEXT NOT NULL,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                duration_ms INTEGER NOT NULL,
                result TEXT NOT NULL
            );",
        )?;

        Ok(Self {
            template_dir: tmpl_dir,
            db: Arc::new(conn),
        })
    }

    /// Build the artifacts for a given `PipelineSpec`.
    ///
    /// The method renders templates, writes files, validates them, records the
    /// build in the SQLite history table, and returns the generated artifact set.
    pub fn build(&self, spec: &PipelineSpec) -> Result<PipelineArtifacts, BuildError> {
        let start_instant = std::time::Instant::now();
        let start_time: DateTime<Utc> = Utc::now();

        // Compute a deterministic hash of the spec for caching / history.
        let spec_hash = {
            let json = serde_json::to_string(spec).map_err(|e| BuildError::Other(e.to_string()))?;
            let mut hasher = sha2::Sha256::new();
            hasher.update(json.as_bytes());
            format!("{:x}", hasher.finalize())
        };

        // Prepare output directory.
        let artifact_dir = self.prepare_artifact_dir(&spec_hash)?;
        info!("Artifact directory created at {}", artifact_dir.display());

        // Initialise Tera.
        let tera_pattern = format!("{}/**/*", self.template_dir.display());
        let tera = Tera::new(&tera_pattern)?;

        // Render each step concurrently.
        let mut handles = Vec::new();
        let mut generated_files = Vec::new();

        for step in &spec.steps {
            let tera = tera.clone();
            let ctx = self.context_from_step(step, &spec.trigger);
            let tmpl_name = format!("{}.tera", step.tool.to_string().to_lowercase());

            let out_path = artifact_dir.join(&step.id);
            generated_files.push(out_path.clone());

            let handle = thread::spawn(move || -> Result<PathBuf, BuildError> {
                info!("Rendering step {} using template {}", step.id, tmpl_name);
                let rendered = tera.render(&tmpl_name, &ctx)?;
                let mut file = File::create(&out_path)?;
                file.write_all(rendered.as_bytes())?;
                Ok(out_path)
            });
            handles.push(handle);
        }

        // Collect results.
        for handle in handles {
            match handle.join() {
                Ok(Ok(_)) => {}
                Ok(Err(e)) => {
                    error!("Rendering thread failed: {}", e);
                    self.record_history(&spec_hash, start_time, Utc::now(), start_instant.elapsed(), &e)?;
                    return Err(e);
                }
                Err(_) => {
                    let err = BuildError::Other("Thread panicked".into());
                    error!("Rendering thread panicked");
                    self.record_history(&spec_hash, start_time, Utc::now(), start_instant.elapsed(), &err)?;
                    return Err(err);
                }
            }
        }

        // Validate generated artifacts.
        let artifacts = PipelineArtifacts {
            dir: artifact_dir.clone(),
            files: generated_files.clone(),
        };
        self.validate(&artifacts)?;

        // Record successful build.
        let finish_time: DateTime<Utc> = Utc::now();
        self.record_history(
            &spec_hash,
            start_time,
            finish_time,
            start_instant.elapsed(),
            &BuildError::Other("OK".into()),
        )?;

        info!("Build completed successfully in {} ms", start_instant.elapsed().as_millis());
        Ok(artifacts)
    }

    /// Validate generated artifacts for syntactic correctness.
    ///
    /// Currently validates YAML files with `serde_yaml` and ensures shell scripts are non‑empty.
    pub fn validate(&self, artifacts: &PipelineArtifacts) -> Result<(), BuildError> {
        for file_path in &artifacts.files {
            let ext = file_path.extension().and_then(|s| s.to_str()).unwrap_or_default();
            let mut content = String::new();
            File::open(file_path)?.read_to_string(&mut content)?;

            match ext {
                "yml" | "yaml" => {
                    info!("Validating YAML file {}", file_path.display());
                    serde_yaml::from_str::<serde_yaml::Value>(&content)
                        .map_err(|e| BuildError::Validation(format!("YAML error in {}: {}", file_path.display(), e)))?;
                }
                "sh" => {
                    info!("Validating shell script {}", file_path.display());
                    if content.trim().is_empty() {
                        return Err(BuildError::Validation(format!(
                            "Shell script {} is empty",
                            file_path.display()
                        )));
                    }
                }
                _ => {
                    warn!("Unknown file type for validation: {}", file_path.display());
                }
            }
        }
        Ok(())
    }

    /// Prepare a unique artifact directory under the user's home directory.
    fn prepare_artifact_dir(&self, spec_hash: &str) -> Result<PathBuf, BuildError> {
        let home = dirs::home_dir().ok_or_else(|| BuildError::Other("Unable to locate home directory".into()))?;
        let base = home.join(".tracecraft").join("artifacts");
        fs::create_dir_all(&base)?;
        let dir = base.join(format!("{}-{}", Uuid::new_v4(), spec_hash));
        fs::create_dir_all(&dir)?;
        Ok(dir)
    }

    /// Convert a `PipelineStep` and its trigger into a Tera context.
    fn context_from_step(&self, step: &PipelineStep, trigger: &TriggerSpec) -> Context {
        let mut ctx = Context::new();
        ctx.insert("id", &step.id);
        ctx.insert("action", &step.action);
        ctx.insert("tool", &step.tool.to_string());
        ctx.insert("script", &step.script);
        ctx.insert("trigger", &trigger);
        ctx
    }

    /// Record a build attempt in the SQLite history table.
    fn record_history(
        &self,
        spec_hash: &str,
        started_at: DateTime<Utc>,
        finished_at: DateTime<Utc>,
        duration: std::time::Duration,
        result: &BuildError,
    ) -> Result<(), BuildError> {
        let id = Uuid::new_v4().to_string();
        let result_str = match result {
            BuildError::Other(msg) if msg == "OK" => "OK".to_string(),
            _ => format!("{:?}", result),
        };
        self.db.execute(
            "INSERT INTO build_history (id, spec_hash, started_at, finished_at, duration_ms, result)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                id,
                spec_hash,
                started_at.to_rfc3339(),
                finished_at.to_rfc3339(),
                duration.as_millis() as i64,
                result_str
            ],
        )?;
        Ok(())
    }
}