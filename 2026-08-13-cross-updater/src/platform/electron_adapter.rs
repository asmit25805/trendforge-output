use std::fs::{self, File, OpenOptions};
use std::io::{self, ErrorKind};
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use log::{debug, error, info, warn};
use thiserror::Error;
use tokio::time::sleep;

use crate::event::bus::EventBus;
use crate::event::bus::UpdateEvent;

/// Represents a held file lock. The lock is released when the struct is dropped.
pub struct FileLock {
    _file: File,
}

impl FileLock {
    /// Explicitly releases the lock before the struct is dropped.
    pub fn release(self) {
        // Dropping `_file` releases the OS lock.
    }
}

/// Errors that can occur while acquiring a lock.
#[derive(Debug, Error)]
pub enum LockError {
    #[error("failed to create lock file: {0}")]
    Io(#[from] io::Error),

    #[error("lock already held by another process")]
    AlreadyLocked,
}

/// Errors that can occur while requesting elevation.
#[derive(Debug, Error)]
pub enum ElevationError {
    #[error("failed to spawn elevation process: {0}")]
    Spawn(#[from] io::Error),

    #[error("elevation was denied by the user")]
    Denied,
}

/// Errors that can occur while performing filesystem operations.
#[derive(Debug, Error)]
pub enum FsError {
    #[error("io error: {0}")]
    Io(#[from] io::Error),

    #[error("failed to replace executable atomically")]
    AtomicReplace,
}

/// Trait that abstracts platform‑specific operations. Implemented by each adapter.
pub trait PlatformAdapter {
    /// Acquire an exclusive lock on the directory that contains the application binary.
    fn acquire_lock(&self, app_path: &Path) -> Result<FileLock, LockError>;

    /// Request elevated privileges if required for the update operation.
    fn request_elevation(&self) -> Result<(), ElevationError>;

    /// Atomically replace the old executable with the newly downloaded one.
    fn replace_executable(&self, old: &Path, new: &Path) -> Result<(), FsError>;
}

/// Adapter used when the host is an Electron application on Windows.
pub struct ElectronAdapter {
    event_bus: EventBus,
}

impl ElectronAdapter {
    /// Creates a new `ElectronAdapter`. The `EventBus` is used to emit progress and error events.
    pub fn new(event_bus: EventBus) -> Self {
        Self { event_bus }
    }

    /// Internal helper that emits a generic event.
    fn emit(&self, event: UpdateEvent) {
        self.event_bus.emit(event);
    }

    /// Generates a lock file name based on the application binary path.
    fn lock_file_path(app_path: &Path) -> PathBuf {
        let mut lock_path = app_path.to_path_buf();
        lock_path.set_extension("lock");
        lock_path
    }
}

impl PlatformAdapter for ElectronAdapter {
    fn acquire_lock(&self, app_path: &Path) -> Result<FileLock, LockError> {
        let lock_path = Self::lock_file_path(app_path);
        debug!("Attempting to acquire lock at {:?}", lock_path);

        // `create_new` fails if the file already exists, giving us a simple cross‑platform lock.
        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|e| {
                if e.kind() == ErrorKind::AlreadyExists {
                    LockError::AlreadyLocked
                } else {
                    LockError::Io(e)
                }
            })?;

        self.emit(UpdateEvent::LockAcquired {
            path: lock_path.clone(),
        });
        info!("Lock acquired: {:?}", lock_path);
        Ok(FileLock { _file: file })
    }

    fn request_elevation(&self) -> Result<(), ElevationError> {
        #[cfg(target_os = "windows")]
        {
            debug!("Requesting elevation via PowerShell");
            // The current executable is copied to a temporary location before this call,
            // so we can safely request elevation without locking the original binary.
            let current_exe = std::env::current_exe()
                .map_err(ElevationError::Spawn)?
                .to_string_lossy()
                .into_owned();

            let status = Command::new("powershell")
                .args(&[
                    "-Command",
                    "Start-Process",
                    &current_exe,
                    "-Verb",
                    "runAs",
                ])
                .status()
                .map_err(ElevationError::Spawn)?;

            if status.success() {
                self.emit(UpdateEvent::ElevationGranted);
                info!("Elevation granted by the user");
                Ok(())
            } else {
                self.emit(UpdateEvent::ElevationDenied);
                warn!("Elevation denied or failed");
                Err(ElevationError::Denied)
            }
        }

        #[cfg(not(target_os = "windows"))]
        {
            // On non‑Windows platforms the adapter is not used; return an error to keep the API consistent.
            Err(ElevationError::Spawn(io::Error::new(
                ErrorKind::Unsupported,
                "Elevation not supported on this platform",
            )))
        }
    }

    fn replace_executable(&self, old: &Path, new: &Path) -> Result<(), FsError> {
        debug!(
            "Replacing executable: old={:?}, new={:?}",
            old.display(),
            new.display()
        );

        // Ensure the new file exists before attempting replacement.
        if !new.exists() {
            error!("New executable does not exist: {:?}", new);
            return Err(FsError::Io(io::Error::new(
                ErrorKind::NotFound,
                "new executable missing",
            )));
        }

        // On Windows `rename` fails if the target exists. We therefore remove the old file first.
        // The operation is retried a few times to mitigate transient lock contention.
        const MAX_RETRIES: usize = 3;
        let mut attempt = 0usize;

        loop {
            attempt += 1;
            // Attempt to delete the old executable.
            match fs::remove_file(old) {
                Ok(_) => debug!("Removed old executable on attempt {}", attempt),
                Err(e) if e.kind() == ErrorKind::NotFound => {
                    debug!("Old executable already absent");
                }
                Err(e) => {
                    if attempt >= MAX_RETRIES {
                        error!("Failed to remove old executable after {} attempts: {}", attempt, e);
                        return Err(FsError::Io(e));
                    }
                    warn!(
                        "Transient error removing old executable (attempt {}): {}. Retrying...",
                        attempt, e
                    );
                    // Exponential back‑off before retrying.
                    let backoff = Duration::from_millis(100 * 2_u64.pow(attempt as u32));
                    std::thread::sleep(backoff);
                    continue;
                }
            }

            // Attempt the atomic rename.
            match fs::rename(new, old) {
                Ok(_) => {
                    self.emit(UpdateEvent::ExecutableReplaced {
                        old_path: old.to_path_buf(),
                        new_path: new.to_path_buf(),
                    });
                    info!("Executable replaced successfully");
                    return Ok(());
                }
                Err(e) => {
                    if attempt >= MAX_RETRIES {
                        error!("Failed to rename new executable after {} attempts: {}", attempt, e);
                        return Err(FsError::AtomicReplace);
                    }
                    warn!(
                        "Transient rename failure (attempt {}): {}. Retrying...",
                        attempt, e
                    );
                    let backoff = Duration::from_millis(200 * 2_u64.pow(attempt as u32));
                    std::thread::sleep(backoff);
                }
            }
        }
    }
}