use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;

use crate::event::bus::{EventBus, UpdateEvent, SubscriptionHandle};
use crate::core::engine::{UpdaterEngine, UpdateRequest, UpdateError, UpdateState};

/// Helper that records all events received by a subscription.
struct EventRecorder {
    events: Arc<Mutex<Vec<UpdateEvent>>>,
    _handle: SubscriptionHandle,
}

impl EventRecorder {
    fn new(bus: &EventBus) -> Self {
        let events = Arc::new(Mutex::new(Vec::new()));
        let events_clone = Arc::clone(&events);
        let handle = bus.subscribe(move |ev| {
            events_clone.lock().unwrap().push(ev);
        });
        Self {
            events,
            _handle: handle,
        }
    }

    fn collected(&self) -> Vec<UpdateEvent> {
        self.events.lock().unwrap().clone()
    }
}

#[tokio::test]
async fn test_engine_starts_in_checking_state() {
    let bus = EventBus::new();
    let engine = UpdaterEngine::new(bus);
    assert_eq!(engine.current_state(), UpdateState::Checking);
}

#[tokio::test]
async fn test_engine_transitions_to_downloading() {
    let bus = EventBus::new();
    let recorder = EventRecorder::new(&bus);
    let mut engine = UpdaterEngine::new(bus);
    // Transition to the Downloading state; the engine should emit a progress event.
    engine
        .transition(UpdateState::Downloading)
        .expect("transition to Downloading failed");
    let events = recorder.collected();
    assert!(events.iter().any(|e| matches!(
        e,
        UpdateEvent::Progress {
            state: UpdateState::Downloading,
            ..
        }
    )));
}

#[tokio::test]
async fn test_engine_emits_progress_events_during_update() {
    let bus = EventBus::new();
    let recorder = EventRecorder::new(&bus);
    let mut engine = UpdaterEngine::new(bus);
    // Simulate a full lifecycle by stepping through each state.
    let lifecycle = [
        UpdateState::Checking,
        UpdateState::Downloading,
        UpdateState::Verifying,
        UpdateState::BackingUp,
        UpdateState::Replacing,
        UpdateState::Launching,
        UpdateState::Completed,
    ];
    for state in lifecycle.iter() {
        engine
            .transition(*state)
            .expect("state transition failed");
    }
    let events = recorder.collected();
    // Ensure at least one progress event per state was emitted.
    for state in lifecycle.iter() {
        assert!(
            events.iter().any(|e| matches!(
                e,
                UpdateEvent::Progress { state: s, .. } if *s == *state
            )),
            "missing progress event for state {:?}",
            state
        );
    }
    // The final Completed event must be present.
    assert!(events.iter().any(|e| matches!(e, UpdateEvent::Completed)));
}

#[tokio::test]
async fn test_engine_handles_retryable_error_and_retries() {
    let bus = EventBus::new();
    let recorder = EventRecorder::new(&bus);
    let mut engine = UpdaterEngine::new(bus);
    // Force a retryable error by providing a malformed request.
    let bad_req = UpdateRequest {
        manifest_url: "file:///nonexistent".into(),
        current_version: "0.0.0".into(),
        app_path: std::env::current_exe().unwrap(),
    };
    // The engine should attempt the operation, emit an error, and retry up to three times.
    let result = engine.run(bad_req).await;
    assert!(matches!(result, Err(UpdateError::Retryable(_))));
    let error_events = recorder
        .collected()
        .into_iter()
        .filter(|e| matches!(e, UpdateEvent::Error(_)))
        .count();
    // At least one error event must have been emitted.
    assert!(error_events >= 1);
}

#[tokio::test]
async fn test_engine_rollback_restores_previous_state() {
    let bus = EventBus::new();
    let recorder = EventRecorder::new(&bus);
    let mut engine = UpdaterEngine::new(bus);
    // Move to a state that would normally require a rollback later.
    engine
        .transition(UpdateState::Replacing)
        .expect("failed to transition to Replacing");
    // Invoke rollback; it should emit a progress event for the Backup state.
    engine.rollback().expect("rollback failed");
    let events = recorder.collected();
    assert!(events.iter().any(|e| matches!(
        e,
        UpdateEvent::Progress {
            state: UpdateState::BackingUp,
            ..
        }
    )));
}

#[tokio::test]
async fn test_eventbus_thread_safety_multiple_emitters() {
    let bus = EventBus::new();
    let recorder = EventRecorder::new(&bus);
    let handles: Vec<_> = (0..5)
        .map(|i| {
            let bus_clone = bus.clone();
            thread::spawn(move || {
                let progress = UpdateEvent::Progress {
                    state: UpdateState::Downloading,
                    percent: i as f32 * 20.0,
                };
                bus_clone.emit(progress);
                thread::sleep(Duration::from_millis(10));
                let log = UpdateEvent::Log(format!("thread {} done", i));
                bus_clone.emit(log);
            })
        })
        .collect();

    for h in handles {
        h.join().expect("thread panicked");
    }

    // Give the bus a moment to deliver all events.
    tokio::time::sleep(Duration::from_millis(50)).await;

    let events = recorder.collected();
    // Expect 5 progress events and 5 log events.
    let progress_cnt = events
        .iter()
        .filter(|e| matches!(e, UpdateEvent::Progress { .. }))
        .count();
    let log_cnt = events.iter().filter(|e| matches!(e, UpdateEvent::Log(_))).count();
    assert_eq!(progress_cnt, 5);
    assert_eq!(log_cnt, 5);
}