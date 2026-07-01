use std::time::Duration;

use anyhow::Result;
use chrono::{DateTime, Utc};
use diesel::prelude::*;
use diesel::r2d2::{ConnectionManager, Pool};
use diesel::sql_query;
use serde_json::json;
use testcontainers::clients::Cli;
use testcontainers::images::postgres::Postgres;
use testcontainers::Container;
use tokio::time::sleep;
use uuid::Uuid;

use crate::services::config_store::{
    AgentMemory, ConfigStore, ConfigSnapshot, MemoryFilter, MemoryKind,
};

/// Spin up a PostgreSQL container, apply the minimal schema, and return a
/// `ConfigStore` backed by a connection pool.
///
/// The container is automatically stopped when the returned `Container` is
/// dropped. The caller must keep the container alive for the duration of the
/// test.
async fn setup_config_store() -> Result<(ConfigStore, Container<'static, Postgres>)> {
    // Start Docker container.
    let docker = Cli::default();
    let container = docker.run(Postgres::default());

    // Build connection URL.
    let host_port = container.get_host_port_ipv4(5432);
    let db_url = format!("postgres://postgres:postgres@127.0.0.1:{}/postgres", host_port);

    // Wait until the DB is ready.
    let mut attempts = 0;
    loop {
        attempts += 1;
        match PgConnection::establish(&db_url) {
            Ok(conn) => {
                // Apply schema.
                conn.batch_execute(
                    r#"
                    CREATE TABLE IF NOT EXISTS config_snapshots (
                        id UUID PRIMARY KEY,
                        project_id UUID NOT NULL,
                        config_json JSONB NOT NULL,
                        version BIGINT NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS agent_memories (
                        id UUID PRIMARY KEY,
                        project_id UUID NOT NULL,
                        kind TEXT NOT NULL,
                        title VARCHAR(200) NOT NULL,
                        body VARCHAR(4000) NOT NULL,
                        source_user_id UUID,
                        source_agent_run_id UUID,
                        created_at TIMESTAMPTZ NOT NULL
                    );
                    "#,
                )
                .expect("failed to create schema");
                // Build pool.
                let manager = ConnectionManager::<PgConnection>::new(db_url);
                let pool = Pool::builder()
                    .max_size(5)
                    .build(manager)
                    .expect("failed to create pool");
                let store = ConfigStore::new(pool);
                return Ok((store, container));
            }
            Err(_) if attempts < 10 => {
                sleep(Duration::from_millis(500)).await;
            }
            Err(e) => return Err(e.into()),
        }
    }
}

/// Helper to insert a `ConfigSnapshot` directly via Diesel.
fn insert_snapshot(conn: &PgConnection, snapshot: &ConfigSnapshot) {
    sql_query(
        "INSERT INTO config_snapshots (id, project_id, config_json, version, created_at)
         VALUES ($1, $2, $3, $4, $5)",
    )
    .bind::<diesel::sql_types::Uuid, _>(snapshot.id)
    .bind::<diesel::sql_types::Uuid, _>(snapshot.project_id)
    .bind::<diesel::sql_types::Jsonb, _>(snapshot.config_json.clone())
    .bind::<diesel::sql_types::BigInt, _>(snapshot.version)
    .bind::<diesel::sql_types::Timestamptz, _>(snapshot.created_at)
    .execute(conn)
    .expect("failed to insert snapshot");
}

/// Helper to insert an `AgentMemory` directly via Diesel.
fn insert_memory(conn: &PgConnection, memory: &AgentMemory) {
    sql_query(
        "INSERT INTO agent_memories (id, project_id, kind, title, body,
         source_user_id, source_agent_run_id, created_at)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
    )
    .bind::<diesel::sql_types::Uuid, _>(memory.id)
    .bind::<diesel::sql_types::Uuid, _>(memory.project_id)
    .bind::<diesel::sql_types::Text, _>(memory.kind.to_string())
    .bind::<diesel::sql_types::VarChar, _>(memory.title.clone())
    .bind::<diesel::sql_types::VarChar, _>(memory.body.clone())
    .bind::<diesel::sql_types::Nullable<diesel::sql_types::Uuid>, _>(memory.source_user_id)
    .bind::<diesel::sql_types::Nullable<diesel::sql_types::Uuid>, _>(memory.source_agent_run_id)
    .bind::<diesel::sql_types::Timestamptz, _>(memory.created_at)
    .execute(conn)
    .expect("failed to insert memory");
}

#[tokio::test]
async fn test_get_current_returns_latest_snapshot() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let conn = store.pool.get()?;

    let project_id = Uuid::new_v4();

    let older = ConfigSnapshot {
        id: Uuid::new_v4(),
        project_id,
        config_json: json!({ "setting": "old" }),
        version: 1,
        created_at: Utc::now() - chrono::Duration::minutes(10),
    };
    let newer = ConfigSnapshot {
        id: Uuid::new_v4(),
        project_id,
        config_json: json!({ "setting": "new" }),
        version: 2,
        created_at: Utc::now(),
    };

    insert_snapshot(&conn, &older);
    insert_snapshot(&conn, &newer);

    let result = store.get_current(project_id).await?;
    assert_eq!(result.id, newer.id);
    assert_eq!(result.version, newer.version);
    Ok(())
}

#[tokio::test]
async fn test_get_current_returns_error_when_no_snapshot() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let project_id = Uuid::new_v4();

    let err = store.get_current(project_id).await.unwrap_err();
    // The exact error type is `DbError::Query`, but we only assert that an error occurs.
    assert!(format!("{:?}", err).contains("Query"));
    Ok(())
}

#[tokio::test]
async fn test_save_memory_persists_and_can_be_retrieved() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let conn = store.pool.get()?;

    let memory = AgentMemory {
        id: Uuid::new_v4(),
        project_id: Uuid::new_v4(),
        kind: MemoryKind::Feedback,
        title: "Test memory".into(),
        body: "Detailed description".into(),
        source_user_id: None,
        source_agent_run_id: None,
        created_at: Utc::now(),
    };

    store.save_memory(memory.clone()).await?;
    // Verify directly via SQL.
    let fetched: AgentMemory = sql_query(
        "SELECT * FROM agent_memories WHERE id = $1",
    )
    .bind::<diesel::sql_types::Uuid, _>(memory.id)
    .get_result(&conn)
    .expect("memory not found");

    assert_eq!(fetched.title, memory.title);
    assert_eq!(fetched.body, memory.body);
    Ok(())
}

#[tokio::test]
async fn test_list_memories_filters_by_project() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let conn = store.pool.get()?;

    let project_a = Uuid::new_v4();
    let project_b = Uuid::new_v4();

    let mem_a = AgentMemory {
        id: Uuid::new_v4(),
        project_id: project_a,
        kind: MemoryKind::Infra,
        title: "A".into(),
        body: "A body".into(),
        source_user_id: None,
        source_agent_run_id: None,
        created_at: Utc::now(),
    };
    let mem_b = AgentMemory {
        id: Uuid::new_v4(),
        project_id: project_b,
        kind: MemoryKind::Infra,
        title: "B".into(),
        body: "B body".into(),
        source_user_id: None,
        source_agent_run_id: None,
        created_at: Utc::now(),
    };

    insert_memory(&conn, &mem_a);
    insert_memory(&conn, &mem_b);

    let filter = MemoryFilter {
        project_id: Some(project_a),
        kind: None,
        limit: None,
    };
    let results = store.list_memories(filter).await?;
    assert_eq!(results.len(), 1);
    assert_eq!(results[0].id, mem_a.id);
    Ok(())
}

#[tokio::test]
async fn test_list_memories_respects_limit() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let conn = store.pool.get()?;

    let project = Uuid::new_v4();

    for i in 0..5 {
        let mem = AgentMemory {
            id: Uuid::new_v4(),
            project_id: project,
            kind: MemoryKind::Project,
            title: format!("Mem {}", i),
            body: "Body".into(),
            source_user_id: None,
            source_agent_run_id: None,
            created_at: Utc::now(),
        };
        insert_memory(&conn, &mem);
    }

    let filter = MemoryFilter {
        project_id: Some(project),
        kind: None,
        limit: Some(3),
    };
    let results = store.list_memories(filter).await?;
    assert_eq!(results.len(), 3);
    Ok(())
}

#[tokio::test]
async fn test_list_memories_returns_empty_when_no_match() -> Result<()> {
    let (store, _container) = setup_config_store().await?;
    let filter = MemoryFilter {
        project_id: Some(Uuid::new_v4()),
        kind: Some(MemoryKind::Feedback),
        limit: None,
    };
    let results = store.list_memories(filter).await?;
    assert!(results.is_empty());
    Ok(())
}