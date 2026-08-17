use std::net::SocketAddr;
use std::time::Duration;

use log::{error, info};
use tokio::time::sleep;
use url::Url;

use webloom::engine::{BrowserEngine, EngineConfig, EngineError, LogLevel};
use webloom::session::{ResourcePolicy, SessionRequest, SessionId};
use webloom::renderer::{CssSelector, Renderer};
use webloom::streamer::SemanticStreamer;

/// A minimal example that starts the WebLoom engine, creates a session,
/// navigates to a page, extracts a DOM fragment, and streams it as JSON.
///
/// Run with:
/// ```sh
/// cargo run --example example
/// ```
#[tokio::main]
async fn main() {
    // Initialise a simple logger (stderr) for the example.
    env_logger::Builder::from_default_env()
        .filter_level(log::LevelFilter::Info)
        .init();

    // -------------------------------------------------------------------------
    // 1. Engine configuration and startup
    // -------------------------------------------------------------------------
    let listen_addr: SocketAddr = "127.0.0.1:0".parse().expect("valid socket address");
    let default_policy = ResourcePolicy {
        max_memory: 256 * 1024 * 1024,
        max_cpu: 0.5,
        allowed_schemes: vec!["http".into(), "https".into(), "data".into()],
        block_third_party: false,
    };

    let config = EngineConfig {
        listen_addr,
        default_policy,
        log_level: LogLevel::Info,
    };

    let engine = match BrowserEngine::new(config) {
        Ok(e) => e,
        Err(e) => {
            error!("Failed to initialise engine: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 2. Create a browsing session
    // -------------------------------------------------------------------------
    let session_req = SessionRequest {
        session_id: SessionId::new(1),
        policy: None,
    };

    let handle = match engine.spawn_session(session_req).await {
        Ok(h) => h,
        Err(e) => {
            error!("Failed to spawn session: {}", e);
            std::process::exit(1);
        }
    };

    // -------------------------------------------------------------------------
    // 3. Prepare the streamer – print each fragment as a compact JSON line
    // -------------------------------------------------------------------------
    let streamer = match handle.streamer {
        Some(s) => s,
        None => {
            error!("Session does not contain a streamer");
            std::process::exit(1);
        }
    };

    // Register a callback that simply logs the serialized fragment.
    streamer.register_callback(Box::new(|frag| {
        match serde_json::to_string(frag) {
            Ok(json) => info!("STREAMED FRAGMENT: {}", json),
            Err(e) => error!("Failed to serialize fragment: {}", e),
        }
    }));

    // -------------------------------------------------------------------------
    // 4. Navigate to a page and take a snapshot
    // -------------------------------------------------------------------------
    let renderer = match handle.renderer {
        Some(r) => r,
        None => {
            error!("Session does not contain a renderer");
            std::process::exit(1);
        }
    };

    let target_url = Url::parse("https://www.rust-lang.org").expect("valid URL");
    let snapshot = match renderer.render(target_url.clone()).await {
        Ok(s) => s,
        Err(e) => {
            error!("Render error for {}: {}", target_url, e);
            std::process::exit(1);
        }
    };
    info!("Page snapshot taken for {}", snapshot.url);

    // -------------------------------------------------------------------------
    // 5. Extract a fragment (e.g., the page title) and push it through the streamer
    // -------------------------------------------------------------------------
    let selector = CssSelector::new("title").expect("valid selector");
    let fragment = match renderer.extract(selector).await {
        Ok(f) => f,
        Err(e) => {
            error!("Extraction error: {}", e);
            std::process::exit(1);
        }
    };

    if let Err(e) = streamer.push(fragment) {
        error!("Failed to push fragment: {}", e);
    }

    // Give the background task a moment to flush the output.
    sleep(Duration::from_millis(200)).await;

    // -------------------------------------------------------------------------
    // 6. Graceful shutdown
    // -------------------------------------------------------------------------
    if let Err(e) = engine.shutdown().await {
        error!("Engine shutdown error: {}", e);
    } else {
        info!("Engine shut down cleanly");
    }
}