use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use log::{error, info, warn};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use tokio::sync::Mutex;
use uuid::Uuid;

use crate::store::{
    Document,
    KnowledgeStore,
    StoreError,
}; // removed non‑exported `ArtifactId` and `DocumentMeta`

/// Unique identifier for a skill file inside the repository.
/// The string is expected to be …
/// (The rest of the file is unchanged.)
