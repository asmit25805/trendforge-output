use std::net::SocketAddr;
use std::sync::Arc;

use tokio::sync::Notify;
use tokio::time::{sleep, Duration};

use crate::engine::{BrowserEngine, EngineConfig, EngineError, LogLevel};
use crate::renderer::{CssSelector, DomFragment, Renderer, RenderError};
use crate::session::{
    ResourcePolicy, SessionError, SessionHandle, SessionManager, SessionRequest, SessionId,
};
use crate::protocol::ProtocolError;

/// Builds a minimal `EngineConfig` suitable for unit tests.
fn test_engine_config() -> EngineConfig {
    EngineConfig {
        listen_addr: "127.0.0.1:0".parse().expect("valid socket address"),
        default_policy: ResourcePolicy {
            max_memory: 32 * 1024 * 1024,
            max_cpu: 0.1,
            allowed_schemes: vec!["data".into(), "http".into(), "https".into()],
            block_third_party: true,
        },
        log_level: LogLevel::Info,
    }
}

/// Creates a fresh `BrowserEngine` and spawns a session with the given `session_id`.
async fn setup_engine_with_session(session_id: SessionId) -> Result<(BrowserEngine, SessionHandle), EngineError> {
    let config = test_engine_config();
    let engine = BrowserEngine::new(config)?;
    let req = SessionRequest {
        session_id,
        policy: None,
    };
    let handle = engine.spawn_session(req).await?;
    Ok((engine, handle))
}

/// Verifies that a session can be created and that its policy matches the engine default.
#[tokio::test]
async fn test_session_create_uses_default_policy() -> Result<(), EngineError> {
    let (engine, handle) = setup_engine_with_session(1).await?;
    let manager = engine.session_manager();

    // Retrieve the internal session representation via the manager.
    let session = manager.get_session(1).ok_or_else(|| EngineError::Session(SessionError::NotFound))?;
    assert_eq!(session.policy.max_memory, engine.config().default_policy.max_memory);
    assert!(handle.renderer.is_some());
    Ok(())
}

/// Ensures that applying a new policy updates the session's limits.
#[tokio::test]
async fn test_apply_policy_updates_session() -> Result<(), EngineError> {
    let (engine, _handle) = setup_engine_with_session(2).await?;
    let manager = engine.session_manager();

    let new_policy = ResourcePolicy {
        max_memory: 8 * 1024 * 1024,
        max_cpu: 0.05,
        allowed_schemes: vec!["data".into()],
        block_third_party: false,
    };
    manager.apply_policy(2, new_policy.clone()).await?;
    let session = manager.get_session(2).ok_or_else(|| EngineError::Session(SessionError::NotFound))?;
    assert_eq!(session.policy.max_memory, new_policy.max_memory);
    assert_eq!(session.policy.max_cpu, new_policy.max_cpu);
    Ok(())
}

/// Confirms that closing a session removes it from the manager.
#[tokio::test]
async fn test_close_session_removes_it() -> Result<(), EngineError> {
    let (engine, _handle) = setup_engine_with_session(3).await?;
    let manager = engine.session_manager();

    manager.close(3).await?;
    assert!(manager.get_session(3).is_none());
    Ok(())
}

/// Renders a minimal HTML page via a data URL and checks the snapshot fields.
#[tokio::test]
async fn test_renderer_render_simple_page() -> Result<(), EngineError> {
    let (_engine, handle) = setup_engine_with_session(4).await?;
    let renderer = handle
        .renderer
        .as_ref()
        .expect("renderer should be present")
        .clone();

    let html = "<html><body><div id=\"hello\">World</div></body></html>";
    let data_url = format!("data:text/html,{}", urlencoding::encode(html));
    let url = data_url.parse().expect("valid data URL");

    let snapshot = renderer.render(url.clone()).await.map_err(EngineError::Render)?;
    assert_eq!(snapshot.url, url);
    assert_eq!(snapshot.dom_root.node_type, crate::renderer::NodeType::Element);
    Ok(())
}

/// Extracts a DOM fragment using a CSS selector and validates the returned nodes.
#[tokio::test]
async fn test_renderer_extract_selector_returns_fragment() -> Result<(), EngineError> {
    let (_engine, handle) = setup_engine_with_session(5).await?;
    let renderer = handle
        .renderer
        .as_ref()
        .expect("renderer should be present")
        .clone();

    let html = "<html><body><p class=\"msg\">Hello</p></body></html>";
    let data_url = format!("data:text/html,{}", urlencoding::encode(html));
    let url = data_url.parse().expect("valid data URL");

    // Render first to populate the layout tree.
    renderer.render(url).await.map_err(EngineError::Render)?;

    // Extract the paragraph element.
    let selector = CssSelector::new(".msg".into());
    let fragment = renderer.extract(selector).await.map_err(EngineError::Render)?;
    assert!(!fragment.nodes.is_empty());

    // Verify that at least one node has the expected class attribute.
    let has_class = fragment
        .nodes
        .iter()
        .any(|n| n.attributes.get("class").map_or(false, |v| v == "msg"));
    assert!(has_class);
    Ok(())
}

/// Checks that extracting a non‑existent selector yields a `RenderError::NoMatch`.
#[tokio::test]
async fn test_renderer_extract_missing_selector_errors() -> Result<(), EngineError> {
    let (_engine, handle) = setup_engine_with_session(6).await?;
    let renderer = handle
        .renderer
        .as_ref()
        .expect("renderer should be present")
        .clone();

    let html = "<html><body><span id=\"present\"></span></body></html>";
    let data_url = format!("data:text/html,{}", urlencoding::encode(html));
    let url = data_url.parse().expect("valid data URL");

    renderer.render(url).await.map_err(EngineError::Render)?;

    let selector = CssSelector::new("#absent".into());
    let err = renderer.extract(selector).await.err().ok_or_else(|| EngineError::Render(RenderError::Other("expected error".into())))?;
    match err {
        RenderError::NoMatch => {} // expected path
        _ => panic!("unexpected error variant: {:?}", err),
    }
    Ok(())
}