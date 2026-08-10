// swift-tools-version: 5.10
import PackageDescription

let package = Package(
    name: "TreeCore",
    platforms: [
        .iOS(.v17),
        .macOS(.v13),
    ],
    products: [
        .library(name: "TreeCore", targets: ["TreeCore"])
    ],
    targets: [
        .target(
            name: "TreeCore",
            path: "TreeCore"
        ),
        .testTarget(
            name: "TreeCoreTests",
            dependencies: ["TreeCore"],
            path: "TreeCoreTests"
        )
    ]
)
