use std::collections::HashMap;
use std::env;
use std::time::Duration;

use chrono::Utc;
use log::{error, info};
use env_logger::Env;
use serde_json::json;
use uuid::Uuid;

use clickhouse::Client as ClickHouseClient;

use cogni_tune::services::telemetry::{store_event, TelemetryEvent, Source};
use cogni_tune::services::config_store::{
    AgentMemory, ConfigStore, MemoryKind,
};
use cogni_tune::engine::{IngestError, ApplyError};
use cogni_tune::mcp::server::McpServer;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Initialise logger.
    env_logger::Builder::from_env(Env::default().default_filter_or("info")).init();

    // -------------------------------------------------------------------------
    // 1. Ingest a telemetry event.
    // -------------------------------------------------------------------------
    let clickhouse = ClickHouseClient::default()
        .with_url(&env::var("CLICKHOUSE_URL").unwrap_or_else(|_| "http://localhost:8123".into()));

    let telemetry = TelemetryEvent {
        id: Uuid::new_v4(),
        timestamp: Utc::now(),
        source: Source::Log,
        payload: json!({ "message": "example telemetry payload" }),
        resource_attrs: HashMap::new(),
    };

    match store_event(&clickhouse, telemetry).await {
        Ok(_) => info!("telemetry stored successfully"),
        Err(e) => {
            error!("failed to store telemetry: {}", e);
            return Err(Box::new(e));
        }
    }

    // -------------------------------------------------------------------------
    // 2. Retrieve the latest configuration snapshot for a project.
    // -------------------------------------------------------------------------
    // Build a PostgreSQL connection pool.
    let database_url = env::var("DATABASE_URL")
        .unwrap_or_else(|_| "postgres://postgres:postgres@localhost:5432/postgres".into());

    let manager =
        diesel::r2d2::ConnectionManager::<diesel::pg::PgConnection>::new(database_url);
    let pool = diesel::r2d2::Pool::builder()
        .max_size(5)
        .build(manager)
        .expect("failed to create DB pool");

    let config_store = ConfigStore::new(pool);

    let project_id = Uuid::new_v4(); // In a real deployment this would be a known project.
    match config_store.get_current(project_id).await {
        Ok(snapshot) => info!("current config version {} retrieved", snapshot.version),
        Err(err) => error!("could not fetch configuration: {}", err),
    }

    // -------------------------------------------------------------------------
    // 3. Persist a short‑lived agent memory (simulating an LLM proposal).
    // -------------------------------------------------------------------------
    let memory = AgentMemory {
        id: Uuid::new_v4(),
        project_id,
        kind: MemoryKind::Infra,
        title: "Suggested firewall rule".into(),
        body: "Allow inbound TCP 443 from 10.0.0.0/8".into(),
        source_user_id: None,
        source_agent_run_id: Some(Uuid::new_v4()),
        created_at: Utc::now(),
    };

    if let Err(err) = config_store.save_memory(memory).await {
        error!("failed to save agent memory: {}", err);
    } else {
        info!("agent memory persisted");
    }

    // -------------------------------------------------------------------------
    // 4. Start the MCP JSON‑RPC server (runs forever).
    // -------------------------------------------------------------------------
    let mcp = McpServer::new();
    tokio::spawn(async move {
        if let Err(e) = mcp.run().await {
            error!("MCP server terminated with error: {}", e);
        }
    });

    // Keep the example alive briefly to illustrate that the server is running.
    tokio::time::sleep(Duration::from_secs(5)).await;

    Ok(())
}