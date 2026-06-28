use std::net::SocketAddr;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex as StdMutex};

use log::{error, info, warn};
use thiserror::Error;
use tokio::sync::Mutex;
use tonic::{transport::Server, Code, Request, Response, Status};

use crate::engine::Engine;
use crate::skill_registry::SkillRegistry; // fixed import name
use crate::store::{
    Document,
    KnowledgeStore,
    StoreError,
}; // removed non‑exported imports

/// MCP server implementation.
/// (The rest of the file is unchanged.)
