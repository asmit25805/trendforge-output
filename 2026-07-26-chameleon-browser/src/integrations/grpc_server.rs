use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use chrono::{DateTime, Utc};
use log::{error, info, warn};
use rusqlite::{params, Connection, Result as SqlResult};
use tonic::{transport::Server, Request, Response, Status};

use crate::engine::{Persona, PersonaEngine, ValidationError};
use crate::error::Error;

/// Protobuf generated types for the Persona gRPC service.
///
/// The corresponding `.proto` file must be compiled with `prost-build` in the
/// crate's build script. The generated module is expected to contain the
/// `persona_service_server::PersonaService` trait and request/response messages.
mod persona {
    tonic::include_proto!("persona");
}
use persona::persona_service_server::{PersonaService, PersonaServiceServer};
use persona::{
    ExpirePersonaRequest, ExpirePersonaResponse, GeneratePersonaRequest,
    GeneratePersonaResponse, ValidatePersonaRequest, ValidatePersonaResponse,
};

/// A unit of work that is recorded in the `run_history` SQLite table.
///
/// The task is executed synchronously; its duration and outcome are stored
/// before the gRPC response is sent back to the client.
struct Task<T> {
    /// Human readable name used for logging and run‑history records.
    name: String,
    /// The closure that performs the actual work.
    action: Box<dyn FnOnce() -> Result<T, Error> + Send + 'static>,
}

impl<T> Task<T> {
    /// Executes the task, measures its duration and records the outcome.
    ///
    /// Returns the inner result on success or propagates the error.
    fn run(self, db: Arc<Mutex<Connection>>) -> Result<T, Error> {
        let start_ts: DateTime<Utc> = Utc::now();
        let start_instant = std::time::Instant::now();

        info!("Task '{}' started at {}", self.name, start_ts);
        let result = (self.action)();

        let elapsed = start_instant.elapsed().as_secs_f64();
        let end_ts: DateTime<Utc> = Utc::now();

        // Record the run in the SQLite `run_history` table.
        let db_guard = db
            .lock()
            .map_err(|e| Error::Fatal(format!("run_history DB mutex poisoned: {}", e)))?;
        let insert_res: SqlResult<usize> = db_guard.execute(
            "INSERT INTO run_history (task_name, start_ts, end_ts, success, error) VALUES (?, ?, ?, ?, ?)",
            params![
                self.name,
                start_ts.to_rfc3339(),
                end_ts.to_rfc3339(),
                result.is_ok() as i32,
                result.as_ref().err().map(|e| e.to_string())
            ],
        );

        match insert_res {
            Ok(_) => {
                if result.is_ok() {
                    info!(
                        "Task '{}' completed successfully in {:.3}s",
                        self.name, elapsed
                    );
                } else {
                    warn!(
                        "Task '{}' failed after {:.3}s: {:?}",
                        self.name,
                        elapsed,
                        result.as_ref().err()
                    );
                }
            }
            Err(e) => {
                // Recording the run should never crash the whole process; we log and
                // continue. The original task result is still propagated.
                error!(
                    "Failed to insert run_history record for task '{}': {}",
                    self.name, e
                );
            }
        }

        result
    }
}

/// Implementation of the Persona gRPC service.
///
/// All methods are idempotent and wrapped in a `Task` so that each call is
/// logged in the run‑history database.
pub struct PersonaGrpcService {
    engine: PersonaEngine,
    db: Arc<Mutex<Connection>>,
}

impl PersonaGrpcService {
    /// Creates a new service instance.
    pub fn new(engine: PersonaEngine, db: Connection) -> Self {
        Self {
            engine,
            db: Arc::new(Mutex::new(db)),
        }
    }
}

#[tonic::async_trait]
impl PersonaService for PersonaGrpcService {
    async fn generate_persona(
        &self,
        request: Request<GeneratePersonaRequest>,
    ) -> Result<Response<GeneratePersonaResponse>, Status> {
        let req = request.into_inner();
        let persona_id = if req.persona_id.is_empty() {
            None
        } else {
            Some(req.persona_id)
        };

        let task = Task {
            name: "generate_persona".to_string(),
            action: Box::new(move || {
                // The engine may retry internally on transient validation errors.
                let persona = self.engine.generate(persona_id.clone())?;
                Ok(persona)
            }),
        };

        let persona = task.run(self.db.clone()).map_err(|e| {
            error!("generate_persona error: {}", e);
            Status::internal(e.to_string())
        })?;

        let response = GeneratePersonaResponse {
            persona: Some(persona::Persona {
                id: persona.id,
                user_agent: persona.user_agent,
                platform: persona.platform,
                hardware_concurrency: persona.hardware_concurrency as u32,
                device_memory: persona.device_memory,
                gpu_vendor: persona.gpu_vendor,
                gpu_renderer: persona.gpu_renderer,
                timezone: persona.timezone,
                language: persona.language,
                fonts: persona.fonts,
            }),
        };
        Ok(Response::new(response))
    }

    async fn validate_persona(
        &self,
        request: Request<ValidatePersonaRequest>,
    ) -> Result<Response<ValidatePersonaResponse>, Status> {
        let req = request.into_inner();
        let proto = req
            .persona
            .ok_or_else(|| Status::invalid_argument("missing persona payload"))?;
        let persona = Persona {
            id: proto.id,
            user_agent: proto.user_agent,
            platform: proto.platform,
            hardware_concurrency: proto.hardware_concurrency as u8,
            device_memory: proto.device_memory,
            gpu_vendor: proto.gpu_vendor,
            gpu_renderer: proto.gpu_renderer,
            timezone: proto.timezone,
            language: proto.language,
            fonts: proto.fonts,
        };

        let task = Task {
            name: "validate_persona".to_string(),
            action: Box::new(move || self.engine.validate(&persona).map_err(Error::from)),
        };

        task.run(self.db.clone())
            .map_err(|e| {
                error!("validate_persona error: {}", e);
                Status::internal(e.to_string())
            })
            .map(|_| {
                let resp = ValidatePersonaResponse { valid: true };
                Response::new(resp)
            })
    }

    async fn expire_persona(
        &self,
        request: Request<ExpirePersonaRequest>,
    ) -> Result<Response<ExpirePersonaResponse>, Status> {
        let req = request.into_inner();
        let persona_id = req.persona_id;

        let task = Task {
            name: "expire_persona".to_string(),
            action: Box::new(move || {
                self.engine.expire(&persona_id);
                Ok(())
            }),
        };

        task.run(self.db.clone())
            .map_err(|e| {
                error!("expire_persona error: {}", e);
                Status::internal(e.to_string())
            })
            .map(|_| {
                let resp = ExpirePersonaResponse {};
                Response::new(resp)
            })
    }
}

/// Starts the gRPC server.
///
/// The function blocks until the server shuts down (e.g., via Ctrl‑C). All
/// fatal errors are wrapped in `crate::error::Error` so that the caller can
/// decide whether to exit the process.
///
/// # Arguments
///
/// * `addr` – Socket address to bind the server to.
/// * `engine` – Shared `PersonaEngine` instance.
/// * `db` – SQLite connection used for run‑history logging.
///
/// # Errors
///
/// Returns `Error::Fatal` if the server cannot be started or the bind fails.
pub async fn serve_grpc(
    addr: SocketAddr,
    engine: PersonaEngine,
    db: Connection,
) -> Result<(), Error> {
    // Ensure the run_history table exists; this mirrors the schema used by
    // other components.
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS run_history (
            task_name TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT NOT NULL,
            success INTEGER NOT NULL,
            error TEXT
        );",
    )
    .map_err(|e| {
        Error::Fatal(format!(
            "failed to create run_history table for gRPC server: {}",
            e
        ))
    })?;

    let service = PersonaGrpcService::new(engine, db);
    info!("Starting gRPC server on {}", addr);
    Server::builder()
        .add_service(PersonaServiceServer::new(service))
        .serve(addr)
        .await
        .map_err(|e| Error::Fatal(format!("gRPC server failed: {}", e)))
}