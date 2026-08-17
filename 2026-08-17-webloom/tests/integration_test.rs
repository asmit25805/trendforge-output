use std::net::SocketAddr;
use std::sync::{Arc, Mutex};

use tokio::sync::Notify;
use tokio::time::{sleep, Duration};

use crate::engine::{BrowserEngine, EngineConfig, EngineError, LogLevel};
use crate::session::{
    ResourcePolicy, SessionError, SessionHandle, SessionManager, SessionRequest, SessionId,
};
use crate::renderer::{CssSelector, DomFragment, Renderer};
use crate::protocol::{CdpMessage, CdpResponse, ProtocolError};
use crate::streamer::{SemanticStreamer, StreamError};

/// Helper to build a minimal `EngineConfig` for tests.
fn test_engine_config() -> EngineConfig {
    EngineConfig {
        listen_addr: "127.0.0.1:0".parse().expect("valid socket address"),
        default_policy: ResourcePolicy {
            max_memory: 64 * 1024 * 1024,
            max_cpu: 0.2,
            allowed_schemes: vec!["http".into(), "https".into()],
            block_third_party: true,
        },
        log_level: LogLevel::Info,
    }
}

/// Creates a fresh `BrowserEngine` and a `SessionHandle` for the given session id.
async fn setup_session(session_id: SessionId) -> Result<(BrowserEngine, SessionHandle), EngineError>
{
    let config = test_engine_config();
    let engine = BrowserEngine::new(config)?;
    let req = SessionRequest {
        session_id,
        policy: None,
    };
    let handle = engine.spawn_session(req).await?;
    Ok((engine, handle))
}

/// Captures fragments pushed through a `SemanticStreamer`.
struct CaptureCallback {
    fragments: Arc<Mutex<Vec<DomFragment>>>,
}

impl CaptureCallback {
    fn new() -> (Self, Arc<Mutex<Vec<DomFragment>>>) {
        let fragments = Arc::new(Mutex::new(Vec::new()));
        (Self { fragments: fragments.clone() }, fragments)
    }

    fn callback(&self) -> Box<dyn Fn(&DomFragment) + Send + Sync> {
        let fragments = Arc::clone(&self.fragments);
        Box::new(move |frag| {
            let mut lock = fragments.lock().unwrap();
            lock.push(frag.clone());
        })
    }
}

#[tokio::test]
async fn test_engine_spawn_session_success() -> Result<(), EngineError> {
    let config = test_engine_config();
    let engine = BrowserEngine::new(config)?;
    let req = SessionRequest {
        session_id: 1,
        policy: None,
    };
    let handle = engine.spawn_session(req).await?;
    // The handle must contain a renderer and a streamer.
    assert!(handle.renderer.is_some());
    assert!(handle.streamer.is_some());
    Ok(())
}

#[tokio::test]
async fn test_renderer_navigate_and_snapshot() -> Result<(), EngineError> {
    let (_engine, handle) = setup_session(2).await?;
    let renderer = handle
        .renderer
        .as_ref()
        .expect("renderer should be present")
        .clone();

    let url = "https://example.org".parse().expect("valid URL");
    let snapshot = renderer.render(url.clone()).await.map_err(|e| EngineError::Render(e))?;
    assert_eq!(snapshot.url, url);
    // The snapshot must contain at least the document node.
    assert_eq!(snapshot.dom_root.node_type, crate::renderer::NodeType::Document);
    Ok(())
}

#[tokio::test]
async fn test_renderer_extract_returns_dom_fragment() -> Result<(), EngineError> {
    let (_engine, handle) = setup_session(3).await?;
    let renderer = handle
        .renderer
        .as_ref()
        .expect("renderer should be present")
        .clone();

    // Render a simple page first.
    let url = "https://example.org".parse().expect("valid URL");
    renderer.render(url).await.map_err(|e| EngineError::Render(e))?;

    // Extract a selector that is guaranteed to exist (the body element).
    let selector = CssSelector("body".into());
    let fragment = renderer
        .extract(selector)
        .await
        .map_err(|e| EngineError::Render(e))?;
    assert!(!fragment.nodes.is_empty());
    // All returned nodes must be of type Element.
    for node in &fragment.nodes {
        assert_eq!(node.node_type, crate::renderer::NodeType::Element);
    }
    Ok(())
}

#[tokio::test]
async fn test_streamer_push_and_callback_invoked() -> Result<(), StreamError> {
    // Create a streamer with a small capacity.
    let streamer = SemanticStreamer::new(4);
    let (callback, captured) = CaptureCallback::new();
    streamer.register_callback(callback.callback());

    // Build a dummy fragment.
    let fragment = DomFragment {
        nodes: vec![crate::renderer::DomNode {
            node_id: 1,
            node_type: crate::renderer::NodeType::Text,
            tag_name: None,
            attributes: std::collections::HashMap::new(),
            children: Vec::new(),
            text_content: Some("hello".into()),
        }],
    };

    // Push the fragment; the background task will invoke the callback.
    streamer.push(fragment.clone())?;
    // Give the background task a moment to process.
    sleep(Duration::from_millis(50)).await;
    streamer.close()?;

    let lock = captured.lock().unwrap();
    assert_eq!(lock.len(), 1);
    assert_eq!(lock[0].nodes[0].text_content.as_deref(), Some("hello"));
    Ok(())
}

#[tokio::test]
async fn test_session_policy_update_applies_correctly() -> Result<(), SessionError> {
    let manager = Arc::new(SessionManager::new());
    let session_id: SessionId = 4;
    let initial_policy = ResourcePolicy {
        max_memory: 32 * 1024 * 1024,
        max_cpu: 0.1,
        allowed_schemes: vec!["http".into()],
        block_third_party: false,
    };
    manager.create(session_id, initial_policy.clone())?;

    // Apply a stricter policy.
    let new_policy = ResourcePolicy {
        max_memory: 16 * 1024 * 1024,
        max_cpu: 0.05,
        allowed_schemes: vec!["https".into()],
        block_third_party: true,
    };
    manager.apply_policy(session_id, new_policy.clone())?;

    // Retrieve the session and verify the policy was updated.
    let handle = manager
        .get_handle(session_id)
        .expect("session should exist after policy update");
    assert_eq!(handle.policy.max_memory, new_policy.max_memory);
    assert_eq!(handle.policy.max_cpu, new_policy.max_cpu);
    assert_eq!(handle.policy.allowed_schemes, new_policy.allowed_schemes);
    assert_eq!(handle.policy.block_third_party, new_policy.block_third_party);
    Ok(())
}

#[tokio::test]
async fn test_protocol_adapter_create_and_close_session() -> Result<(), ProtocolError> {
    let manager = Arc::new(SessionManager::new());
    let adapter = crate::protocol::ProtocolAdapter::new(manager.clone());

    // Create a session via CDP.
    let create_msg = CdpMessage::CreateSession {
        session_id: 5,
        policy: None,
    };
    let create_resp = adapter.handle_cdp(create_msg)?;
    match create_resp {
        CdpResponse::Ok => {}
        _ => panic!("expected Ok response for CreateSession"),
    }

    // Close the session via CDP.
    let close_msg = CdpMessage::CloseSession { session_id: 5 };
    let close_resp = adapter.handle_cdp(close_msg)?;
    match close_resp {
        CdpResponse::Ok => {}
        _ => panic!("expected Ok response for CloseSession"),
    }

    // Subsequent close should yield an error.
    let err_resp = adapter.handle_cdp(close_msg)?;
    match err_resp {
        CdpResponse::Error { code, message } => {
            assert_ne!(code, 0);
            assert!(!message.is_empty());
        }
        _ => panic!("expected Error response for duplicate CloseSession"),
    }
    Ok(())
}