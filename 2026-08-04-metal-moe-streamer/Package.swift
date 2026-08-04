// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "metal-moe-streamer",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .library(
            name: "MetalMoE",
            targets: ["MetalMoE"]
        )
    ],
    targets: [
        .target(
            name: "MetalMoE",
            path: "Sources/MetalMoE",
            exclude: [],
            resources: [],
            swiftSettings: [
                .define("ENABLE_LOGGING", .when(configuration: .debug))
            ]
        ),
        .testTarget(
            name: "MetalMoETests",
            dependencies: ["MetalMoE"],
            path: "Tests/MetalMoETests"
        )
    ]
)