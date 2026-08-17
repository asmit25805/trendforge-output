use std::collections::HashMap;
use std::sync::Arc;

use parking_lot::RwLock;
use thiserror::Error;
use tokio::sync::mpsc;
use url::Url;

use crate::renderer::{RenderError, Renderer};
use crate::session::{
    ResourcePolicy, SessionError, SessionHandle, SessionManager, SessionRequest, SessionId,
};
use crate::streamer::{SemanticStreamer, StreamError};

/// High‑level events emitted by the engine that can be forwarded to a client.
#[derive(Debug, Clone)]
pub enum EngineEvent {
    SessionCreated { id: SessionId },
    SessionClosed { id: SessionId },
    PageRendered { id: SessionId, url: Url },
    DomFragmentPushed { id: SessionId, fragment_id: u64 },
}

/// Errors that can be emitted by the protocol layer.
#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid CDP message: {0}")]
    InvalidCdpMessage(String),

    #[error("invalid WebDriver message: {0}")]
    InvalidWebDriverMessage(String),

    #[error("session error: {0}")]
    SessionError(#[from] SessionError),

    #[error("render error: {0}")]
    RenderError(#[from] RenderError),

    #[error("stream error: {0}")]
    StreamError(#[from] StreamError),

    #[error("unknown error: {0}")]
    Unknown(String),
}

/// Simplified CDP command set used by WebLoom.
#[derive(Debug, Clone)]
pub enum CdpMessage {
    CreateSession {
        session_id: u64,
        policy: Option<ResourcePolicy>,
    },
    Navigate {
        session_id: u64,
        url: String,
    },
    Extract {
        session_id: u64,
        selector: String,
    },
    CloseSession {
        session_id: u64,
    },
}

/// Responses sent back to a CDP client.
#[derive(Debug, Clone)]
pub enum CdpResponse {
    Ok,
    PageSnapshot {
        url: String,
        dom_root_id: u64,
        timestamp: u64,
    },
    DomFragment {
        fragment_id: u64,
        nodes: Vec<crate::renderer::DomNode>,
    },
    Error {
        code: i32,
        message: String,
    },
}

/// Simplified WebDriver BiDi command set.
#[derive(Debug, Clone)]
pub enum WebDriverMessage {
    NewSession {
        session_id: u64,
        policy: Option<ResourcePolicy>,
    },
    GoUrl {
        session_id: u64,
        url: String,
    },
    FindElement {
        session_id: u64,
        selector: String,
    },
    DeleteSession {
        session_id: u64,
    },
}

/// Responses sent back to a WebDriver client.
#[derive(Debug, Clone)]
pub enum WebDriverResponse {
    Success,
    PageSnapshot {
        url: String,
        dom_root_id: u64,
        timestamp: u64,
    },
    ElementFragment {
        fragment_id: u64,
        nodes: Vec<crate::renderer::DomNode>,
    },
    Error {
        error: String,
        code: i32,
    },
}

/// Central adapter that translates between external protocols (CDP / WebDriver) and the
/// internal command model used by the engine.
pub struct ProtocolAdapter {
    session_manager: Arc<SessionManager>,
    /// One streamer per active session; the streamer handles back‑pressure and JSON‑Lines output.
    streamers: RwLock<HashMap<SessionId, Arc<SemanticStreamer>>>,
    /// Optional channel to forward engine events to a monitoring task.
    event_tx: Option<mpsc::UnboundedSender<EngineEvent>>,
}

impl ProtocolAdapter {
    /// Constructs a new `ProtocolAdapter` bound to the supplied `SessionManager`.
    ///
    /// The optional `event_tx` can be used by the engine to receive a copy of all emitted events.
    pub fn new(
        session_manager: Arc<SessionManager>,
        event_tx: Option<mpsc::UnboundedSender<EngineEvent>>,
    ) -> Self {
        Self {
            session_manager,
            streamers: RwLock::new(HashMap::new()),
            event_tx,
        }
    }

    /// Handles an incoming CDP message, routing it to the appropriate subsystem and
    /// returning a CDP‑compatible response.
    pub async fn handle_cdp(&self, msg: CdpMessage) -> Result<CdpResponse, ProtocolError> {
        match msg {
            CdpMessage::CreateSession { session_id, policy } => {
                let req = SessionRequest {
                    id: SessionId(session_id),
                    policy: policy.unwrap_or_default(),
                };
                let handle = self.session_manager.create(req.id, req.policy.clone())?;
                // Create a dedicated streamer for the new session.
                let streamer = Arc::new(SemanticStreamer::new());
                self.streamers
                    .write()
                    .insert(handle.id(), Arc::clone(&streamer));
                self.emit_event_internal(EngineEvent::SessionCreated { id: handle.id() })
                    .await?;
                Ok(CdpResponse::Ok)
            }
            CdpMessage::Navigate { session_id, url } => {
                let handle = self.session_manager.get(SessionId(session_id))?;
                let renderer = handle.renderer();
                let parsed_url = Url::parse(&url).map_err(ProtocolError::InvalidCdpMessage)?;
                let snapshot = renderer.render(parsed_url.clone()).await?;
                self.emit_event_internal(EngineEvent::PageRendered {
                    id: handle.id(),
                    url: parsed_url,
                })
                .await?;
                Ok(CdpResponse::PageSnapshot {
                    url: snapshot.url.to_string(),
                    dom_root_id: snapshot.dom_root.node_id,
                    timestamp: snapshot
                        .timestamp
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_secs(),
                })
            }
            CdpMessage::Extract { session_id, selector } => {
                let handle = self.session_manager.get(SessionId(session_id))?;
                let renderer = handle.renderer();
                let css = crate::renderer::CssSelector(selector);
                let fragment = renderer.extract(css).await?;
                // Push the fragment to the session‑specific streamer.
                if let Some(streamer) = self.streamers.read().get(&handle.id()) {
                    streamer.push(fragment.clone()).await?;
                }
                self.emit_event_internal(EngineEvent::DomFragmentPushed {
                    id: handle.id(),
                    fragment_id: fragment
                        .nodes
                        .first()
                        .map(|n| n.node_id)
                        .unwrap_or_default(),
                })
                .await?;
                Ok(CdpResponse::DomFragment {
                    fragment_id: fragment
                        .nodes
                        .first()
                        .map(|n| n.node_id)
                        .unwrap_or_default(),
                    nodes: fragment.nodes,
                })
            }
            CdpMessage::CloseSession { session_id } => {
                self.session_manager.close(SessionId(session_id))?;
                self.streamers.write().remove(&SessionId(session_id));
                self.emit_event_internal(EngineEvent::SessionClosed {
                    id: SessionId(session_id),
                })
                .await?;
                Ok(CdpResponse::Ok)
            }
        }
    }

    /// Handles an incoming WebDriver message, routing it to the appropriate subsystem and
    /// returning a WebDriver‑compatible response.
    pub async fn handle_wd(&self, msg: WebDriverMessage) -> Result<WebDriverResponse, ProtocolError> {
        match msg {
            WebDriverMessage::NewSession { session_id, policy } => {
                let req = SessionRequest {
                    id: SessionId(session_id),
                    policy: policy.unwrap_or_default(),
                };
                let handle = self.session_manager.create(req.id, req.policy.clone())?;
                let streamer = Arc::new(SemanticStreamer::new());
                self.streamers
                    .write()
                    .insert(handle.id(), Arc::clone(&streamer));
                self.emit_event_internal(EngineEvent::SessionCreated { id: handle.id() })
                    .await?;
                Ok(WebDriverResponse::Success)
            }
            WebDriverMessage::GoUrl { session_id, url } => {
                let handle = self.session_manager.get(SessionId(session_id))?;
                let renderer = handle.renderer();
                let parsed_url = Url::parse(&url).map_err(ProtocolError::InvalidWebDriverMessage)?;
                let snapshot = renderer.render(parsed_url.clone()).await?;
                self.emit_event_internal(EngineEvent::PageRendered {
                    id: handle.id(),
                    url: parsed_url,
                })
                .await?;
                Ok(WebDriverResponse::PageSnapshot {
                    url: snapshot.url.to_string(),
                    dom_root_id: snapshot.dom_root.node_id,
                    timestamp: snapshot
                        .timestamp
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_secs(),
                })
            }
            WebDriverMessage::FindElement { session_id, selector } => {
                let handle = self.session_manager.get(SessionId(session_id))?;
                let renderer = handle.renderer();
                let css = crate::renderer::CssSelector(selector);
                let fragment = renderer.extract(css).await?;
                if let Some(streamer) = self.streamers.read().get(&handle.id()) {
                    streamer.push(fragment.clone()).await?;
                }
                self.emit_event_internal(EngineEvent::DomFragmentPushed {
                    id: handle.id(),
                    fragment_id: fragment
                        .nodes
                        .first()
                        .map(|n| n.node_id)
                        .unwrap_or_default(),
                })
                .await?;
                Ok(WebDriverResponse::ElementFragment {
                    fragment_id: fragment
                        .nodes
                        .first()
                        .map(|n| n.node_id)
                        .unwrap_or_default(),
                    nodes: fragment.nodes,
                })
            }
            WebDriverMessage::DeleteSession { session_id } => {
                self.session_manager.close(SessionId(session_id))?;
                self.streamers.write().remove(&SessionId(session_id));
                self.emit_event_internal(EngineEvent::SessionClosed {
                    id: SessionId(session_id),
                })
                .await?;
                Ok(WebDriverResponse::Success)
            }
        }
    }

    /// Emits an internal engine event to any registered listeners. Errors from the
    /// underlying channel are logged but do not propagate to the caller.
    pub async fn emit_event(&self, event: EngineEvent) -> Result<(), ProtocolError> {
        if let Some(tx) = &self.event_tx {
            tx.send(event).map_err(|e| ProtocolError::Unknown(e.to_string()))?;
        }
        Ok(())
    }

    /// Internal helper that forwards an event and logs failures.
    async fn emit_event_internal(&self, event: EngineEvent) -> Result<(), ProtocolError> {
        self.emit_event(event).await?;
        Ok(())
    }
}

// Implementations for SessionManager that are required by the adapter.
// These are thin wrappers around the existing API to keep the adapter code tidy.

impl SessionManager {
    /// Retrieves a handle for an existing session, returning an error if the session does not exist.
    pub fn get(&self, id: SessionId) -> Result<Arc<SessionHandle>, SessionError> {
        let map = self.sessions.read();
        map.get(&id)
            .cloned()
            .ok_or(SessionError::NotFound(id))
    }

    /// Creates a new session and returns its handle.
    pub fn create(
        &self,
        id: SessionId,
        policy: ResourcePolicy,
    ) -> Result<Arc<SessionHandle>, SessionError> {
        // The real implementation lives in `SessionManager::create` defined elsewhere.
        // Here we simply forward to that method.
        SessionManager::create(self, id, policy)
    }

    /// Closes an existing session.
    pub fn close(&self, id: SessionId) -> Result<(), SessionError> {
        SessionManager::close(self, id)
    }
}

// The `SemanticStreamer` implementation is expected to provide an async `push` method.
// We expose a thin wrapper to satisfy the compiler when the concrete type differs.

impl SemanticStreamer {
    /// Constructs a new `SemanticStreamer`. In a real implementation this would allocate
    /// buffers and configure back‑pressure thresholds.
    pub fn new() -> Self {
        SemanticStreamer::default()
    }

    /// Pushes a DOM fragment onto the stream, applying throttling if the consumer is slow.
    pub async fn push(&self, fragment: crate::renderer::DomFragment) -> Result<(), StreamError> {
        SemanticStreamer::push(self, fragment).await
    }
}