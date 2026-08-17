use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, SystemTime};

use parking_lot::Mutex;
use reqwest::Client;
use tokio::time::sleep;
use url::Url;

use crate::session::{ResourcePolicy, SessionId};
use crate::streamer::{SemanticStreamer, StreamError};

/// Represents a CSS selector used for DOM extraction.
pub type CssSelector = String;

/// Errors that can occur during rendering or extraction.
#[derive(Debug)]
pub enum RenderError {
    /// Network request failed.
    Network(reqwest::Error),
    /// HTML parsing failed.
    Parse(String),
    /// The session exceeded its resource limits.
    ResourceLimitExceeded(String),
    /// An unexpected error occurred.
    Other(String),
}

impl std::fmt::Display for RenderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            RenderError::Network(e) => write!(f, "network error: {}", e),
            RenderError::Parse(e) => write!(f, "parse error: {}", e),
            RenderError::ResourceLimitExceeded(e) => write!(f, "resource limit exceeded: {}", e),
            RenderError::Other(e) => write!(f, "render error: {}", e),
        }
    }
}

impl std::error::Error for RenderError {}

/// The type of a DOM node.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
pub enum NodeType {
    Element,
    Text,
    Comment,
    Document,
}

/// A single node in the semantic DOM tree.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DomNode {
    /// Unique identifier within the session.
    pub node_id: u64,
    /// Kind of node.
    pub node_type: NodeType,
    /// Tag name for element nodes.
    pub tag_name: Option<String>,
    /// HTML attributes.
    pub attributes: HashMap<String, String>,
    /// Child node identifiers.
    pub children: Vec<u64>,
    /// Text content for text nodes.
    pub text_content: Option<String>,
}

/// A fragment returned by `Renderer::extract`.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DomFragment {
    /// Root node of the fragment.
    pub root: DomNode,
    /// All descendant nodes indexed by their id.
    pub nodes: HashMap<u64, DomNode>,
}

/// Information about a fetched sub‑resource.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ResourceEntry {
    /// URL of the fetched resource.
    pub url: Url,
    /// HTTP status code.
    pub status: u16,
}

/// Snapshot of a page after a render operation.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PageSnapshot {
    /// Absolute URL of the page.
    pub url: Url,
    /// Root of the lazy semantic tree.
    pub dom_root: DomNode,
    /// List of fetched sub‑resources.
    pub resources: Vec<ResourceEntry>,
    /// Moment the snapshot was taken.
    pub timestamp: SystemTime,
}

/// Handles streaming of DOM fragments back to the client.
pub struct StreamHandle {
    /// Reference to the underlying `SemanticStreamer`.
    pub streamer: Arc<SemanticStreamer>,
    /// Optional callback for custom processing.
    pub callback: Option<Box<dyn Fn(&DomFragment) + Send + Sync>>,
}

impl StreamHandle {
    /// Pushes a fragment through the associated streamer.
    pub async fn push(&self, fragment: DomFragment) -> Result<(), StreamError> {
        if let Some(cb) = &self.callback {
            cb(&fragment);
        }
        self.streamer.push(fragment).await
    }

    /// Closes the stream gracefully.
    pub async fn close(&self) -> Result<(), StreamError> {
        self.streamer.close().await
    }
}

/// Core renderer that performs on‑demand layout and provides a lazy semantic DOM API.
pub struct Renderer {
    session_id: SessionId,
    policy: ResourcePolicy,
    client: Client,
    /// Cached DOM tree for the current page; guarded by a mutex for interior mutability.
    dom_cache: Mutex<Option<DomNode>>,
    /// Cached resources for the current page.
    resources: Mutex<Vec<ResourceEntry>>,
    /// Stream handle used to emit fragments.
    stream_handle: StreamHandle,
}

impl Renderer {
    /// Creates a new `Renderer` bound to a session.
    pub fn new(
        session_id: SessionId,
        policy: ResourcePolicy,
        streamer: Arc<SemanticStreamer>,
    ) -> Self {
        let client = Client::builder()
            .gzip(true)
            .brotli(true)
            .deflate(true)
            .build()
            .expect("valid client builder");

        let stream_handle = StreamHandle {
            streamer,
            callback: None,
        };

        Renderer {
            session_id,
            policy,
            client,
            dom_cache: Mutex::new(None),
            resources: Mutex::new(Vec::new()),
            stream_handle,
        }
    }

    /// Fetches a URL with exponential back‑off retry on transient failures.
    async fn fetch_with_retry(&self, url: &Url) -> Result<reqwest::Response, RenderError> {
        let mut attempt = 0usize;
        let mut delay = Duration::from_millis(100);
        loop {
            match self.client.get(url.clone()).send().await {
                Ok(resp) => return Ok(resp),
                Err(e) if e.is_timeout() || e.is_connect() => {
                    attempt += 1;
                    if attempt >= 3 {
                        return Err(RenderError::Network(e));
                    }
                    sleep(delay).await;
                    delay *= 2;
                }
                Err(e) => return Err(RenderError::Network(e)),
            }
        }
    }

    /// Parses raw HTML into a minimal DOM tree.
    fn parse_html(&self, html: &str) -> Result<DomNode, RenderError> {
        // Very lightweight parser: split on tags and create a flat document node.
        // For a production implementation a proper HTML parser would be used.
        let mut node = DomNode {
            node_id: 1,
            node_type: NodeType::Document,
            tag_name: None,
            attributes: HashMap::new(),
            children: Vec::new(),
            text_content: None,
        };

        // Create a single child element representing the whole body.
        let body_id = 2;
        let body_node = DomNode {
            node_id: body_id,
            node_type: NodeType::Element,
            tag_name: Some("body".into()),
            attributes: HashMap::new(),
            children: vec![3],
            text_content: None,
        };

        let text_node = DomNode {
            node_id: 3,
            node_type: NodeType::Text,
            tag_name: None,
            attributes: HashMap::new(),
            children: Vec::new(),
            text_content: Some(html.trim().to_string()),
        };

        // Store children relationships.
        node.children.push(body_id);
        let mut map = HashMap::new();
        map.insert(node.node_id, node.clone());
        map.insert(body_node.node_id, body_node.clone());
        map.insert(text_node.node_id, text_node.clone());

        // For simplicity we return the document node; the full map is kept in cache.
        // The cache will be populated by the caller.
        Ok(node)
    }

    /// Renders a page, fetching resources on demand and building a minimal layout.
    ///
    /// Returns a `PageSnapshot` containing the URL, root DOM node, fetched resources,
    /// and the timestamp of the snapshot.
    pub async fn render(&self, url: Url) -> Result<PageSnapshot, RenderError> {
        // Enforce allowed schemes.
        if !self
            .policy
            .allowed_schemes
            .iter()
            .any(|s| s == url.scheme())
        {
            return Err(RenderError::ResourceLimitExceeded(format!(
                "scheme '{}' not allowed",
                url.scheme()
            )));
        }

        // Fetch the main document.
        let resp = self.fetch_with_retry(&url).await?;
        let status = resp.status().as_u16();
        let body = resp.text().await.map_err(RenderError::Network)?;

        // Record the main resource.
        {
            let mut res = self.resources.lock();
            res.push(ResourceEntry {
                url: url.clone(),
                status,
            });
        }

        // Parse HTML into a DOM node.
        let root_node = self.parse_html(&body)?;
        {
            let mut cache = self.dom_cache.lock();
            *cache = Some(root_node.clone());
        }

        // Build the snapshot.
        let snapshot = PageSnapshot {
            url,
            dom_root: root_node,
            resources: self.resources.lock().clone(),
            timestamp: SystemTime::now(),
        };

        Ok(snapshot)
    }

    /// Evaluates a CSS selector against the current layout tree without fully painting.
    ///
    /// Returns a `DomFragment` containing the matching subtree.
    pub async fn extract(&self, selector: CssSelector) -> Result<DomFragment, RenderError> {
        // Ensure we have a cached DOM.
        let dom_opt = { self.dom_cache.lock().clone() };
        let dom_root = dom_opt.ok_or_else(|| {
            RenderError::Other("DOM not available; call render() before extract()".into())
        })?;

        // Very naive selector handling: only supports tag name equality.
        // A real implementation would use a selector engine like `scraper`.
        let target_tag = selector.trim().to_lowercase();

        // Walk the tree to find the first matching element.
        let mut nodes = HashMap::new();
        let mut stack = vec![dom_root.clone()];
        let mut match_node: Option<DomNode> = None;

        while let Some(node) = stack.pop() {
            nodes.insert(node.node_id, node.clone());

            if let Some(tag) = &node.tag_name {
                if tag.to_lowercase() == target_tag {
                    match_node = Some(node.clone());
                    break;
                }
            }

            // In this minimal implementation children are stored as ids; we cannot
            // resolve them without a full map. For the demo we assume a flat structure.
        }

        let fragment = if let Some(root) = match_node {
            DomFragment {
                root,
                nodes,
            }
        } else {
            // Return an empty fragment if nothing matches.
            DomFragment {
                root: DomNode {
                    node_id: 0,
                    node_type: NodeType::Element,
                    tag_name: Some(selector),
                    attributes: HashMap::new(),
                    children: Vec::new(),
                    text_content: None,
                },
                nodes,
            }
        };

        // Stream the fragment to the client.
        self.stream_handle.push(fragment.clone()).await?;

        Ok(fragment)
    }

    /// Pushes incremental DOM events to a consumer as they become available.
    ///
    /// The method returns when the stream is closed or an error occurs.
    pub async fn stream_dom(&self, handle: StreamHandle) -> Result<(), StreamError> {
        // For demonstration we stream the current cached DOM once.
        let dom_opt = { self.dom_cache.lock().clone() };
        if let Some(root) = dom_opt {
            let fragment = DomFragment {
                root,
                nodes: HashMap::new(),
            };
            handle.push(fragment).await?;
        }
        Ok(())
    }

    /// Registers a custom callback that will be invoked for each streamed fragment.
    pub fn register_callback<F>(&mut self, cb: F)
    where
        F: Fn(&DomFragment) + Send + Sync + 'static,
    {
        self.stream_handle.callback = Some(Box::new(cb));
    }
}