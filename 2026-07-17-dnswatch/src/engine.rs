use anyhow::{Context, Result};
use std::collections::HashMap;
use std::net::IpAddr;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use tokio::signal;
use tokio::sync::{mpsc, Mutex, Notify};
use tokio::task::JoinHandle;
use tokio::time::{sleep, Instant};

use crate::app_state::AppState;
use crate::metrics::MetricsCollector;
use crate::probe::{Probe, ProbeOpts, ProbeType};

/// Command that can be sent to the engine.
#[derive(Debug)]
pub enum AppCommand {
    /// Gracefully shut down the engine.
    Shutdown,
    /// Reload configuration from the given path.
    Reload(PathBuf),
}

/// The core engine that coordinates probing, state updates, and shutdown.
pub struct Engine {
    /// Shared application state.
    pub state: Arc<Mutex<AppState>>,
    /// Channel for sending commands to the engine.
    cmd_tx: mpsc::Sender<AppCommand>,
    /// Receiver side of the command channel.
    cmd_rx: Mutex<mpsc::Receiver<AppCommand>>,
    /// Handle for the background task that runs the engine loop.
    handle: Option<JoinHandle<()>>,
}

impl Engine {
    /// Create a new engine instance.
    pub fn new(state: Arc<Mutex<AppState>>) -> Self {
        let (tx, rx) = mpsc::channel(32);
        Engine {
            state,
            cmd_tx: tx,
            cmd_rx: Mutex::new(rx),
            handle: None,
        }
    }

    /// Start the engine's background loop.
    pub fn start(&mut self) {
        let mut cmd_rx = self.cmd_rx.lock().await;
        let state = Arc::clone(&self.state);
        let mut cmd_rx = cmd_rx.clone();
        self.handle = Some(tokio::spawn(async move {
            loop {
                tokio::select! {
                    Some(cmd) = cmd_rx.recv() => match cmd {
                        AppCommand::Shutdown => break,
                        AppCommand::Reload(_path) => {
                            // In a real implementation we would reload the config here.
                        }
                    },
                    _ = sleep(Duration::from_secs(1)) => {
                        // Periodic work such as launching probes could be placed here.
                        let _ = state.lock().await; // placeholder to avoid unused warnings
                    }
                }
            }
        }));
    }

    /// Send a command to the engine.
    pub async fn send_command(&self, cmd: AppCommand) -> Result<()> {
        self.cmd_tx
            .send(cmd)
            .await
            .context("failed to send command to engine")
    }

    /// Wait for the engine to finish.
    pub async fn wait(self) -> Result<()> {
        if let Some(handle) = self.handle {
            handle.await.context("engine task panicked")?;
        }
        Ok(())
    }
}
