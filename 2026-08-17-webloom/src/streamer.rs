use std::sync::Arc;

use parking_lot::RwLock;
use serde::Serialize;
use thiserror::Error;
use tokio::io::AsyncWriteExt;
use tokio::sync::mpsc::{self, Receiver, Sender};
use tokio::task::JoinHandle;

use crate::renderer::DomFragment;

/// Errors that can be emitted by the streaming subsystem.
#[derive(Debug, Error)]
pub enum StreamError {
    #[error("stream has been closed")]
    Closed,
    #[error("failed to join background task: {0}")]
    TaskJoin(String),
    #[error("callback error: {0}")]
    Callback(String),
    #[error("serialization error: {0}")]
    Serialization(String),
}

/// A streamer that serializes `DomFragment`s into a compact JSON‑Lines stream
/// and applies back‑pressure when the consumer is slow.
///
/// The streamer owns a bounded channel; `push` enqueues fragments while the
/// background task drains the channel, serializes each fragment to JSON and
/// writes it to stdout (or any other sink you replace in the background task).
/// A user‑provided callback can be registered to receive each fragment for
/// custom processing (e.g., logging, metrics, or forwarding to another service).
pub struct SemanticStreamer {
    /// Sender side of the bounded channel used for back‑pressure.
    sender: Sender<DomFragment>,
    /// Shared, mutable callback invoked for every fragment that passes through
    /// the streamer.
    callback: Arc<RwLock<Box<dyn Fn(&DomFragment) + Send + Sync>>>,
    /// Background task that consumes fragments, serializes them and writes the
    /// resulting JSON line to the output sink.
    background_handle: JoinHandle<()>,
}

impl SemanticStreamer {
    /// Creates a new `SemanticStreamer` with the given channel capacity.
    ///
    /// The capacity determines how many fragments can be queued before
    /// `push` starts to await space, providing natural throttling.
    pub fn new(capacity: usize) -> Self {
        let (tx, rx) = mpsc::channel::<DomFragment>(capacity);
        let callback: Arc<RwLock<Box<dyn Fn(&DomFragment) + Send + Sync>>> =
            Arc::new(RwLock::new(Box::new(|_| {})));

        let bg_callback = Arc::clone(&callback);
        let background_handle = tokio::spawn(async move {
            Self::run_background(rx, bg_callback).await;
        });

        Self {
            sender: tx,
            callback,
            background_handle,
        }
    }

    /// Internal background loop that receives fragments, serializes them to a
    /// JSON line, writes the line to stdout, and finally invokes the registered
    /// callback.
    async fn run_background(mut rx: Receiver<DomFragment>, callback: Arc<RwLock<Box<dyn Fn(&DomFragment) + Send + Sync>>>) {
        // Use stdout as the default sink; this can be swapped out by
        // modifying the implementation without affecting the public API.
        let mut stdout = tokio::io::stdout();

        while let Some(fragment) = rx.recv().await {
            // Serialize the fragment to a compact JSON string.
            match serde_json::to_string(&fragment) {
                Ok(json) => {
                    // Write the JSON line followed by a newline.
                    let _ = stdout.write_all(json.as_bytes()).await;
                    let _ = stdout.write_all(b"\n").await;
                }
                Err(_) => {
                    // Serialization failure is non‑recoverable for this fragment;
                    // we simply continue with the next one.
                }
            }

            // Invoke the user‑provided callback. Any panic inside the callback
            // is caught to avoid crashing the background task.
            let cb = callback.read();
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| (cb)(&fragment)));
        }
    }

    /// Enqueues a `DomFragment` for transmission. The method awaits until
    /// space becomes available in the bounded channel, applying natural
    /// throttling when the consumer is slower than the producer.
    ///
    /// Returns `Err(StreamError::Closed)` if the streamer has been closed.
    pub async fn push(&self, fragment: DomFragment) -> Result<(), StreamError> {
        self.sender
            .send(fragment)
            .await
            .map_err(|_| StreamError::Closed)
    }

    /// Closes the streamer, signalling the background task to finish after all
    /// queued fragments have been processed. The method awaits the termination
    /// of the background task and returns any error that occurred while joining.
    pub async fn close(&self) -> Result<(), StreamError> {
        // Closing the sender will cause the receiver loop to exit after draining.
        self.sender.clone().close_channel();

        self.background_handle
            .await
            .map_err(|e| StreamError::TaskJoin(e.to_string()))?;
        Ok(())
    }

    /// Registers a user‑provided callback that will be invoked for each fragment
    /// after it has been serialized and written to the output sink.
    ///
    /// The callback replaces any previously registered callback.
    pub fn register_callback(&self, cb: Box<dyn Fn(&DomFragment) + Send + Sync>) {
        let mut lock = self.callback.write();
        *lock = cb;
    }
}

// Unit tests for the streamer implementation.
#[cfg(test)]
mod tests {
    use super::*;
    use crate::renderer::DomNode;
    use crate::renderer::NodeType;
    use std::collections::HashMap;
    use tokio::sync::oneshot;

    fn make_fragment() -> DomFragment {
        let mut attrs = HashMap::new();
        attrs.insert("class".into(), "test".into());
        let node = DomNode {
            node_id: 1,
            node_type: NodeType::Element,
            tag_name: Some("div".into()),
            attributes: attrs,
            children: vec![],
            text_content: None,
        };
        DomFragment { nodes: vec![node] }
    }

    #[tokio::test]
    async fn push_and_close_successful() {
        let streamer = SemanticStreamer::new(2);
        let frag = make_fragment();
        streamer.push(frag.clone()).await.expect("push should succeed");
        streamer.close().await.expect("close should succeed");
    }

    #[tokio::test]
    async fn backpressure_applies_when_full() {
        let streamer = SemanticStreamer::new(1);
        let frag1 = make_fragment();
        let frag2 = make_fragment();

        // First push should succeed immediately.
        streamer.push(frag1).await.expect("first push");

        // Second push will await until the background task consumes the first.
        // Use a timeout to ensure it does not deadlock.
        let (tx, rx) = oneshot::channel();
        tokio::spawn({
            let s = streamer.clone();
            async move {
                s.push(frag2).await.expect("second push");
                let _ = tx.send(());
            }
        });
        // Give the background task a moment to process.
        tokio::time::sleep(tokio::time::Duration::from_millis(10)).await;
        // Now close to unblock the waiting push.
        streamer.close().await.expect("close");
        rx.await.expect("push should complete");
    }

    #[tokio::test]
    async fn register_callback_is_invoked() {
        let streamer = SemanticStreamer::new(2);
        let (tx, rx) = oneshot::channel();

        streamer.register_callback(Box::new(move |_frag| {
            let _ = tx.send(());
        }));

        streamer.push(make_fragment()).await.expect("push");
        // Wait for the callback to fire.
        rx.await.expect("callback invoked");
        streamer.close().await.expect("close");
    }

    #[tokio::test]
    async fn push_fails_after_close() {
        let streamer = SemanticStreamer::new(2);
        streamer.close().await.expect("close");
        let result = streamer.push(make_fragment()).await;
        assert!(matches!(result, Err(StreamError::Closed)));
    }

    #[tokio::test]
    async fn multiple_pushes_respect_capacity() {
        let capacity = 3;
        let streamer = SemanticStreamer::new(capacity);
        for _ in 0..capacity {
            streamer
                .push(make_fragment())
                .await
                .expect("push within capacity");
        }
        // The next push will block until at least one fragment is processed.
        let (tx, rx) = oneshot::channel();
        tokio::spawn({
            let s = streamer.clone();
            async move {
                s.push(make_fragment()).await.expect("blocked push");
                let _ = tx.send(());
            }
        });
        // Allow background task to consume one fragment.
        tokio::time::sleep(tokio::time::Duration::from_millis(20)).await;
        streamer.close().await.expect("close");
        rx.await.expect("blocked push completed");
    }
}