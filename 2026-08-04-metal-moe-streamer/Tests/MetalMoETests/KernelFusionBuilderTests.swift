import XCTest
import Metal
@testable import MetalMoE

final class KernelFusionBuilderTests: XCTestCase {
    private var device: MTLDevice!
    private var builder: KernelFusionBuilder!

    override func setUpWithError() throws {
        try super.setUpWithError()
        guard let dev = MTLCreateSystemDefaultDevice() else {
            throw XCTSkip("Metal device not available on this platform")
        }
        device = dev
        builder = KernelFusionBuilder(device: device)
    }

    func testFusionCreation() throws {
        // Create a dummy quantization scheme; the actual kernel is not executed in this unit test.
        let dummyScheme = QuantizationScheme(name: "none")
        let kernel = try builder.buildFusion(for: dummyScheme)
        XCTAssertNotNil(kernel, "Fusion kernel should be created")
    }
}
