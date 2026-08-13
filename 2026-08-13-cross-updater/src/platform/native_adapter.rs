use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;

use log::{debug, error, info, warn};
use thiserror::Error;

use crate::event::bus::{EventBus, UpdateEvent};
use crate::platform::electron_adapter::{
    ElevationError, FileLock, FsError, LockError, PlatformAdapter,
};

/// Adapter used when the host is a pure native application (no Electron/NW.js wrapper).
///
/// It follows the same contract as the other platform adapters but does not rely on any
/// JavaScript runtime. All operations are performed directly against the operating system.
pub struct NativeAdapter {
    event_bus: EventBus,
}

impl NativeAdapter {
    /// Creates a new `NativeAdapter`. The supplied `EventBus` is used to emit progress,
    /// log and error events throughout the update lifecycle.
    pub fn new(event_bus: EventBus) -> Self {
        Self { event_bus }
    }

    /// Helper that forwards an `UpdateEvent` to the internal `EventBus`.
    fn emit(&self, event: UpdateEvent) {
        self.event_bus.emit(event);
    }

    /// Generates a lock file name based on the application binary path.
    ///
    /// The lock file lives alongside the binary and has the extension `.lock`.
    fn lock_file_path(app_path: &Path) -> PathBuf {
        let mut lock_path = app_path.to_path_buf();
        lock_path.set_extension("lock");
        lock_path
    }

    /// Performs a platform‑specific elevation request.
    ///
    /// On Unix‑like systems this runs `sudo -v` to prompt for credentials.
    /// On Windows the updater is expected to already have the required rights,
    /// so the function is a no‑op.
    fn perform_elevation(&self) -> Result<(), ElevationError> {
        #[cfg(target_os = "windows")]
        {
            debug!("Elevation request skipped on Windows");
            Ok(())
        }

        #[cfg(not(target_os = "windows"))]
        {
            debug!("Requesting elevation via sudo");
            let status = Command::new("sudo")
                .arg("-v")
                .status()
                .map_err(ElevationError::Spawn)?;

            if status.success() {
                Ok(())
            } else {
                Err(ElevationError::Denied)
            }
        }
    }

    /// Replaces the old executable with the new one atomically.
    ///
    /// The implementation first tries a direct rename. If that fails on Windows,
    /// it falls back to a copy‑then‑replace strategy.
    fn perform_replace(&self, old: &Path, new: &Path) -> Result<(), FsError> {
        // Direct rename works on Unix and overwrites the target.
        match fs::rename(new, old) {
            Ok(_) => {
                debug!("Atomic rename succeeded for {:?} -> {:?}", new, old);
                return Ok(());
            }
            Err(e) => {
                debug!("Direct rename failed ({:?}); attempting fallback", e);
            }
        }

        #[cfg(target_os = "windows")]
        {
            // On Windows rename does not overwrite; copy the new file over the old one.
            fs::copy(new, old)
                .map_err(|e| {
                    error!("Copy fallback failed: {}", e);
                    FsError::Io(e)
                })
                .and_then(|bytes_copied| {
                    debug!("Copied {} bytes to replace executable", bytes_copied);
                    // Remove the temporary new file after successful copy.
                    fs::remove_file(new).map_err(|e| {
                        error!("Failed to delete temporary file {:?}: {}", new, e);
                        FsError::Io(e)
                    })
                })
        }

        #[cfg(not(target_os = "windows"))]
        {
            // If we reach here on non‑Windows platforms the rename already failed;
            // treat it as a fatal atomic replace error.
            Err(FsError::AtomicReplace)
        }
    }
}

impl PlatformAdapter for NativeAdapter {
    fn acquire_lock(&self, app_path: &Path) -> Result<FileLock, LockError> {
        let lock_path = Self::lock_file_path(app_path);
        debug!("Attempting to acquire native lock at {:?}", lock_path);

        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|e| {
                if e.kind() == io::ErrorKind::AlreadyExists {
                    debug!("Lock file already exists");
                    LockError::AlreadyLocked
                } else {
                    LockError::Io(e)
                }
            })?;

        info!("Lock acquired for {:?}", app_path);
        self.emit(UpdateEvent::Log(format!(
            "Lock acquired at {:?}",
            lock_path
        )));

        Ok(FileLock { _file: file })
    }

    fn request_elevation(&self) -> Result<(), ElevationError> {
        debug!("NativeAdapter requesting elevation");
        match self.perform_elevation() {
            Ok(_) => {
                info!("Elevation succeeded or not required");
                self.emit(UpdateEvent::Log(
                    "Elevation granted or not required".to_string(),
                ));
                Ok(())
            }
            Err(e) => {
                error!("Elevation failed: {}", e);
                self.emit(UpdateEvent::Error(UpdateError::Fatal(e.into())));
                Err(e)
            }
        }
    }

    fn replace_executable(&self, old: &Path, new: &Path) -> Result<(), FsError> {
        debug!(
            "NativeAdapter replacing executable: old={:?}, new={:?}",
            old, new
        );
        match self.perform_replace(old, new) {
            Ok(_) => {
                info!("Executable replaced successfully");
                self.emit(UpdateEvent::Log(format!(
                    "Replaced {:?} with {:?}",
                    old, new
                )));
                Ok(())
            }
            Err(e) => {
                error!("Failed to replace executable: {}", e);
                self.emit(UpdateEvent::Error(UpdateError::Fatal(e.into())));
                Err(e)
            }
        }
    }
}

// Re‑export the error types for external users of the adapter.
pub use crate::platform::electron_adapter::{ElevationError, FsError, LockError};

/// The `UpdateError` type used throughout the engine. It is defined in the core module,
/// but we need a local import for the `request_elevation` and `replace_executable` error
/// conversions.
use crate::core::engine::UpdateError;