import Foundation
import Metal
import os.log

/// Simple retry utility for transient errors with exponential back‑off.
func retry<T>(attempts: Int = 3, initialDelay: TimeInterval = 0.1, operation: () throws -> T) throws -> T {
    var delay = initialDelay
    var lastError: Error?
    for attempt in 1...attempts {
        do {
            return try operation()
        } catch {
            lastError = error
            os_log("Attempt %{public}d failed with error: %{public}@", type: .error, attempt, "\(error)")
            if attempt < attempts {
                Thread.sleep(forTimeInterval: delay)
                delay *= 2
            }
        }
    }
    throw lastError!
}

// Example usage (illustrative only; adjust paths as needed).
if let device = MTLCreateSystemDefaultDevice() {
    let manager = StreamManager(device: device)
    let tensorURL = URL(fileURLWithPath: "/path/to/tensor.bin")
    do {
        let buffer = try retry {
            try manager.streamTensor(from: tensorURL, length: 4096)
        }
        print("Successfully streamed tensor with length \(buffer.length)")
    } catch {
        print("Failed to stream tensor: \(error)")
    }
} else {
    print("Metal device not available on this platform")
}
