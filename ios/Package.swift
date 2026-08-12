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
    dependencies: [
        .package(url: "https://github.com/apple/swift-crypto.git", exact: "4.3.1")
    ],
    targets: [
        .target(
            name: "TreeCore",
            dependencies: [
                .product(name: "Crypto", package: "swift-crypto")
            ],
            path: "TreeCore"
        ),
        .testTarget(
            name: "TreeCoreTests",
            dependencies: ["TreeCore"],
            path: "TreeCoreTests"
        )
    ]
)
