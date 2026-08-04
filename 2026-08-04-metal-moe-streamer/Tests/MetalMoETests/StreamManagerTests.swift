import XCTest
import Metal
@testable import MetalMoE

final class StreamManagerTests: XCTestCase {
    private var device: MTLDevice!
    private var manager: StreamManager!

    override func setUpWithError() throws {
        try super.setUpWithError()
        guard let dev = MTLCreateSystemDefaultDevice() else {
            throw XCTSkip("Metal device not available on this platform")
        }
        device = dev
        manager = StreamManager(device: device)
    }

    func testZeroBufferCreation() throws {
        let length = 1024
        let tempURL = URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("zero.bin")
        // Write a file filled with zeros.
        let zeros = Data(count: length)
        try zeros.write(to: tempURL)

        let buffer = try manager.streamTensor(from: tempURL, length: length)
        XCTAssertEqual(buffer.length, length)

        let contents = buffer.contents().assumingMemoryBound(to: UInt8.self)
        for i in 0..<length {
            XCTAssertEqual(contents[i], 0, "Byte at index \(i) is not zero")
        }
    }
}
