use std::path::PathBuf;
use std::time::Duration;

use log::{error, info, warn};
use tokio::time::sleep;
use uuid::Uuid;

use gitmind::engine::{Engine, EngineConfig, EngineError, ApplyResult};
use gitmind::store::{Document, DocumentMeta, DocumentChange, KnowledgeStore};
use gitmind::mcp::{McpServer, AgentAction, ActionResult, McpError};
use gitmind::collab::{CollaborationSession, ClientHandle, ClientId, CrdtOp};

/// Number of times a transient error is retried before giving up.
const MAX_RETRIES: usize = 3;

/// Back‑off base duration for retries.
const BACKOFF_BASE: Duration = Duration::from_millis(200);

/// Simple helper that performs exponential back‑off.
async fn backoff(attempt: usize) {
    let delay = BACKOFF_BASE * 2u32.pow(attempt as u32);
    sleep(delay).await;
}

/// Build a minimal `EngineConfig` for the example.
///
/// The configuration points to a temporary directory that will be created on
/// demand. All other fields use their default values.
fn build_config(repo_path: PathBuf) -> EngineConfig {
    EngineConfig {
        repo_path,
        ..Default::default()
    }
}

/// Create a fresh markdown document that will be stored in the repository.
fn make_initial_document() -> Document {
    Document {
        id: String::new(),
        path: PathBuf::from("examples/hello.md"),
        content: "# Hello, gitmind!\n\nThis document is created by the basic example.\n".into(),
        metadata: DocumentMeta::default(),
    }
}

/// Wrap a `Document` in a `DocumentChange` suitable for `Engine::apply_change`.
fn make_change(doc: Document) -> DocumentChange {
    DocumentChange::new(doc)
}

/// Build an `AgentAction` that carries the document change to the MCP server.
fn make_agent_action(change: DocumentChange) -> AgentAction {
    AgentAction {
        // The concrete fields depend on the protobuf definition; we only need
        // the change for this example.
        change: Some(change),
        // Other optional fields are left as `None`.
        ..Default::default()
    }
}

/// Attempt to apply an `AgentAction` via the MCP server, retrying on transient
/// errors. Returns the final `ActionResult` on success.
async fn apply_action_with_retries(
    server: &McpServer,
    action: AgentAction,
) -> Result<ActionResult, McpError> {
    let mut attempt = 0;
    loop {
        match server.apply_agent_action(action.clone()).await {
            Ok(res) => return Ok(res),
            Err(err) => {
                // Distinguish transient from fatal errors based on the error
                // variant. `McpError::Transient` is assumed to exist.
                if let McpError::Transient(_) = err {
                    if attempt >= MAX_RETRIES {
                        error!("Maximum retries reached for transient error");
                        return Err(err);
                    }
                    warn!(
                        "Transient MCP error (attempt {}): {} – retrying",
                        attempt + 1,
                        err
                    );
                    backoff(attempt).await;
                    attempt += 1;
                    continue;
                } else {
                    // Fatal error – propagate immediately.
                    error!("Fatal MCP error: {}", err);
                    return Err(err);
                }
            }
        }
    }
}

/// Retrieve the latest version of a document from the knowledge store and
/// return its content together with the token usage reported by the apply
/// operation.
async fn fetch_document_and_report(
    store: &KnowledgeStore,
    path: &PathBuf,
    apply_result: &ApplyResult,
) -> Result<(), EngineError> {
    let doc = store.read_doc(path)?;
    println!("--- Document Version ---");
    println!("{}", doc.content);
    println!("--- Token Usage ---");
    println!("Tokens consumed: {}", apply_result.token_usage);
    Ok(())
}

/// Entry point for the example program.
///
/// The function performs the following steps:
///
/// 1. Initialise logging.
/// 2. Create a temporary repository and start the engine.
/// 3. Load an initial document into the repository.
/// 4. Start an MCP server bound to the engine.
/// 5. Send an `AgentAction` that modifies the document.
/// 6. Print the updated document and token usage.
///
/// All operations are performed with robust error handling; any failure is
/// logged and the program exits with a non‑zero status.
#[tokio::main]
async fn main() {
    // Initialise a simple logger that prints to stderr.
    env_logger::init();

    // -------------------------------------------------------------------------
    // 1. Engine initialisation
    // -------------------------------------------------------------------------
    let repo_path = std::env::temp_dir().join(format!("gitmind_example_{}", Uuid::new_v4()));
    let config = build_config(repo_path.clone());

    let engine = match Engine::initialize(config).await {
        Ok(e) => {
            info!("Engine initialised with repository at {}", repo_path.display());
            e
        }
        Err(e) => {
            error!("Failed to initialise engine: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 2. Store a baseline document
    // -------------------------------------------------------------------------
    let initial_doc = make_initial_document();
    let change = make_change(initial_doc.clone());

    // Directly use the engine to write the document; this also updates the CRDT
    // session and backlink graph.
    let apply_result = match engine.apply_change(change.clone()).await {
        Ok(res) => {
            info!("Initial document stored, commit hash: {}", res.commit_hash);
            res
        }
        Err(e) => {
            error!("Failed to store initial document: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 3. Start the MCP server
    // -------------------------------------------------------------------------
    let mcp_server = match McpServer::new(engine.clone()).await {
        Ok(s) => {
            info!("MCP server started");
            s
        }
        Err(e) => {
            error!("Failed to start MCP server: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 4. Create an AgentAction that appends a paragraph to the document
    // -------------------------------------------------------------------------
    let mut updated_doc = initial_doc.clone();
    updated_doc.content.push_str("\nAdditional content added by the agent.\n");
    let updated_change = make_change(updated_doc.clone());
    let agent_action = make_agent_action(updated_change);

    // -------------------------------------------------------------------------
    // 5. Apply the action via the MCP server with retry logic
    // -------------------------------------------------------------------------
    let action_result = match apply_action_with_retries(&mcp_server, agent_action).await {
        Ok(res) => {
            info!("Agent action applied successfully");
            res
        }
        Err(e) => {
            error!("Failed to apply agent action: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 6. Fetch the updated document and report token usage
    // -------------------------------------------------------------------------
    if let Err(e) = fetch_document_and_report(&engine.store, &updated_doc.path, &apply_result).await
    {
        error!("Failed to fetch updated document: {}", e);
        std::process::exit(1);
    }

    // -------------------------------------------------------------------------
    // 7. Graceful shutdown
    // -------------------------------------------------------------------------
    if let Err(e) = engine.shutdown().await {
        warn!("Engine shutdown reported an error: {}", e);
    } else {
        info!("Engine shut down cleanly");
    }
}