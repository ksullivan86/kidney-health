// body_vectors.json and apple_health_vectors.json: the units, the rounding, the contexts, the watch rule and the source_key.
// A HealthKit client has no XML, so the reader's chunk and entity cases do not apply (tests/data/README.md, "apple_health_vectors").
import Foundation
import XCTest
@testable import KidneyHealthCore

final class BodyVectorTests: XCTestCase {
    func testTheConstantsAreTheServers() throws {
        let body = try Vectors.load("body_vectors.json")
        let constants = try body.object("constants")
        XCTAssertEqual(try constants.number("kg_per_lb"), Body.kgPerLb)
        let limits = try constants.object("limits")
        XCTAssertEqual(try limits.number("min_kg"), Body.kgRange.lowerBound)
        XCTAssertEqual(try limits.number("max_kg"), Body.kgRange.upperBound)
        XCTAssertEqual(try limits.int("min_systolic"), Body.systolicRange.lowerBound)
        XCTAssertEqual(try limits.int("max_systolic"), Body.systolicRange.upperBound)
        XCTAssertEqual(try limits.int("min_diastolic"), Body.diastolicRange.lowerBound)
        XCTAssertEqual(try limits.int("max_diastolic"), Body.diastolicRange.upperBound)
        XCTAssertEqual(try limits.int("max_weights_per_day"), Body.maxWeightsPerDay)
        XCTAssertEqual(try limits.int("max_readings_per_day"), Body.maxReadingsPerDay)

        let apple = try Vectors.load("apple_health_vectors.json")
        let appleLimits = try apple.object("limits")
        XCTAssertEqual(try appleLimits.number("kg_per_lb"), Body.kgPerLb)
        let types = try appleLimits.object("types")
        XCTAssertEqual(try types.text("weight"), Body.weightType)
        XCTAssertEqual(try types.text("systolic"), Body.systolicType)
        XCTAssertEqual(try types.text("diastolic"), Body.diastolicType)
        let ranges = try appleLimits.object("ranges")
        XCTAssertEqual(ranges["kg"] as? [Double], [Body.kgRange.lowerBound, Body.kgRange.upperBound])
        XCTAssertEqual(ranges["systolic"] as? [Int], [Body.systolicRange.lowerBound, Body.systolicRange.upperBound])
        XCTAssertEqual(ranges["diastolic"] as? [Int], [Body.diastolicRange.lowerBound, Body.diastolicRange.upperBound])
    }

    func testPoundsBecomeTheStoredKilograms() throws {
        let groups = try Vectors.load("body_vectors.json").list("unit_cases")
        var seen = 0
        for group in groups {
            for unit in try group.list("cases") {
                if unit["lb"] != nil {
                    XCTAssertEqual(Body.lbToKg(try unit.number("lb")), try unit.number("kg"), "\(unit)")
                    seen += 1
                } else if unit["round_kg"] != nil {
                    XCTAssertEqual(Body.roundKg(try unit.number("value")), try unit.number("round_kg"), "\(unit)")
                    seen += 1
                }
            }
        }
        XCTAssertGreaterThanOrEqual(seen, 25)
    }

    func testTheContextComesFromTheClockTime() throws {
        let cases = try Vectors.load("body_vectors.json").list("context_cases")
        XCTAssertGreaterThanOrEqual(cases.count, 20)
        for c in cases {
            let kind = try XCTUnwrap(Body.Kind(rawValue: try c.text("kind")))
            let minutes = (c["minutes"] as? NSNumber)?.intValue
            XCTAssertEqual(Body.context(kind, minutes: minutes), try c.text("context"), "\(c)")
            XCTAssertEqual(Body.context(kind, time: c.optionalText("time")), try c.text("context"), "\(c)")
        }
    }

    func testAWatchIsAnySourceNamedWatch() throws {
        let body = try Vectors.load("body_vectors.json").list("watch_cases")
        for c in body {
            XCTAssertEqual(Body.isWatchSource(c.optionalText("name")), c["watch"] as? Bool, "\(c)")
        }
        let apple = try XCTUnwrap(try Vectors.load("apple_health_vectors.json")["watch"] as? [[Any]])
        for pair in apple {
            XCTAssertEqual(Body.isWatchSource(pair[0] as? String), pair[1] as? Bool, "\(pair)")
        }
        XCTAssertGreaterThanOrEqual(body.count + apple.count, 20)
    }

    func testSHA256() throws {
        let cases = try Vectors.load("apple_health_vectors.json").list("sha256")
        for c in cases {
            var text = c.optionalText("text") ?? ""
            if let repeated = c["repeat"] as? [String: Any] {
                text = String(repeating: try repeated.text("text"), count: try repeated.int("count"))
            }
            let digest = try c.text("digest")
            let name = try c.text("name")
            XCTAssertEqual(String(SHA256.hex(text).prefix(digest.count)), digest, name)
        }
        XCTAssertGreaterThanOrEqual(cases.count, 3)
    }

    func testEveryRowOfTheHealthExportCasesHasTheSameKeyAndContext() throws {
        var seen = 0
        for c in try Vectors.load("apple_health_vectors.json").list("cases") {
            let expected = try c.object("expected")
            for (kind, rows) in [(Body.Kind.weight, try expected.list("weights")), (.reading, try expected.list("readings"))] {
                for row in rows {
                    XCTAssertEqual(Push.sourceKey(try row.text("key_input")), try row.text("source_key"), "\(row)")
                    XCTAssertEqual(Body.context(kind, time: try row.text("time")), try row.text("context"), "\(row)")
                    if kind == .weight {
                        XCTAssertTrue(Body.isPlausible(kg: try row.number("kg")), "\(row)")
                    } else {
                        XCTAssertTrue(Body.isPlausible(systolic: try row.int("systolic"), diastolic: try row.int("diastolic")), "\(row)")
                    }
                    seen += 1
                }
            }
        }
        XCTAssertGreaterThanOrEqual(seen, 20)
    }

    func testTheFirstSyncStartsWhereTheHealthImportStarts() throws {
        let apple = try Vectors.load("apple_health_vectors.json")
        for c in try apple.list("default_since") {
            XCTAssertEqual(Push.defaultSince(try c.text("today")), try c.text("since"), "\(c)")
        }
        for bad in try XCTUnwrap(apple["default_since_errors"] as? [Any]) {
            if let text = bad as? String { XCTAssertNil(Push.defaultSince(text), text) }
        }
    }

    func testRowsAreSplitIntoBatches() throws {
        let apple = try Vectors.load("apple_health_vectors.json")
        for c in try apple.list("batches") {
            let rows = Array(0..<(try c.int("count")))
            let sizes = try Body.batches(rows, size: try c.int("size")).map(\.count)
            XCTAssertEqual(sizes, c["sizes"] as? [Int], "\(c)")
        }
        for bad in [0, -1] {
            XCTAssertThrowsError(try Body.batches([1, 2, 3], size: bad))
        }
    }
}
