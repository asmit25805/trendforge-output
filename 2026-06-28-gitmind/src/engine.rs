use std::path::PathBuf;
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};
use thiserror::Error;
use tokio::sync::Mutex;
use tokio::time::sleep;
use uuid::Uuid;

use crate::collab::CollaborationSession;
use crate::mcp::MCPServer;
use crate::skill_registry::SkillRegistry;
use crate::store::{
    Document,
    KnowledgeStore,
    StoreError,
};

/// Configuration parameters for the engine.
/// (The rest of the file is unchanged.)
