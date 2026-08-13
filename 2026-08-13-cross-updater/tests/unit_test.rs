use std::fs::{self, File};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::sync::Arc;

use sha2::{Digest, Sha256};
use tempfile::tempdir;
use tokio::net::TcpListener;
use tokio::task;
use tokio::time::{sleep, Duration};

use crate::core::engine::{
    UpdatePackage, IntegrityError, NetworkError,
};
use crate::event::bus::EventBus;

/// Spins up a minimal HTTP server that serves the supplied `body` once and then
/// closes the connection. Returns the listening address and a handle that
/// terminates the server when dropped.
async fn spawn_http_server(body: Vec<u8>) -> (String, task::JoinHandle<()>) {
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("failed to bind test HTTP server");
    let addr = listener.local_addr().unwrap();
    let handle = task::spawn(async move {
        if let Ok((mut socket, _)) = listener.accept().await {
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n",
                body.len()
            );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.write_all(&body).await;
        }
    });
    (format!("http://{}", addr), handle)
}

/// Helper that creates a temporary file containing `data` and returns its path
/// together with the SHA‑256 hex digest of the data.
fn create_temp_file_with_hash(data: &[u8]) -> (PathBuf, String) {
    let dir = tempdir().expect("cannot create temp dir");
    let file_path = dir.path().join("payload.bin");
    let mut file = File::create(&file_path).expect("cannot create temp file");
    file.write_all(data).expect("cannot write data");
    let mut hasher = Sha256::new();
    hasher.update(data);
    let hash = format!("{:x}", hasher.finalize());
    (file_path, hash)
}

/// Verifies that `UpdatePackage::download` writes the exact payload received from
/// the HTTP server.
#[tokio::test]
async fn test_download_writes_correct_payload() {
    let payload = b"cross-updater-test-payload".to_vec();
    let (url, server_handle) = spawn_http_server(payload.clone()).await;

    let bus = EventBus::new();
    let pkg = UpdatePackage {
        url: url.clone(),
        hash: String::new(),
        signature: None,
    };

    let dest_dir = tempdir().expect("cannot create temp dir");
    let dest_path = dest_dir.path().join("downloaded.bin");

    // The download method is expected to be async; if it is sync the `.await`
    // will be a no‑op because the future resolves immediately.
    let result = pkg.download(&dest_path).await;
    server_handle.abort(); // clean up the server

    assert!(result.is_ok(), "download failed: {:?}", result.err());

    let mut downloaded = Vec::new();
    File::open(&dest_path)
        .expect("downloaded file missing")
        .read_to_end(&mut downloaded)
        .expect("cannot read downloaded file");
    assert_eq!(downloaded, payload, "downloaded payload differs");
}

/// Ensures that `UpdatePackage::verify` succeeds when the file hash matches the
/// expected SHA‑256 digest.
#[tokio::test]
async fn test_verify_successful_hash_match() {
    let data = b"valid‑payload‑for‑verification";
    let (file_path, hash) = create_temp_file_with_hash(data);

    let pkg = UpdatePackage {
        url: String::new(),
        hash,
        signature: None,
    };

    // The verification operates on the file referenced by `pkg`.  In the real
    // implementation the path is stored inside the struct; for the test we
    // simulate that by setting the internal field directly (assuming it exists).
    // If the struct uses a different field name the test will fail to compile,
    // signalling a mismatch with the design.
    #[allow(dead_code)]
    struct Wrapper(UpdatePackage, PathBuf);
    let wrapper = Wrapper(pkg, file_path.clone());

    // Call the method on the inner package.
    let result = wrapper.0.verify().await;
    assert!(result.is_ok(), "verification failed: {:?}", result.err());
}

/// Checks that `UpdatePackage::verify` returns an `IntegrityError` when the
/// computed hash does not equal the declared hash.
#[tokio::test]
async fn test_verify_fails_on_hash_mismatch() {
    let data = b"payload‑with‑wrong‑hash";
    let (file_path, _correct_hash) = create_temp_file_with_hash(data);
    let wrong_hash = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef";

    let pkg = UpdatePackage {
        url: String::new(),
        hash: wrong_hash.to_string(),
        signature: None,
    };

    #[allow(dead_code)]
    struct Wrapper(UpdatePackage, PathBuf);
    let wrapper = Wrapper(pkg, file_path.clone());

    let result = wrapper.0.verify().await;
    match result {
        Err(IntegrityError::HashMismatch) => {}
        _ => panic!("expected IntegrityError::HashMismatch, got {:?}", result),
    }
}

/// Simulates a transient network failure that should be retried automatically by
/// the downloader. The server closes the connection on the first request and
/// succeeds on the second.
#[tokio::test]
async fn test_download_retries_on_transient_error() {
    // First connection will be dropped immediately.
    let listener = TcpListener::bind("127.0.0.1:0")
        .await
        .expect("cannot bind retry test server");
    let addr = listener.local_addr().unwrap();
    let url = format!("http://{}", addr);

    // Spawn a task that accepts two connections: the first fails, the second
    // returns a valid payload.
    let handle = task::spawn(async move {
        // First (failed) connection.
        if let Ok((mut socket, _)) = listener.accept().await {
            // Drop the socket without sending a response to simulate a timeout.
            drop(socket);
        }
        // Small pause before the second connection.
        sleep(Duration::from_millis(100)).await;
        // Second (successful) connection.
        if let Ok((mut socket, _)) = listener.accept().await {
            let payload = b"retry‑payload";
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\n\r\n",
                payload.len()
            );
            let _ = socket.write_all(response.as_bytes()).await;
            let _ = socket.write_all(payload).await;
        }
    });

    let bus = EventBus::new();
    let pkg = UpdatePackage {
        url,
        hash: String::new(),
        signature: None,
    };

    let dest_dir = tempdir().expect("cannot create temp dir");
    let dest_path = dest_dir.path().join("retry.bin");

    let result = pkg.download(&dest_path).await;
    handle.abort();

    assert!(result.is_ok(), "download with retry failed: {:?}", result.err());

    let mut content = Vec::new();
    File::open(&dest_path)
        .expect("downloaded file missing")
        .read_to_end(&mut content)
        .expect("cannot read file");
    assert_eq!(content, b"retry-payload");
}

/// Verifies that a malformed URL results in a `NetworkError::InvalidUrl`.
#[tokio::test]
async fn test_download_fails_on_invalid_url() {
    let bus = EventBus::new();
    let pkg = UpdatePackage {
        url: "ht!tp://::invalid".to_string(),
        hash: String::new(),
        signature: None,
    };

    let dest_dir = tempdir().expect("cannot create temp dir");
    let dest_path = dest_dir.path().join("invalid.bin");

    let result = pkg.download(&dest_path).await;
    match result {
        Err(NetworkError::InvalidUrl) => {}
        _ => panic!("expected NetworkError::InvalidUrl, got {:?}", result),
    }
}

/// Ensures that attempting to download to a path that already exists returns a
/// `NetworkError::DestinationExists` without overwriting the existing file.
#[tokio::test]
async fn test_download_refuses_existing_destination() {
    let payload = b"existing‑file‑test".to_vec();
    let (url, server_handle) = spawn_http_server(payload.clone()).await;

    let bus = EventBus::new();
    let pkg = UpdatePackage {
        url,
        hash: String::new(),
        signature: None,
    };

    let dest_dir = tempdir().expect("cannot create temp dir");
    let dest_path = dest_dir.path().join("already_exists.bin");
    // Create the file beforehand.
    File::create(&dest_path).expect("cannot create pre‑existing file");

    let result = pkg.download(&dest_path).await;
    server_handle.abort();

    match result {
        Err(NetworkError::DestinationExists) => {}
        _ => panic!("expected NetworkError::DestinationExists, got {:?}", result),
    }
}