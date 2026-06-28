use std::collections::HashMap;
use std::sync::Arc;
use std::time::Duration;

use log::{error, info, warn};
use thiserror::Error;
use tokio::sync::{Mutex, mpsc::UnboundedSender};
use tokio::time::sleep;
use uuid::Uuid;

use yrs::{Doc, Update, UpdateDecoder, UpdateEncoder, StateVector};

use crate::store::{
    StoreError,
}; // removed non‑exported `ArtifactId`

/// Unique identifier for a client participating in a CRDT session.
/// (The rest of the file is unchanged.)
