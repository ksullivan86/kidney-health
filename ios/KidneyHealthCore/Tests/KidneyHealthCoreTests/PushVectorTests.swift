// push_vectors.json: what POST /push/v1/body makes of each row (tests/data/gen_push_vectors.py, from app/push.py).
import Foundation
import XCTest
@testable import KidneyHealthCore

final class PushVectorTests: XCTestCase {
    /// The vectors never depend on the server's date; any day after their rows works here.
    let today = "2026-10-28"

    func testTheLimitsAreTheRoutes() throws {
        let k = try Vectors.load("push_vectors.json").object("constants")
        XCTAssertEqual(try k.text("path"), Push.path)
        XCTAssertEqual(try k.int("max_rows"), Push.maxRows)
        XCTAssertEqual(try k.int("max_body_bytes"), Push.maxBodyBytes)
        XCTAssertEqual(try k.int("max_source_chars"), Push.maxSourceChars)
        XCTAssertEqual(try k.int("max_weights_per_day"), Body.maxWeightsPerDay)
        XCTAssertEqual(try k.int("max_readings_per_day"), Body.maxReadingsPerDay)
        XCTAssertEqual(try k.text("weight_type"), Body.weightType)
    }

    func testAnInstantIsSentAsTheWallClockOfItsZone() throws {
        let cases = try Vectors.load("push_vectors.json").list("clock_cases")
        for c in cases {
            let name = try c.text("zone")
            let zone = try XCTUnwrap(TimeZone(identifier: name), name)
            let at = Push.at(Date(timeIntervalSince1970: try c.number("epoch")), in: zone)
            XCTAssertEqual(at, try c.text("at"), "\(c)")
            let moment = try XCTUnwrap(Push.moment(at), at)
            XCTAssertEqual(moment.date, try c.text("date"), at)
            XCTAssertEqual(moment.time, try c.text("time"), at)
            XCTAssertEqual(moment.stamp, try c.text("stamp"), at)
        }
        XCTAssertGreaterThanOrEqual(cases.count, 15)
    }

    func testTheAtTextIsReadAsTheServerReadsIt() throws {
        for c in try Vectors.load("push_vectors.json").list("at_cases") {
            let at = try c.text("at")
            if c["refused"] as? Bool == true {
                XCTAssertNil(Push.moment(at), "the server refuses \(at.debugDescription)")
            } else {
                let moment = try XCTUnwrap(Push.moment(at), "the server reads \(at.debugDescription)")
                XCTAssertEqual(moment.date, try c.text("date"), at)
                XCTAssertEqual(moment.time, try c.text("time"), at)
                XCTAssertEqual(moment.stamp, try c.text("stamp"), at)
            }
        }
    }

    func testAWeightIsSentAsTheTextTheServerBuildsItsKeyFrom() throws {
        for c in try Vectors.load("push_vectors.json").list("value_cases") {
            XCTAssertEqual(Push.valueText(try c.number("number")), c.optionalText("text"), "\(c)")
        }
    }

    func testTheSourceIsCleanedAsTheServerCleansIt() throws {
        for c in try Vectors.load("push_vectors.json").list("source_cases") {
            let source = try c.text("source")
            XCTAssertEqual(Push.cleanSource(source), c.optionalText("kept"), source.debugDescription)
        }
    }

    func testEachWeightIsPlannedOrRefusedAsTheServerDoes() throws {
        var planned = 0
        for c in try Vectors.load("push_vectors.json").list("weight_cases") {
            let row = try c.object("row")
            let weight = Push.Weight(at: try row.text("at"), value: try row.text("value"), unit: try row.text("unit"),
                                     source: try row.text("source"))
            switch Push.plan(weight, today: today) {
            case .success(let got):
                let want = try c.object("planned")
                XCTAssertNil(c["refused"], "the server refuses \(row)")
                XCTAssertEqual(got.date, try want.text("date"))
                XCTAssertEqual(got.time, try want.text("time"))
                XCTAssertEqual(got.kg, try want.number("kg"), "\(row)")
                XCTAssertEqual(got.context, try want.text("context"), "\(row)")
                XCTAssertEqual(got.keyText, try want.text("key_text"), "\(row)")
                XCTAssertEqual(got.key, try want.text("key"), "\(row)")
                planned += 1
            case .failure(let refusal):
                XCTAssertEqual(refusal.field.rawValue, c.optionalText("refused"), "\(row)")
            }
        }
        XCTAssertGreaterThanOrEqual(planned, 8)
    }

    func testEachReadingIsPlannedOrRefusedAsTheServerDoes() throws {
        var planned = 0
        for c in try Vectors.load("push_vectors.json").list("reading_cases") {
            let row = try c.object("row")
            // The app sends whole numbers. A text the server reads as no whole number of 3 digits or fewer must be refused there.
            guard let systolic = Int(try row.text("systolic")), let diastolic = Int(try row.text("diastolic")) else {
                XCTAssertEqual(c.optionalText("refused"), "systolic", "\(row)")
                continue
            }
            let reading = Push.Reading(at: try row.text("at"), systolic: systolic, diastolic: diastolic, source: try row.text("source"))
            switch Push.plan(reading, today: today) {
            case .success(let got):
                let want = try c.object("planned")
                XCTAssertNil(c["refused"], "the server refuses \(row)")
                XCTAssertEqual(got.date, try want.text("date"))
                XCTAssertEqual(got.time, try want.text("time"))
                XCTAssertEqual(got.systolic, try want.int("systolic"))
                XCTAssertEqual(got.diastolic, try want.int("diastolic"))
                XCTAssertEqual(got.context, try want.text("context"), "\(row)")
                XCTAssertEqual(got.keyText, try want.text("key_text"), "\(row)")
                XCTAssertEqual(got.key, try want.text("key"), "\(row)")
                XCTAssertEqual(got.watch, want["watch"] as? Bool, "\(row)")
                planned += 1
            case .failure(let refusal):
                XCTAssertEqual(refusal.field.rawValue, c.optionalText("refused"), "\(row)")
            }
        }
        XCTAssertGreaterThanOrEqual(planned, 8)
    }
}
