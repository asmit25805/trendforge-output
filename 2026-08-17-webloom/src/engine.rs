use std::net::SocketAddr;
use std::sync::Arc;
use std::time::Duration;

use parking_lot::RwLock;
use tokio::net::{TcpListener, TcpStream};
use tokio::sync::{oneshot, Notify};
use tokio::task::JoinHandle;
use tokio::time;

use thiserror::Error;
use log::{debug, error, info, warn};

use crate::session::{
    SessionManager, SessionRequest, SessionHandle, SessionError,
};
use crate::protocol::ProtocolAdapter;
use crate::renderer::Renderer;
use crate::streamer::SemanticStreamer;

/// Verbosity levels for internal diagnostics.
#[derive(Debug, Clone, Copy)]
pub enum LogLevel {
    Debug,
    Info,
    Warn,
    Error,
}

impl LogLevel {
    fn as_str(self) -> &'static str {
        match self {
            LogLevel::Debug => "debug",
            LogLevel::Info => "info",
            LogLevel::Warn => "warn",
            LogLevel::Error => "error",
        }
    }
}

/// Configuration supplied to the engine at start‑up.
#[derive(Debug, Clone)]
pub struct EngineConfig {
    /// Address on which the engine listens for CDP/WebDriver connections.
    pub listen_addr: SocketAddr,
    /// Default resource limits applied when a session does not provide its own policy.
    pub default_policy: crate::session::ResourcePolicy,
    /// Desired log level.
    pub log_level: LogLevel,
}

/// Top‑level errors emitted by the engine.
#[derive(Debug, Error)]
pub enum EngineError {
    #[error("failed to bind listening socket: {0}")]
    BindError(String),

    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    #[error("session error: {0}")]
    SessionError(#[from] SessionError),

    #[error("protocol error: {0}")]
    ProtocolError(#[from] crate::protocol::ProtocolError),

    #[error("engine shutdown failed: {0}")]
    ShutdownError(String),

    #[error("fatal error: {0}")]
    Fatal(String),
}

/// Orchestrates the lifecycle of a headless browser instance, handling I/O,
/// event loops, and graceful shutdown.
pub struct BrowserEngine {
    listener: TcpListener,
    session_manager: Arc<SessionManager>,
    shutdown_tx: Option<oneshot::Sender<()>>,
    /// Notifies when all background tasks have terminated.
    termination_notify: Arc<Notify>,
    /// Handles for background tasks (accept loop, per‑connection handlers).
    background_tasks: RwLock<Vec<JoinHandle<()>>>,
}

impl BrowserEngine {
    /// Boots the engine with the supplied configuration and returns a handle
    /// that can be used to spawn sessions. The engine starts listening for
    /// incoming CDP/WebDriver connections in the background.
    pub async fn run(config: EngineConfig) -> Result<Self, EngineError> {
        // Initialise logger according to the requested level.
        std::env::set_var(
            "RUST_LOG",
            format!("webloom={}", config.log_level.as_str()),
        );
        env_logger::init();

        // Bind the TCP listener; fatal if it fails.
        let listener = TcpListener::bind(config.listen_addr)
            .await
            .map_err(|e| EngineError::BindError(e.to_string()))?;

        info!("engine listening on {}", config.listen_addr);

        // Create the session manager with the default policy.
        let session_manager = Arc::new(SessionManager::new(config.default_policy));

        // Channel used to signal shutdown.
        let (shutdown_tx, shutdown_rx) = oneshot::channel();

        // Notification used to await termination of all spawned tasks.
        let termination_notify = Arc::new(Notify::new());

        // Spawn the accept loop.
        let accept_handle = {
            let listener = listener.clone();
            let session_manager = Arc::clone(&session_manager);
            let termination_notify = Arc::clone(&termination_notify);
            tokio::spawn(async move {
                Self::accept_loop(listener, session_manager, shutdown_rx, termination_notify).await;
            })
        };

        // Store the task handle.
        let background_tasks = RwLock::new(vec![accept_handle]);

        Ok(Self {
            listener,
            session_manager,
            shutdown_tx: Some(shutdown_tx),
            termination_notify,
            background_tasks,
        })
    }

    /// Initiates an orderly shutdown, waiting for all active sessions to finish.
    pub async fn shutdown(&self) -> Result<(), EngineError> {
        // Send the shutdown signal; ignore if already sent.
        if let Some(tx) = &self.shutdown_tx {
            let _ = tx.send(());
        }

        // Wait for background tasks to finish.
        self.termination_notify.notified().await;

        // Join all task handles to surface any panics.
        let mut tasks = self.background_tasks.write();
        for handle in tasks.drain(..) {
            if let Err(e) = handle.await {
                error!("background task panicked: {:?}", e);
                return Err(EngineError::ShutdownError(
                    "background task panicked".into(),
                ));
            }
        }

        info!("engine shutdown complete");
        Ok(())
    }

    /// Creates a new isolated browsing session.
    ///
    /// Transient errors (e.g., temporary resource exhaustion) are retried up
    /// to three times with exponential back‑off before propagating the error.
    pub async fn spawn_session(
        &self,
        req: SessionRequest,
    ) -> Result<SessionHandle, EngineError> {
        const MAX_RETRIES: usize = 3;
        let mut attempt = 0usize;
        let mut backoff = Duration::from_millis(100);

        loop {
            match self.session_manager.create(req.clone()) {
                Ok(handle) => {
                    debug!("session {} created", req.id);
                    return Ok(handle);
                }
                Err(e) => {
                    attempt += 1;
                    if attempt > MAX_RETRIES {
                        warn!("session creation failed after {} attempts: {}", attempt - 1, e);
                        return Err(EngineError::SessionError(e));
                    }
                    warn!(
                        "transient error creating session {}: {} – retry {}/{}",
                        req.id, e, attempt, MAX_RETRIES
                    );
                    time::sleep(backoff).await;
                    backoff = backoff * 2;
                }
            }
        }
    }

    /// Internal accept loop that dispatches each incoming TCP stream to the
    /// protocol adapter. The loop terminates when the shutdown signal is
    /// received.
    async fn accept_loop(
        listener: TcpListener,
        session_manager: Arc<SessionManager>,
        mut shutdown_rx: oneshot::Receiver<()>,
        termination_notify: Arc<Notify>,
    ) {
        loop {
            tokio::select! {
                accept_res = listener.accept() => {
                    match accept_res {
                        Ok((stream, addr)) => {
                            debug!("incoming connection from {}", addr);
                            let session_manager = Arc::clone(&session_manager);
                            let termination_notify = Arc::clone(&termination_notify);
                            tokio::spawn(async move {
                                if let Err(e) = Self::handle_connection(stream, session_manager).await {
                                    error!("connection handling error: {}", e);
                                }
                                // When a connection finishes, we simply drop its task.
                                // No explicit notification needed per‑connection.
                                drop(termination_notify);
                            });
                        }
                        Err(e) => {
                            error!("accept error: {}", e);
                            // Fatal accept errors cause the engine to exit.
                            std::process::exit(1);
                        }
                    }
                }
                _ = &mut shutdown_rx => {
                    info!("shutdown signal received – stopping accept loop");
                    break;
                }
            }
        }
        // Notify that the accept loop has exited.
        termination_notify.notify_waiters();
    }

    /// Handles a single TCP connection by delegating to the protocol adapter.
    async fn handle_connection(
        stream: TcpStream,
        session_manager: Arc<SessionManager>,
    ) -> Result<(), EngineError> {
        let mut adapter = ProtocolAdapter::new(session_manager);
        adapter.handle_connection(stream).await?;
        Ok(())
    }
}

// ---------------------------------------------------------------------------
// Public API re‑exports for convenience.

pub use EngineConfig;
pub use EngineError;
pub use LogLevel;
pub use BrowserEngine;