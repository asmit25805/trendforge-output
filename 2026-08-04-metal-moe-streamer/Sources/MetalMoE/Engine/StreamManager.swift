import Foundation
import Metal
import os.log

/// Errors that can be raised by ``StreamManager`` during expert streaming.
public enum StreamError: Error, CustomStringConvertible {
    /// A non‑recoverable error that aborts the whole inference session.
    case fatal(message: String)
    /// A transient I/O error that may be retried.
    case transient(message: String, underlying: Error)

    public var description: String {
        switch self {
        case .fatal(let message):
            return "Fatal StreamError: \(message)"
        case .transient(let message, let underlying):
            return "Transient StreamError: \(message) – underlying: \(underlying)"
        }
    }
}

/// Manages streaming of expert tensors from disk into GPU buffers.
public final class StreamManager {
    private let device: MTLDevice
    private let logger = OSLog(subsystem: "com.metalmoe.stream", category: "StreamManager")

    public init(device: MTLDevice) {
        self.device = device
    }

    /// Streams a tensor from the given file URL into a Metal buffer.
    /// - Parameters:
    ///   - url: File URL of the tensor data.
    ///   - length: Number of bytes to read.
    /// - Returns: A `MTLBuffer` containing the tensor data.
    /// - Throws: `StreamError` if reading fails.
    public func streamTensor(from url: URL, length: Int) throws -> MTLBuffer {
        do {
            let data = try Data(contentsOf: url, options: .mappedIfSafe)
            guard data.count >= length else {
                throw StreamError.fatal(message: "File data is smaller than expected length.")
            }
            guard let buffer = device.makeBuffer(length: length, options: .storageModeShared) else {
                throw StreamError.fatal(message: "Failed to create Metal buffer.")
            }
            data.copyBytes(to: buffer.contents().assumingMemoryBound(to: UInt8.self), count: length)
            os_log("Successfully streamed tensor from %{public}@", log: logger, type: .info, url.path)
            return buffer
        } catch {
            throw StreamError.transient(message: "Failed to read tensor data.", underlying: error)
        }
    }
}
