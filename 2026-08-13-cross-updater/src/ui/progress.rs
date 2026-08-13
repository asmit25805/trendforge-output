use std::sync::{Arc, Mutex};

use log::{debug, error, info, warn};
use tokio::task::JoinHandle;

use crate::event::bus::{EventBus, UpdateEvent, SubscriptionHandle};
use crate::core::engine::{UpdateError, UpdateState};

/// Represents a window that shows update progress and reacts to events emitted by the `EventBus`.
pub struct ProgressWindow {
    /// Shared event bus used to receive update events.
    event_bus: EventBus,
    /// Handle to the subscription; kept to keep the listener alive.
    subscription: Option<SubscriptionHandle>,
    /// Current phase of the update lifecycle.
    current_state: UpdateState,
    /// Progress percentage (0.0‑100.0) for the active phase.
    progress_percent: f32,
    /// Optional background task that drives UI rendering.
    render_task: Option<JoinHandle<()>>,
    /// Internal flag indicating whether the window has been closed.
    closed: Arc<Mutex<bool>>,
}

impl ProgressWindow {
    /// Creates a new `ProgressWindow` attached to the supplied `EventBus`.
    pub fn new(event_bus: EventBus) -> Self {
        Self {
            event_bus,
            subscription: None,
            current_state: UpdateState::Checking,
            progress_percent: 0.0,
            render_task: None,
            closed: Arc::new(Mutex::new(false)),
        }
    }

    /// Starts listening to `UpdateEvent`s and spawns a background task that continuously renders the UI.
    ///
    /// The method returns `Ok(())` when the listener is successfully registered; otherwise an
    /// `UpdateError::Fatal` is returned.
    pub fn start(&mut self) -> Result<(), UpdateError> {
        // Clone the pieces needed inside the closure.
        let bus = self.event_bus.clone();
        let closed_flag = Arc::clone(&self.closed);
        let state_ref = Arc::new(Mutex::new(self.current_state));
        let percent_ref = Arc::new(Mutex::new(self.progress_percent));

        // Register the listener.
        let handle = bus.subscribe(move |event| {
            // Early exit if the UI has been closed.
            if *closed_flag.lock().unwrap() {
                return;
            }

            match event {
                UpdateEvent::Progress { state, percent } => {
                    debug!("Progress event: {:?} @ {:.2}%", state, percent);
                    *state_ref.lock().unwrap() = state;
                    *percent_ref.lock().unwrap() = percent;
                }
                UpdateEvent::Error(err) => {
                    error!("Error event received: {}", err);
                    // Errors are logged; UI rendering will pick them up in the next tick.
                }
                UpdateEvent::Log(msg) => {
                    info!("Log event: {}", msg);
                }
                UpdateEvent::Completed => {
                    info!("Update completed event received");
                    *state_ref.lock().unwrap() = UpdateState::Completed;
                    *percent_ref.lock().unwrap() = 100.0;
                }
            }
        })?;

        self.subscription = Some(handle);

        // Spawn a periodic renderer that updates the console UI every 200 ms.
        let render_handle = {
            let closed = Arc::clone(&self.closed);
            let state = Arc::clone(&state_ref);
            let percent = Arc::clone(&percent_ref);
            tokio::spawn(async move {
                loop {
                    {
                        if *closed.lock().unwrap() {
                            break;
                        }
                        let cur_state = *state.lock().unwrap();
                        let cur_percent = *percent.lock().unwrap();
                        render_console(&cur_state, cur_percent);
                    }
                    tokio::time::sleep(tokio::time::Duration::from_millis(200)).await;
                }
            })
        };

        self.render_task = Some(render_handle);
        Ok(())
    }

    /// Stops the UI rendering and unsubscribes from the event bus.
    ///
    /// This method is idempotent; calling it multiple times has no adverse effect.
    pub fn stop(&mut self) {
        // Mark the window as closed so the background task exits.
        if let Ok(mut flag) = self.closed.lock() {
            *flag = true;
        }

        // Drop the subscription handle, which unregisters the listener.
        self.subscription.take();

        // Await the render task termination if it exists.
        if let Some(handle) = self.render_task.take() {
            // We cannot `.await` inside a sync function; detach the task.
            handle.abort();
        }

        info!("ProgressWindow stopped and cleaned up");
    }

    /// Returns the current update state; useful for tests or external callers.
    pub fn current_state(&self) -> UpdateState {
        self.current_state
    }

    /// Returns the latest progress percentage; useful for tests or external callers.
    pub fn progress_percent(&self) -> f32 {
        self.progress_percent
    }
}

impl Drop for ProgressWindow {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Renders a simple textual progress UI to the console.
///
/// The function prints a single line that is overwritten on each call, giving the appearance
/// of a live progress bar. It is deliberately lightweight and does not depend on any external UI
/// framework, making it suitable for both Tauri and headless environments.
fn render_console(state: &UpdateState, percent: f32) {
    // Build a 30‑character bar where the filled portion corresponds to the percentage.
    let bar_width = 30;
    let filled = ((percent / 100.0) * bar_width as f32).round() as usize;
    let empty = bar_width - filled;
    let bar = format!(
        "[{}>{}]",
        "=".repeat(filled),
        " ".repeat(empty.max(0))
    );

    // Choose a human‑readable label for the current state.
    let state_label = match state {
        UpdateState::Checking => "Checking for updates",
        UpdateState::Downloading => "Downloading package",
        UpdateState::Verifying => "Verifying integrity",
        UpdateState::Extracting => "Extracting archive",
        UpdateState::Replacing => "Replacing executable",
        UpdateState::Launching => "Launching new version",
        UpdateState::Completed => "Update completed",
    };

    // Use carriage return to overwrite the previous line.
    print!("\r{} {} {:.1}%", state_label, bar, percent);
    // Flush stdout to ensure immediate display.
    use std::io::Write;
    std::io::stdout().flush().ok();

    // When the update reaches the Completed state, print a newline to finalize the output.
    if matches!(state, UpdateState::Completed) {
        println!();
    }
}

// -----------------------------------------------------------------------------
// Unit tests for `ProgressWindow`
// -----------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::bus::{EventBus, UpdateEvent};
    use std::sync::mpsc::{channel, Sender};
    use std::thread;
    use tokio::runtime::Runtime;

    /// Helper that creates a mock `EventBus` which forwards events to a `Sender`.
    fn mock_event_bus() -> (EventBus, Sender<UpdateEvent>) {
        let (tx, rx) = channel::<UpdateEvent>();
        let bus = EventBus::new_with_sender(tx.clone());
        // Spawn a background thread that consumes the receiver to keep the channel alive.
        thread::spawn(move || {
            while let Ok(event) = rx.recv() {
                // No‑op: the real listener will be attached in the test.
                let _ = event;
            }
        });
        (bus, tx)
    }

    #[test]
    fn test_progress_window_initial_state() {
        let (bus, _) = mock_event_bus();
        let win = ProgressWindow::new(bus);
        assert_eq!(win.current_state(), UpdateState::Checking);
        assert_eq!(win.progress_percent(), 0.0);
    }

    #[test]
    fn test_progress_window_receives_progress_events() {
        let rt = Runtime::new().unwrap();
        rt.block_on(async {
            let (bus, sender) = mock_event_bus();
            let mut win = ProgressWindow::new(bus.clone());
            win.start().expect("failed to start window");

            // Emit a progress event.
            sender
                .send(UpdateEvent::Progress {
                    state: UpdateState::Downloading,
                    percent: 42.5,
                })
                .expect("failed to send event");

            // Allow a short time for the async listener to process.
            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

            assert_eq!(win.current_state(), UpdateState::Downloading);
            assert!((win.progress_percent() - 42.5).abs() < f32::EPSILON);
            win.stop();
        });
    }

    #[test]
    fn test_progress_window_handles_error_event() {
        let rt = Runtime::new().unwrap();
        rt.block_on(async {
            let (bus, sender) = mock_event_bus();
            let mut win = ProgressWindow::new(bus.clone());
            win.start().expect("failed to start window");

            let err = UpdateError::Fatal("signature mismatch".into());
            sender
                .send(UpdateEvent::Error(err.clone()))
                .expect("failed to send error");

            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

            // The internal state should remain unchanged; only logging occurs.
            assert_eq!(win.current_state(), UpdateState::Checking);
            win.stop();
        });
    }

    #[test]
    fn test_progress_window_completes_successfully() {
        let rt = Runtime::new().unwrap();
        rt.block_on(async {
            let (bus, sender) = mock_event_bus();
            let mut win = ProgressWindow::new(bus.clone());
            win.start().expect("failed to start window");

            sender
                .send(UpdateEvent::Completed)
                .expect("failed to send completed");

            tokio::time::sleep(tokio::time::Duration::from_millis(100)).await;

            assert_eq!(win.current_state(), UpdateState::Completed);
            assert!((win.progress_percent() - 100.0).abs() < f32::EPSILON);
            win.stop();
        });
    }

    #[test]
    fn test_progress_window_stop_is_idempotent() {
        let (bus, _) = mock_event_bus();
        let mut win = ProgressWindow::new(bus);
        win.start().expect("failed to start");
        win.stop();
        // Second call should not panic.
        win.stop();
    }

    #[test]
    fn test_render_console_outputs_expected_format() {
        // Capture stdout.
        let mut buf = Vec::new();
        {
            let _guard = std::io::stdout().lock();
            let stdout = std::io::stdout();
            let mut handle = stdout.lock();
            // Temporarily replace stdout with our buffer.
            std::io::set_output_capture(Some(Box::new(&mut buf)));
            render_console(&UpdateState::Downloading, 55.0);
            std::io::set_output_capture(None);
        }
        let output = String::from_utf8(buf).expect("invalid UTF-8");
        assert!(output.contains("Downloading package"));
        assert!(output.contains("[==============>               ]"));
        assert!(output.contains("55.0%"));
    }
}