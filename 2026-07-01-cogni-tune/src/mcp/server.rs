use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use hyper::body::to_bytes;
use hyper::header::AUTHORIZATION;
use hyper::{Body, Request, Response, StatusCode};
use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tokio::time::timeout;
use uuid::Uuid;

/// Represents a JSON‑RPC method handler.
pub type RpcHandler =
    Box<dyn Fn(Value) -> Pin<Box<dyn Future<Output = Result<Value, RpcError>> + Send>> + Send + Sync>;

#[derive(Debug, thiserror::Error)]
pub enum RpcError {
    #[error("method not found")]
    MethodNotFound,
    #[error("invalid params: {0}")]
    InvalidParams(String),
    #[error("internal error: {0}")]
    Internal(String),
}

/// The MCP server exposing JSON‑RPC over HTTP.
pub struct McpServer {
    address: String,
    methods: Arc<Mutex<HashMap<String, RpcHandler>>>,
}

impl McpServer {
    pub fn new(address: impl Into<String>) -> Self {
        Self {
            address: address.into(),
            methods: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Register a new RPC method.
    pub async fn register_method<F, Fut>(&self, name: impl Into<String>, handler: F)
    where
        F: Fn(Value) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Value, RpcError>> + Send + 'static,
    {
        let mut map = self.methods.lock().await;
        map.insert(
            name.into(),
            Box::new(move |params| Box::pin(handler(params))),
        );
    }

    /// Run the server (simplified for illustration).
    pub async fn run(self) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let make_svc = hyper::service::make_service_fn(|_conn| {
            let methods = self.methods.clone();
            async move {
                Ok::<_, hyper::Error>(hyper::service::service_fn(move |req| {
                    let methods = methods.clone();
                    async move { handle_request(req, methods).await }
                }))
            }
        });

        let addr = self.address.parse()?;
        let server = hyper::Server::bind(&addr).serve(make_svc);
        info!("MCP server listening on {}", self.address);
        server.await?;
        Ok(())
    }
}

async fn handle_request(
    req: Request<Body>,
    methods: Arc<Mutex<HashMap<String, RpcHandler>>>,
) -> Result<Response<Body>, hyper::Error> {
    // Only POST is allowed for JSON‑RPC.
    if req.method() != hyper::Method::POST {
        return Ok(Response::builder()
            .status(StatusCode::METHOD_NOT_ALLOWED)
            .body(Body::from("only POST allowed"))?);
    }

    let bytes = to_bytes(req.into_body()).await?;
    let payload: Value = match serde_json::from_slice(&bytes) {
        Ok(v) => v,
        Err(e) => {
            error!("failed to parse JSON‑RPC payload: {}", e);
            return Ok(Response::builder()
                .status(StatusCode::BAD_REQUEST)
                .body(Body::from("invalid json"))?);
        }
    };

    let method = payload.get("method").and_then(|m| m.as_str());
    let params = payload.get("params").cloned().unwrap_or_else(|| json!({}));
    let id = payload.get("id").cloned();

    let response = match method {
        Some(name) => {
            let map = methods.lock().await;
            match map.get(name) {
                Some(handler) => match handler(params).await {
                    Ok(result) => json!({"jsonrpc": "2.0", "result": result, "id": id}),
                    Err(err) => json!({"jsonrpc": "2.0", "error": {"code": -32603, "message": err.to_string()}, "id": id}),
                },
                None => json!({"jsonrpc": "2.0", "error": {"code": -32601, "message": "Method not found"}, "id": id}),
            }
        }
        None => json!({"jsonrpc": "2.0", "error": {"code": -32600, "message": "Invalid Request"}, "id": id}),
    };

    let body = Body::from(serde_json::to_string(&response).unwrap());
    Ok(Response::new(body))
}

/// Helper to register a method on a server instance.
pub async fn rpc_method<F, Fut>(server: &McpServer, name: impl Into<String>, handler: F)
where
    F: Fn(Value) -> Fut + Send + Sync + 'static,
    Fut: Future<Output = Result<Value, RpcError>> + Send + 'static,
{
    server.register_method(name, handler).await;
}

// Export the public symbols.
pub use McpServer;
pub use rpc_method;
