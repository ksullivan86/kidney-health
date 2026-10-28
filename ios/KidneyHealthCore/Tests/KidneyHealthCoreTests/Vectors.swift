// Loads the JSON vectors from tests/data/ in the repository, which hold the server's answers (tests/data/README.md).
import Foundation
import XCTest

enum Vectors {
    /// The repository root: this file is ios/KidneyHealthCore/Tests/KidneyHealthCoreTests/Vectors.swift.
    static let root = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        .deletingLastPathComponent().deletingLastPathComponent()

    static func load(_ name: String) throws -> [String: Any] {
        let url = root.appendingPathComponent("tests/data/\(name)")
        let data = try Data(contentsOf: url)
        return try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any], "\(name) is not a JSON object")
    }
}

extension Dictionary where Key == String, Value == Any {
    func list(_ key: String) throws -> [[String: Any]] {
        try XCTUnwrap(self[key] as? [[String: Any]], "\(key) is not a list of objects")
    }

    func object(_ key: String) throws -> [String: Any] {
        try XCTUnwrap(self[key] as? [String: Any], "\(key) is not an object")
    }

    func text(_ key: String) throws -> String {
        try XCTUnwrap(self[key] as? String, "\(key) is not a text")
    }

    func number(_ key: String) throws -> Double {
        try XCTUnwrap((self[key] as? NSNumber)?.doubleValue, "\(key) is not a number")
    }

    func int(_ key: String) throws -> Int {
        try XCTUnwrap((self[key] as? NSNumber)?.intValue, "\(key) is not a number")
    }

    /// nil when the key holds JSON null or is missing.
    func optionalText(_ key: String) -> String? { self[key] as? String }
}
