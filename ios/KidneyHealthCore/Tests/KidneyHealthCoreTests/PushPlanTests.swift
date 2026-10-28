// The parts of a sync the vectors cannot pin: the date limit against today, the requests of at most 50 rows, what is left out,
// and the size of a request.
import Foundation
import XCTest
@testable import KidneyHealthCore

final class PushPlanTests: XCTestCase {
    private func weight(_ at: String = "2026-10-19T07:15:00-04:00", value: String = "70.5", source: String = "Health") -> Push.Weight {
        Push.Weight(at: at, value: value, unit: "kg", source: source)
    }

    private func reading(_ at: String = "2026-10-19T07:20:00-04:00", source: String = "Omron") -> Push.Reading {
        Push.Reading(at: at, systolic: 122, diastolic: 78, source: source)
    }

    func testADateMayBeOneDayAfterTodayButNotTwo() {
        XCTAssertNoThrow(try Push.plan(weight("2026-10-29T07:15:00+14:00"), today: "2026-10-28").get())
        XCTAssertEqual(Push.plan(weight("2026-10-30T07:15:00Z"), today: "2026-10-28"), .failure(Push.Refusal(.at)))
        XCTAssertNoThrow(try Push.plan(weight("2027-01-01T07:15:00Z"), today: "2026-12-31").get())
        XCTAssertNoThrow(try Push.plan(weight("2024-03-01T07:15:00Z"), today: "2024-02-29").get())
        XCTAssertEqual(Push.plan(weight("2024-03-01T07:15:00Z"), today: "2024-02-28"), .failure(Push.Refusal(.at)))
        XCTAssertEqual(Push.plan(reading("1899-12-31T23:59:00Z"), today: "2026-10-28"), .failure(Push.Refusal(.at)))
    }

    func testRequestsHoldAtMost50RowsInTheOrderGiven() throws {
        let weights = (0..<70).map { weight(value: String(60 + Double($0) / 10)) }
        let readings = (0..<40).map { _ in reading() }
        let plan = Push.plan(weights: weights, readings: readings, today: "2026-10-28")
        XCTAssertEqual(plan.requests.map { $0.weights.count + $0.readings.count }, [50, 50, 10])
        XCTAssertEqual(plan.requests.map(\.weights.count), [50, 20, 0])
        XCTAssertEqual(plan.requests.flatMap(\.weights), weights)
        XCTAssertEqual(plan.requests.flatMap(\.readings), readings)
        XCTAssertEqual(plan.refused, [:])
        XCTAssertEqual(plan.watchReadings, 0)
    }

    func testWhatTheServerWouldRefuseOrNotStoreIsLeftOutAndCounted() {
        let plan = Push.plan(
            weights: [weight(), weight(value: "19"), weight(source: " "), weight("2026-10-19T07:15:00")],
            readings: [reading(), reading(source: "Sam’s Apple Watch"), Push.Reading(at: "2026-10-19T07:20:00Z", systolic: 80, diastolic: 90, source: "Omron")],
            today: "2026-10-28")
        XCTAssertEqual(plan.requests, [Push.Request(weights: [weight()], readings: [reading()])])
        XCTAssertEqual(plan.refused, [.value: 1, .source: 1, .at: 1, .systolic: 1])
        XCTAssertEqual(plan.watchReadings, 1)
    }

    func testNothingToSendIsNoRequest() {
        XCTAssertEqual(Push.plan(weights: [], readings: [], today: "2026-10-28").requests, [])
        XCTAssertEqual(Push.plan(weights: [], readings: [reading(source: "Apple Watch")], today: "2026-10-28").requests, [])
    }

    func testTheLargestRequestFitsUnderTheServersCap() throws {
        // 50 rows with the longest source, in characters that take the most bytes once encoded.
        let source = String(repeating: "\u{10FFFD}", count: 59) + "\""
        XCTAssertEqual(Push.cleanSource(source), "\"") // private-use characters are removed, as the server removes them
        let longest = String(repeating: "€", count: 59) + "\""
        XCTAssertEqual(Push.cleanSource(longest), longest)
        let rows = (0..<50).map { _ in Push.Weight(at: "2026-10-19T07:15:00-04:00", value: "154.325", unit: "lb", source: longest) }
        let plan = Push.plan(weights: rows, readings: [], today: "2026-10-28")
        XCTAssertEqual(plan.requests.count, 1)
        let bytes = try Push.encode(plan.requests[0])
        XCTAssertLessThan(bytes.count, Push.maxBodyBytes)
        let decoded = try JSONDecoder().decode(Push.Request.self, from: bytes)
        XCTAssertEqual(decoded, plan.requests[0])
    }

    func testTheRequestIsTheShapeTheServerTakes() throws {
        let bytes = try Push.encode(Push.Request(weights: [weight()], readings: [reading()]))
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: bytes) as? [String: [[String: Any]]])
        XCTAssertEqual(Set(object.keys), ["weights", "readings"])
        XCTAssertEqual(Set(try XCTUnwrap(object["weights"]?.first).keys), ["at", "value", "unit", "source"])
        XCTAssertEqual(Set(try XCTUnwrap(object["readings"]?.first).keys), ["at", "systolic", "diastolic", "source"])
        XCTAssertEqual(object["weights"]?.first?["value"] as? String, "70.5")
        XCTAssertEqual(object["readings"]?.first?["systolic"] as? Int, 122)
    }

    func testBloodPressureNumbersAreRoundedHalfUpToWholeNumbers() {
        XCTAssertEqual(Push.wholeMmHg(119.5), 120)
        XCTAssertEqual(Push.wholeMmHg(119.49), 119)
        XCTAssertEqual(Push.wholeMmHg(78), 78)
        XCTAssertNil(Push.wholeMmHg(.nan))
    }

    func testAnInstantKeepsWholeSecondsAndTheOffsetOfThatMoment() throws {
        let zone = try XCTUnwrap(TimeZone(identifier: "America/St_Johns"))
        XCTAssertEqual(Push.at(Date(timeIntervalSince1970: 1_792_667_700.999), in: zone), "2026-10-22T08:45:00-02:30")
    }
}
