use std::collections::HashMap;
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc, Weak,
};
use std::time::{Duration, SystemTime};

use parking_lot::RwLock;
use thiserror::Error;

use crate::renderer::Renderer;

/// Unique identifier for a browsing session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SessionId(pub u64);

impl SessionId {
    /// Generates a new, globally unique `SessionId`.
    pub fn new() -> Self {
        static COUNTER: AtomicU64 = AtomicU64::new(1);
        SessionId(COUNTER.fetch_add(1, Ordering::Relaxed))
    }
}

/// Describes the resource limits applied to a session.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourcePolicy {
    /// Maximum RAM (in bytes) a session may allocate.
    pub max_memory: usize,
    /// CPU share (0.0 .. 1.0) allowed for the session.
    pub max_cpu: f32,
    /// Schemes that are permitted for network requests.
    pub allowed_schemes: Vec<String>,
    /// Whether third‑party requests should be blocked.
    pub block_third_party: bool,
}

impl Default for ResourcePolicy {
    fn default() -> Self {
        Self {
            max_memory: 256 * 1024 * 1024, // 256 MiB
            max_cpu: 0.5,
            allowed_schemes: vec!["http".into(), "https".into(), "data".into()],
            block_third_party: false,
        }
    }
}

/// Request used by `BrowserEngine` to create a new session.
#[derive(Debug, Clone)]
pub struct SessionRequest {
    /// Identifier for the new session.
    pub id: SessionId,
    /// Desired resource policy; if omitted, `EngineConfig::default_policy` is used.
    pub policy: ResourcePolicy,
}

/// Errors that can be emitted by the session subsystem.
#[derive(Debug, Error)]
pub enum SessionError {
    #[error("session {0:?} not found")]
    NotFound(SessionId),

    #[error("policy violation for session {0:?}: {1}")]
    PolicyViolation(SessionId, String),

    #[error("resource limit exceeded for session {0:?}")]
    ResourceLimitExceeded(SessionId),

    #[error("internal session error: {0}")]
    Internal(String),
}

/// Holds the live objects for a session and provides a handle to the caller.
pub struct SessionHandle {
    id: SessionId,
    renderer: Arc<Renderer>,
    manager: Weak<SessionManager>,
    // Tracks allocated resources for simple enforcement.
    allocated_memory: usize,
    allocated_cpu: f32,
}

impl SessionHandle {
    /// Returns the identifier of this session.
    pub fn id(&self) -> SessionId {
        self.id
    }

    /// Provides a clone of the underlying `Renderer`. The renderer is
    /// reference‑counted, so cloning is cheap.
    pub fn renderer(&self) -> Arc<Renderer> {
        Arc::clone(&self.renderer)
    }

    /// Attempts to enforce a new policy on the running session.
    ///
    /// Returns `Ok(())` if the policy can be applied without exceeding current
    /// usage; otherwise returns `SessionError::PolicyViolation`.
    pub fn enforce_policy(&mut self, new_policy: ResourcePolicy) -> Result<(), SessionError> {
        if self.allocated_memory > new_policy.max_memory {
            return Err(SessionError::PolicyViolation(
                self.id,
                format!(
                    "current memory {} > allowed {}",
                    self.allocated_memory, new_policy.max_memory
                ),
            ));
        }
        if self.allocated_cpu > new_policy.max_cpu {
            return Err(SessionError::PolicyViolation(
                self.id,
                format!(
                    "current cpu {} > allowed {}",
                    self.allocated_cpu, new_policy.max_cpu
                ),
            ));
        }
        // Update the stored policy via the manager.
        if let Some(manager) = self.manager.upgrade() {
            manager.apply_policy_internal(self.id, new_policy)?;
        }
        Ok(())
    }
}

impl Drop for SessionHandle {
    fn drop(&mut) {
        if let Some(manager) = self.manager.upgrade() {
            // Ignore errors during drop; they are logged by the manager.
            let _ = manager.close_internal(self.id);
        }
    }
}

/// Internal representation of a session stored inside `SessionManager`.
struct SessionData {
    policy: ResourcePolicy,
    renderer: Arc<Renderer>,
    // Simple counters for resource usage.
    allocated_memory: usize,
    allocated_cpu: f32,
    // Timestamp of creation – useful for diagnostics.
    created_at: SystemTime,
}

/// Manages the lifecycle of all active sessions, enforcing isolation and
/// resource quotas.
pub struct SessionManager {
    sessions: RwLock<HashMap<SessionId, SessionData>>,
}

impl SessionManager {
    /// Constructs a new, empty `SessionManager`.
    pub fn new() -> Self {
        Self {
            sessions: RwLock::new(HashMap::new()),
        }
    }

    /// Allocates a new session with its own `Renderer` and stores it in the
    /// manager. Returns a handle that can be used by the caller.
    ///
    /// # Errors
    ///
    /// Returns `SessionError::PolicyViolation` if the initial policy cannot be
    /// satisfied (e.g., impossible memory limit). Returns `SessionError::Internal`
    /// for unexpected failures.
    pub fn create(&self, id: SessionId, policy: ResourcePolicy) -> Result<SessionHandle, SessionError> {
        // Validate the policy before allocation.
        if policy.max_memory == 0 {
            return Err(SessionError::PolicyViolation(
                id,
                "max_memory must be > 0".into(),
            ));
        }
        if !(0.0..=1.0).contains(&policy.max_cpu) {
            return Err(SessionError::PolicyViolation(
                id,
                "max_cpu must be between 0.0 and 1.0".into(),
            ));
        }

        // Instantiate a fresh renderer for the session.
        let renderer = Arc::new(Renderer::new());

        let data = SessionData {
            policy: policy.clone(),
            renderer: Arc::clone(&renderer),
            allocated_memory: 0,
            allocated_cpu: 0.0,
            created_at: SystemTime::now(),
        };

        {
            let mut map = self.sessions.write();
            if map.contains_key(&id) {
                return Err(SessionError::PolicyViolation(
                    id,
                    "session id already exists".into(),
                ));
            }
            map.insert(id, data);
        }

        Ok(SessionHandle {
            id,
            renderer,
            manager: Arc::downgrade(&Arc::new(self.clone())),
            allocated_memory: 0,
            allocated_cpu: 0.0,
        })
    }

    /// Removes a session from the manager, releasing its resources.
    ///
    /// This method is idempotent; calling it multiple times for the same `id`
    /// will return `Ok(())` after the first successful removal.
    pub fn close(&self, id: SessionId) -> Result<(), SessionError> {
        self.close_internal(id)
    }

    fn close_internal(&self, id: SessionId) -> Result<(), SessionError> {
        let mut map = self.sessions.write();
        if map.remove(&id).is_some() {
            Ok(())
        } else {
            Err(SessionError::NotFound(id))
        }
    }

    /// Updates the resource policy for an existing session.
    ///
    /// The new policy must not be stricter than the current resource usage,
    /// otherwise a `PolicyViolation` error is returned.
    pub fn apply_policy(&self, id: SessionId, policy: ResourcePolicy) -> Result<(), SessionError> {
        self.apply_policy_internal(id, policy)
    }

    fn apply_policy_internal(&self, id: SessionId, policy: ResourcePolicy) -> Result<(), SessionError> {
        let mut map = self.sessions.write();
        let data = map.get_mut(&id).ok_or(SessionError::NotFound(id))?;

        // Ensure current usage fits within the new limits.
        if data.allocated_memory > policy.max_memory {
            return Err(SessionError::PolicyViolation(
                id,
                format!(
                    "current memory {} exceeds new limit {}",
                    data.allocated_memory, policy.max_memory
                ),
            ));
        }
        if data.allocated_cpu > policy.max_cpu {
            return Err(SessionError::PolicyViolation(
                id,
                format!(
                    "current cpu {} exceeds new limit {}",
                    data.allocated_cpu, policy.max_cpu
                ),
            ));
        }

        data.policy = policy;
        Ok(())
    }

    /// Internal helper used by `Renderer` to account for memory usage.
    ///
    /// Returns `Ok(())` if the allocation stays within the session's limits,
    /// otherwise returns `SessionError::ResourceLimitExceeded`.
    pub(crate) fn account_memory(&self, id: SessionId, bytes: usize) -> Result<(), SessionError> {
        let mut map = self.sessions.write();
        let data = map.get_mut(&id).ok_or(SessionError::NotFound(id))?;
        let new_total = data.allocated_memory.saturating_add(bytes);
        if new_total > data.policy.max_memory {
            return Err(SessionError::ResourceLimitExceeded(id));
        }
        data.allocated_memory = new_total;
        Ok(())
    }

    /// Internal helper used by `Renderer` to account for CPU usage.
    ///
    /// Returns `Ok(())` if the usage stays within limits, otherwise returns
    /// `ResourceLimitExceeded`.
    pub(crate) fn account_cpu(&self, id: SessionId, cpu_share: f32) -> Result<(), SessionError> {
        let mut map = self.sessions.write();
        let data = map.get_mut(&id).ok_or(SessionError::NotFound(id))?;
        let new_total = data.allocated_cpu + cpu_share;
        if new_total > data.policy.max_cpu {
            return Err(SessionError::ResourceLimitExceeded(id));
        }
        data.allocated_cpu = new_total;
        Ok(())
    }

    /// Retrieves a reference to the stored `Renderer` for a given session.
    ///
    /// This method is primarily used by `SessionHandle` to expose the renderer
    /// to callers. Returns `None` if the session does not exist.
    pub fn get_renderer(&self, id: SessionId) -> Option<Arc<Renderer>> {
        let map = self.sessions.read();
        map.get(&id).map(|data| Arc::clone(&data.renderer))
    }
}

// Implement Clone manually because `RwLock` does not implement `Clone` automatically.
impl Clone for SessionManager {
    fn clone(&self) -> Self {
        Self {
            sessions: RwLock::new(self.sessions.read().clone()),
        }
    }
}

// -----------------------------------------------------------------------------
// Unit tests for the session subsystem.
// -----------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_and_close_session() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let policy = ResourcePolicy::default();

        let handle = manager.create(id, policy.clone()).expect("creation should succeed");
        assert_eq!(handle.id(), id);
        assert!(manager.get_renderer(id).is_some());

        manager.close(id).expect("close should succeed");
        assert!(manager.get_renderer(id).is_none());
    }

    #[test]
    fn test_duplicate_session_id_fails() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let policy = ResourcePolicy::default();

        manager.create(id, policy.clone()).expect("first creation");
        let err = manager.create(id, policy).unwrap_err();
        match err {
            SessionError::PolicyViolation(_, msg) => assert!(msg.contains("already exists")),
            _ => panic!("unexpected error variant"),
        }
    }

    #[test]
    fn test_apply_policy_successful() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let policy = ResourcePolicy::default();
        manager.create(id, policy).expect("create");

        let new_policy = ResourcePolicy {
            max_memory: 512 * 1024 * 1024,
            max_cpu: 0.8,
            ..Default::default()
        };
        manager.apply_policy(id, new_policy.clone()).expect("policy update");
        // Verify internal state via a direct read.
        let map = manager.sessions.read();
        let data = map.get(&id).expect("session present");
        assert_eq!(data.policy.max_memory, new_policy.max_memory);
        assert_eq!(data.policy.max_cpu, new_policy.max_cpu);
    }

    #[test]
    fn test_apply_policy_violation_memory() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let mut policy = ResourcePolicy::default();
        policy.max_memory = 1024; // 1 KiB
        manager.create(id, policy.clone()).expect("create");

        // Simulate memory allocation that exceeds the tiny limit.
        manager.account_memory(id, 2048).expect_err("should exceed");

        // Now try to tighten the policy further – should fail.
        let tighter = ResourcePolicy {
            max_memory: 512,
            ..policy
        };
        let err = manager.apply_policy(id, tighter).unwrap_err();
        match err {
            SessionError::PolicyViolation(_, msg) => assert!(msg.contains("current memory")),
            _ => panic!("unexpected error"),
        }
    }

    #[test]
    fn test_account_cpu_limits() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let mut policy = ResourcePolicy::default();
        policy.max_cpu = 0.3;
        manager.create(id, policy).expect("create");

        manager.account_cpu(id, 0.1).expect("first cpu allocation");
        manager.account_cpu(id, 0.15).expect("second cpu allocation");
        // Exceeding the limit should error.
        manager.account_cpu(id, 0.1).expect_err("cpu limit exceeded");
    }

    #[test]
    fn test_handle_drop_closes_session() {
        let manager = SessionManager::new();
        let id = SessionId::new();
        let policy = ResourcePolicy::default();

        {
            let handle = manager.create(id, policy).expect("create");
            assert!(manager.get_renderer(id).is_some());
            // Dropping `handle` should trigger a close.
            drop(handle);
        }

        // After the block, the session must be gone.
        assert!(manager.get_renderer(id).is_none());
    }
}