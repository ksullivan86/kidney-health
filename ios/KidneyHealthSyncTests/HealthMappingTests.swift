// HealthKit samples become the package's plain values: units, the two numbers of a reading, the time zone and the source.
import HealthKit
import KidneyHealthCore
import XCTest
@testable import KidneyHealthSync

final class HealthMappingTests: XCTestCase {
    let start = Date(timeIntervalSince1970: 1_792_667_700)

    func testAWeightIsReadInThePersonsUnit() {
        let sample = HKQuantitySample(type: HKQuantityType(.bodyMass), quantity: HKQuantity(unit: .pound(), doubleValue: 154.3),
                                      start: start, end: start, metadata: [HKMetadataKeyTimeZone: "America/New_York"])
        let pounds = HealthMapping.weight(sample, unit: .lb)
        XCTAssertEqual(pounds.unit, .lb)
        XCTAssertEqual(pounds.value, 154.3, accuracy: 1e-9)
        XCTAssertEqual(pounds.row.at, "2026-10-22T07:15:00-04:00")
        XCTAssertEqual(pounds.row.value, "154.3")
        let kilograms = HealthMapping.weight(sample, unit: .kg)
        XCTAssertEqual(kilograms.unit, .kg)
        XCTAssertEqual(kilograms.value, 154.3 * Body.kgPerLb, accuracy: 1e-9)
    }

    func testAReadingIsTheTwoNumbersOfItsCorrelation() throws {
        let mmHg = HKUnit.millimeterOfMercury()
        let top = HKQuantitySample(type: HKQuantityType(.bloodPressureSystolic), quantity: HKQuantity(unit: mmHg, doubleValue: 122),
                                   start: start, end: start)
        let bottom = HKQuantitySample(type: HKQuantityType(.bloodPressureDiastolic), quantity: HKQuantity(unit: mmHg, doubleValue: 78),
                                      start: start, end: start)
        let pair = HKCorrelation(type: HKCorrelationType(.bloodPressure), start: start, end: start, objects: [top, bottom],
                                 metadata: [HKMetadataKeyTimeZone: "Europe/Berlin"])
        let reading = try XCTUnwrap(HealthMapping.reading(pair))
        XCTAssertEqual(reading.row.systolic, 122)
        XCTAssertEqual(reading.row.diastolic, 78)
        XCTAssertEqual(reading.row.at, "2026-10-22T13:15:00+02:00")
        XCTAssertFalse(reading.source.isEmpty)
    }

    func testHalfAPairIsNoReading() {
        let top = HKQuantitySample(type: HKQuantityType(.bloodPressureSystolic),
                                   quantity: HKQuantity(unit: .millimeterOfMercury(), doubleValue: 122), start: start, end: start)
        let pair = HKCorrelation(type: HKCorrelationType(.bloodPressure), start: start, end: start, objects: [top])
        XCTAssertNil(HealthMapping.reading(pair))
    }

    func testWithoutAZoneThePhonesZoneIsUsed() {
        let sample = HKQuantitySample(type: HKQuantityType(.bodyMass), quantity: HKQuantity(unit: .gramUnit(with: .kilo), doubleValue: 70),
                                      start: start, end: start)
        XCTAssertEqual(HealthMapping.zone(of: sample), TimeZone.current)
    }

    func testTheAppAsksToReadExactlyThreeTypesAndToWriteNone() {
        XCTAssertEqual(HealthSource.readTypes, [HKQuantityType(.bodyMass), HKQuantityType(.bloodPressureSystolic),
                                                HKQuantityType(.bloodPressureDiastolic)])
    }

    func testAnchorsSurviveTheKeychainForm() {
        XCTAssertNil(Anchors(nil).weights)
        XCTAssertNil(Anchors(Data("not json".utf8)).readings)
        let empty = Anchors(weights: nil, readings: nil).encoded
        XCTAssertNotNil(empty)
        XCTAssertNil(Anchors(empty).weights)
    }
}
