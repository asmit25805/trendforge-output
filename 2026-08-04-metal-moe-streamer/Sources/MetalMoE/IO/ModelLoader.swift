import Foundation
import Metal
import os.log

/// Errors that can be raised while loading a model manifest or expert tensors.
public enum ManifestParseError: Error, CustomStringConvertible {
    /// A non‑recoverable error that aborts the whole inference session.
    case fatal(message: String)
    /// A transient I/O error that may be retried.
    case transient(message: String, underlying: Error)

    public var description: String {
        switch self {
        case .fatal(let message):
            return "Fatal ManifestParseError: \(message)"
        case .transient(let message, let underlying):
            return "Transient ManifestParseError: \(message) – underlying: \(underlying)"
        }
    }
}

/// Represents a single expert entry in the manifest.
public struct ExpertDescriptor: Codable {
    public let name: String
    public let filePath: String
    public let sizeInBytes: Int
    public let quantization: String
}

/// Represents the top‑level manifest.
public struct ModelManifest: Codable {
    public let version: String
    public let experts: [ExpertDescriptor]
}

/// Loads a model manifest from JSON and provides helper methods.
public final class ModelLoader {
    private let logger = OSLog(subsystem: "com.metalmoe.loader", category: "ModelLoader")

    public init() {}

    /// Loads and decodes a manifest from the given URL.
    /// - Parameter url: URL of the JSON manifest file.
    /// - Returns: `ModelManifest` instance.
    /// - Throws: `ManifestParseError` if the file cannot be read or decoded.
    public func loadManifest(from url: URL) throws -> ModelManifest {
        do {
            let data = try Data(contentsOf: url)
            let decoder = JSONDecoder()
            let manifest = try decoder.decode(ModelManifest.self, from: data)
            os_log("Successfully parsed manifest at %{public}@", log: logger, type: .info, url.path)
            return manifest
        } catch {
            throw ManifestParseError.transient(message: "Failed to load or parse manifest.", underlying: error)
        }
    }
}
