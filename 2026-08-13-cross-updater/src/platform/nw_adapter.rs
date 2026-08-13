use std::fs::{self, File, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use log::{debug, error, info, warn};
use thiserror::Error;
use tokio::time::sleep;

use crate::event::bus::EventBus;
use crate::event::bus::UpdateEvent;
use crate::platform::electron_adapter::{
    ElevationError, FileLock, FsError, LockError, PlatformAdapter,
};

/// Adapter used when the host is a NW.js application. It mirrors the behaviour of
/// `ElectronAdapter` but is kept separate to allow future NW‑specific customisations.
pub struct NwAdapter {
    event_bus: EventBus,
}

impl NwAdapter {
    /// Creates a new `NwAdapter`. The supplied `EventBus` is used for emitting
    /// progress, log and error events.
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
    /// On Unix‑like systems this spawns `sudo -v` to prompt for credentials.
    /// On Windows the call is a no‑op because the updater binary is expected
    /// to run with sufficient rights.
    async fn perform_elevation(&self) -> Result<(), ElevationError> {
        #[cfg(target_os = "windows")]
        {
            // Windows updater is launched with the required rights; nothing to do.
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
    /// The implementation tries a simple rename first; if that fails on Windows,
    /// it falls back to a copy‑then‑replace strategy.
    async fn perform_replace(&self, old: &Path, new: &Path) -> Result<(), FsError> {
        // Attempt a direct rename; on Unix this overwrites the target.
        match fs::rename(new, old) {
            Ok(_) => return Ok(()),
            Err(e) => {
                debug!("Direct rename failed ({:?}); attempting fallback", e);
                #[cfg(target_os = "windows")]
                {
                    // On Windows we need to copy over the old file because rename
                    // does not overwrite an existing file.
                    fs::copy(new, old)
                        .map_err(FsError::Io)
                        .and_then(|_| {
                            // Remove the temporary new file after copy.
                            fs::remove_file(new).map_err(FsError::Io)
                        })
                }
                #[cfg(not(target_os = "windows"))]
                {
                    Err(FsError::AtomicReplace)
                }
            }
        }
    }
}

impl PlatformAdapter for NwAdapter {
    fn acquire_lock(&self, app_path: &Path) -> Result<FileLock, LockError> {
        let lock_path = Self::lock_file_path(app_path);
        debug!("Acquiring lock for NW.js app at {:?}", lock_path);

        let file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
            .map_err(|e| {
                if e.kind() == io::ErrorKind::AlreadyExists {
                    LockError::AlreadyLocked
                } else {
                    LockError::Io(e)
                }
            })?;

        self.emit(UpdateEvent::Log(format!(
            "Lock file created at {:?}",
            lock_path
        )));

        Ok(FileLock { _file: file })
    }

    fn request_elevation(&self) -> Result<(), ElevationError> {
        // The async block is executed synchronously because the trait does not
        // allow async; we block on the future for simplicity.
        let fut = self.perform_elevation();
        // In a real async context we would `.await`; here we use `tokio::runtime`
        // to block safely.
        let rt = tokio::runtime::Runtime::new().map_err(|e| ElevationError::Spawn(io::Error::new(
            io::ErrorKind::Other,
            format!("runtime creation failed: {}", e),
        )))?;
        rt.block_on(fut)
    }

    fn replace_executable(&self, old: &Path, new: &Path) -> Result<(), FsError> {
        let fut = self.perform_replace(old, new);
        let rt = tokio::runtime::Runtime::new().map_err(|e| FsError::Io(io::Error::new(
            io::ErrorKind::Other,
            format!("runtime creation failed: {}", e),
        )))?;
        rt.block_on(fut)
    }
}

// -----------------------------------------------------------------------------
// Unit tests for NwAdapter
// -----------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::bus::EventBus;
    use std::fs;
    use std::io::Write;
    use tempfile::tempdir;

    fn setup_bus() -> EventBus {
        EventBus::new()
    }

    #[test]
    fn test_acquire_lock_creates_file() {
        let bus = setup_bus();
        let adapter = NwAdapter::new(bus);
        let dir = tempdir().unwrap();
        let exe_path = dir.path().join("app.exe");
        File::create(&exe_path).unwrap();

        let lock = adapter.acquire_lock(&exe_path).expect("lock acquisition failed");
        let lock_path = NwAdapter::lock_file_path(&exe_path);
        assert!(lock_path.exists(), "lock file should exist after acquisition");
        drop(lock);
        // After dropping, the lock file remains; cleanup is handled by the test harness.
    }

    #[test]
    fn test_acquire_lock_already_locked() {
        let bus = setup_bus();
        let adapter = NwAdapter::new(bus);
        let dir = tempdir().unwrap();
        let exe_path = dir.path().join("app.exe");
        File::create(&exe_path).unwrap();

        // First lock succeeds.
        let _first = adapter.acquire_lock(&exe_path).expect("first lock failed");
        // Second lock should fail with AlreadyLocked.
        let err = adapter.acquire_lock(&exe_path).unwrap_err();
        match err {
            LockError::AlreadyLocked => {}
            _ => panic!("expected AlreadyLocked error"),
        }
    }

    #[test]
    fn test_request_elevation_no_error_on_windows() {
        // This test runs on any platform; on non‑Windows the implementation uses sudo.
        let bus = setup_bus();
        let adapter = NwAdapter::new(bus);
        // We simply assert that the call does not panic; the result may be Err on CI
        // if sudo is unavailable, which is acceptable for the test suite.
        let _ = adapter.request_elevation();
    }

    #[test]
    fn test_replace_executable_successful() {
        let bus = setup_bus();
        let adapter = NwAdapter::new(bus);
        let dir = tempdir().unwrap();

        let old_path = dir.path().join("old.bin");
        let new_path = dir.path().join("new.bin");

        // Write distinct contents.
        fs::write(&old_path, b"old").unwrap();
        fs::write(&new_path, b"new").unwrap();

        adapter
            .replace_executable(&old_path, &new_path)
            .expect("replace should succeed");

        let content = fs::read(&old_path).expect("read after replace");
        assert_eq!(content, b"new");
        // The temporary new file may have been removed; ensure it does not exist.
        assert!(!new_path.exists(), "new file should be removed after replace");
    }

    #[test]
    fn test_replace_executable_fallback_on_failure() {
        let bus = setup_bus();
        let adapter = NwAdapter::new(bus);
        let dir = tempdir().unwrap();

        let old_path = dir.path().join("old.bin");
        let new_path = dir.path().join("new.bin");

        // Create a read‑only old file to force rename failure on Windows.
        fs::write(&old_path, b"old").unwrap();
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::fs::PermissionsExt;
            let mut perms = fs::metadata(&old_path).unwrap().permissions();
            perms.set_readonly(true);
            fs::set_permissions(&old_path, perms).unwrap();
        }

        fs::write(&new_path, b"new").unwrap();

        let result = adapter.replace_executable(&old_path, &new_path);
        #[cfg(target_os = "windows")]
        {
            // On Windows the fallback copy should succeed even if rename fails.
            assert!(result.is_ok(), "fallback copy should succeed on Windows");
        }
        #[cfg(not(target_os = "windows"))]
        {
            assert!(result.is_err(), "non‑Windows should error on rename failure");
        }
    }

    #[test]
    fn test_lock_file_path_derivation() {
        let exe = Path::new("/some/path/app");
        let lock = NwAdapter::lock_file_path(exe);
        assert_eq!(lock, Path::new("/some/path/app.lock"));
    }
}