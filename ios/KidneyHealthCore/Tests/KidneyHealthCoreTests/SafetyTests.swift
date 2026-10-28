// The app reads three Health types and nothing else (design note 15 §4.2, §5; CLAUDE.md: no insulin or medicine data).
import XCTest
@testable import KidneyHealthCore

final class SafetyTests: XCTestCase {
    func testTheAppReadsOnlyWeightAndBloodPressure() {
        XCTAssertEqual(Body.readTypes, [
            "HKQuantityTypeIdentifierBodyMass",
            "HKQuantityTypeIdentifierBloodPressureSystolic",
            "HKQuantityTypeIdentifierBloodPressureDiastolic",
        ])
        for type in Body.readTypes {
            for word in ["Glucose", "Insulin", "Medication", "Carbohydrates", "Dietary"] {
                XCTAssertFalse(type.localizedCaseInsensitiveContains(word), type)
            }
        }
    }
}
