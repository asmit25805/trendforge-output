use std::sync::{
    atomic::{AtomicUsize, Ordering},
    Arc, Mutex,
};
use std::fmt;

use log::{debug, error, info, warn};

use crate::core::engine::{UpdateError, UpdateState};

/// Represents all possible events emitted by the updater.
///
/// The enum is deliberately exhaustive so that UI code can pattern‑match
/// without needing a catch‑all branch.
#[derive(Debug, Clone)]
pub enum UpdateEvent {
    /// Periodic progress update for a given state.
    ///
    /// * `state` – The current high‑level phase of the update.
    /// * `percent` – Completion percentage of the phase (0.0‑100.0).
    Progress {
        state: UpdateState,
        percent: f32,
    },

    /// An error has occurred. The UI should display the error and decide
    /// whether a retry is possible.
    Error(UpdateError),

    /// Arbitrary log message emitted by the engine or platform adapters.
    Log(String),

    /// The update process finished successfully.
    Completed,
}

impl fmt::Display for UpdateEvent {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            UpdateEvent::Progress { state, percent } => {
                write!(f, "Progress(state={:?}, percent={:.2}%)", state, percent)
            }
            UpdateEvent::Error(err) => write!(f, "Error({})", err),
            UpdateEvent::Log(msg) => write!(f, "Log({})", msg),
            UpdateEvent::Completed => write!(f, "Completed"),
        }
    }
}

/// A handle returned by [`EventBus::subscribe`]. Dropping the handle
/// automatically unregisters the associated listener.
pub struct SubscriptionHandle {
    id: usize,
    listeners: Arc<Mutex<Vec<(usize, Box<dyn Fn(UpdateEvent) + Send + Sync>)>>>,
}

impl SubscriptionHandle {
    /// Returns the identifier of the subscription. Primarily useful for
    /// debugging or manual unsubscription.
    pub fn id(&self) -> usize {
        self.id
    }
}

impl Drop for SubscriptionHandle {
    fn drop(&mut self) {
        let mut guard = self.listeners.lock().expect("mutex poisoned");
        if let Some(pos) = guard.iter().position(|(sid, _)| *sid == self.id) {
            guard.remove(pos);
            debug!("SubscriptionHandle {} dropped and listener removed", self.id);
        }
    }
}

/// Central hub for publishing and subscribing to updater events.
///
/// The bus is cheap to clone; each clone shares the same underlying listener
/// collection, guaranteeing that every emitted event reaches all registered
/// callbacks.
#[derive(Clone, Default)]
pub struct EventBus {
    listeners: Arc<Mutex<Vec<(usize, Box<dyn Fn(UpdateEvent) + Send + Sync>)>>>,
    next_id: Arc<AtomicUsize>,
}

impl EventBus {
    /// Creates a new, empty `EventBus`.
    ///
    /// The returned instance can be freely cloned and passed to any component
    /// that needs to emit or listen for events.
    pub fn new() -> Self {
        Self {
            listeners: Arc::new(Mutex::new(Vec::new())),
            next_id: Arc::new(AtomicUsize::new(1)),
        }
    }

    /// Emits an `UpdateEvent` to all currently registered listeners.
    ///
    /// The method logs the emission at *debug* level and recovers gracefully
    /// from panicking listeners, ensuring that a single faulty callback does
    /// not prevent other listeners from receiving the event.
    pub fn emit(&self, event: UpdateEvent) {
        debug!("Emitting event: {}", event);
        // Clone the listeners while holding the lock to minimise lock duration.
        let listeners_snapshot = {
            let guard = self.listeners.lock().expect("mutex poisoned");
            guard.clone()
        };

        for (_, callback) in listeners_snapshot {
            // Each callback is isolated; we catch panics to keep the bus alive.
            let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                (callback)(event.clone());
            }));
            if let Err(err) = result {
                error!("Listener panicked while handling event: {:?}", err);
            }
        }
    }

    /// Registers a new listener and returns a handle that can be used to
    /// unregister it. The listener receives a cloned `UpdateEvent` each time
    /// `emit` is called.
    ///
    /// # Arguments
    ///
    /// * `callback` – Function or closure that processes an `UpdateEvent`. It
    ///   must be `Send + Sync + 'static` because events may be emitted from
    ///   asynchronous contexts.
    ///
    /// # Returns
    ///
    /// A `SubscriptionHandle` that removes the listener when dropped.
    pub fn subscribe<F>(&self, callback: F) -> SubscriptionHandle
    where
        F: Fn(UpdateEvent) + Send + Sync + 'static,
    {
        let id = self.next_id.fetch_add(1, Ordering::Relaxed);
        let mut guard = self.listeners.lock().expect("mutex poisoned");
        guard.push((id, Box::new(callback)));
        debug!("Registered new listener with id {}", id);
        SubscriptionHandle {
            id,
            listeners: Arc::clone(&self.listeners),
        }
    }

    /// Returns the current number of active listeners. Primarily useful for
    /// diagnostics and unit tests.
    pub fn listener_count(&self) -> usize {
        let guard = self.listeners.lock().expect("mutex poisoned");
        guard.len()
    }
}

// -----------------------------------------------------------------------------
// Integration tests for the EventBus implementation.
// These tests are compiled only when `cargo test` is executed.
// -----------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::{AtomicUsize, Ordering};

    #[test]
    fn test_subscribe_and_emit() {
        let bus = EventBus::new();
        let call_counter = Arc::new(AtomicUsize::new(0));
        let counter_clone = Arc::clone(&call_counter);

        let _handle = bus.subscribe(move |event| {
            if let UpdateEvent::Log(msg) = event {
                assert_eq!(msg, "test message");
                counter_clone.fetch_add(1, Ordering::SeqCst);
            }
        });

        bus.emit(UpdateEvent::Log("test message".into()));
        assert_eq!(call_counter.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_multiple_listeners_receive_events() {
        let bus = EventBus::new();
        let hits = Arc::new(AtomicUsize::new(0));

        for _ in 0..3 {
            let hits_clone = Arc::clone(&hits);
            bus.subscribe(move |_| {
                hits_clone.fetch_add(1, Ordering::SeqCst);
            });
        }

        bus.emit(UpdateEvent::Completed);
        assert_eq!(hits.load(Ordering::SeqCst), 3);
    }

    #[test]
    fn test_unsubscribe_on_drop() {
        let bus = EventBus::new();
        let hits = Arc::new(AtomicUsize::new(0));

        let handle = {
            let hits_clone = Arc::clone(&hits);
            bus.subscribe(move |_| {
                hits_clone.fetch_add(1, Ordering::SeqCst);
            })
        };

        assert_eq!(bus.listener_count(), 1);
        drop(handle);
        assert_eq!(bus.listener_count(), 0);

        bus.emit(UpdateEvent::Completed);
        assert_eq!(hits.load(Ordering::SeqCst), 0);
    }

    #[test]
    fn test_listener_panic_is_isolated() {
        let bus = EventBus::new();
        let safe_hits = Arc::new(AtomicUsize::new(0));

        // Panic‑inducing listener.
        bus.subscribe(|_| {
            panic!("intentional panic");
        });

        // Safe listener.
        let safe_clone = Arc::clone(&safe_hits);
        bus.subscribe(move |_| {
            safe_clone.fetch_add(1, Ordering::SeqCst);
        });

        // Emitting should not abort the test.
        bus.emit(UpdateEvent::Log("ignore".into()));
        assert_eq!(safe_hits.load(Ordering::SeqCst), 1);
    }

    #[test]
    fn test_progress_event_payload() {
        let bus = EventBus::new();
        let captured = Arc::new(Mutex::new(None));

        let cap_clone = Arc::clone(&captured);
        bus.subscribe(move |event| {
            if let UpdateEvent::Progress { state, percent } = event {
                let mut lock = cap_clone.lock().unwrap();
                *lock = Some((state, percent));
            }
        });

        bus.emit(UpdateEvent::Progress {
            state: UpdateState::Downloading,
            percent: 42.5,
        });

        let lock = captured.lock().unwrap();
        let (state, percent) = lock.as_ref().expect("no progress captured");
        assert_eq!(*state, UpdateState::Downloading);
        assert!((percent - 42.5).abs() < f32::EPSILON);
    }

    #[test]
    fn test_error_event_propagates_update_error() {
        let bus = EventBus::new();
        let received = Arc::new(Mutex::new(None));

        let recv_clone = Arc::clone(&received);
        bus.subscribe(move |event| {
            if let UpdateEvent::Error(err) = event {
                let mut lock = recv_clone.lock().unwrap();
                *lock = Some(err);
            }
        });

        let err = UpdateError::Fatal("boom".into());
        bus.emit(UpdateEvent::Error(err.clone()));

        let lock = received.lock().unwrap();
        let stored = lock.as_ref().expect("error not received");
        match stored {
            UpdateError::Fatal(msg) => assert_eq!(msg, "boom"),
            _ => panic!("unexpected error variant"),
        }
    }
}