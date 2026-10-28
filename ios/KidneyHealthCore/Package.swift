// swift-tools-version: 6.0
// KidneyHealthCore: the rules the iOS Health sync app must apply exactly as the server does (design note 15 §4.1).
// No dependencies, no UI and no HealthKit, so it builds and tests on Linux. The tests replay the JSON vectors in tests/data/.
import PackageDescription

let package = Package(
    name: "KidneyHealthCore",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [
        .library(name: "KidneyHealthCore", targets: ["KidneyHealthCore"]),
    ],
    targets: [
        .target(name: "KidneyHealthCore"),
        .testTarget(name: "KidneyHealthCoreTests", dependencies: ["KidneyHealthCore"]),
    ]
)
