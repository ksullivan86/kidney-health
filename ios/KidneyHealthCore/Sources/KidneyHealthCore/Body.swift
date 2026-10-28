// The weight and blood pressure rules of app/body.py and app/models.py, for the iOS Health sync app (design note 15 §4.1).
// tests/data/body_vectors.json and apple_health_vectors.json hold the server's answers; the tests replay them.
import Foundation

public enum Body {
    /// One pound in kilograms, exactly (note 10 F7).
    public static let kgPerLb = 0.45359237

    /// The plausible ranges of a stored row (app/models.py).
    public static let kgRange: ClosedRange<Double> = 20...400
    public static let systolicRange: ClosedRange<Int> = 50...300
    public static let diastolicRange: ClosedRange<Int> = 20...200

    /// At most this many rows of one kind on one day, counting the rows already stored.
    public static let maxWeightsPerDay = 20
    public static let maxReadingsPerDay = 30

    /// The HealthKit type names, as the Health export writes them and as the key text holds them.
    public static let weightType = "HKQuantityTypeIdentifierBodyMass"
    public static let systolicType = "HKQuantityTypeIdentifierBloodPressureSystolic"
    public static let diastolicType = "HKQuantityTypeIdentifierBloodPressureDiastolic"

    /// Everything the app may ask Apple Health to read: weight and the two blood pressure numbers. Never glucose, insulin or a
    /// medicine (CLAUDE.md: no dosing data), and nothing is ever written to Health.
    public static let readTypes = [weightType, systolicType, diastolicType]

    /// Half-up rounding on the number's shortest decimal form, as the server's `_half_up` (so 70.125 gives 70.13, not 70.12).
    public static func halfUp(_ value: Double, places: Int) -> Double {
        guard value.isFinite, var exact = Decimal(string: "\(value)", locale: Locale(identifier: "en_US_POSIX")) else {
            return value
        }
        var rounded = Decimal()
        NSDecimalRound(&rounded, &exact, places, .plain)
        return Double(rounded.description) ?? value  // through the text: the Decimal-to-Double conversion is not exact
    }

    /// A weight as it is stored: kilograms, rounded half up to 0.01 kg.
    public static func roundKg(_ kg: Double) -> Double { halfUp(kg, places: 2) }

    /// Pounds to the stored kilograms (pounds × 0.45359237, then rounded half up to 0.01 kg).
    public static func lbToKg(_ lb: Double) -> Double { roundKg(lb * kgPerLb) }

    public enum Kind: String, Sendable {
        case weight
        case reading
    }

    /// The context a row gets from its clock time when the person is not asked: `morning` from 04:00 to 10:59; for a blood
    /// pressure reading also `evening` from 17:00 to 23:59; anything else, and a row with no time, is `other`.
    public static func context(_ kind: Kind, minutes: Int?) -> String {
        guard let at = minutes else { return "other" }
        if at >= 4 * 60 && at <= 10 * 60 + 59 { return "morning" }
        if kind == .reading && at >= 17 * 60 { return "evening" }
        return "other"
    }

    /// The same, from `HH:MM` on the person's clock.
    public static func context(_ kind: Kind, time: String?) -> String {
        guard let time else { return "other" }
        let parts = time.split(separator: ":")
        guard parts.count == 2, let hours = Int(parts[0]), let minutes = Int(parts[1]) else { return "other" }
        return context(kind, minutes: hours * 60 + minutes)
    }

    /// True for a source whose name contains "watch" in any letter case. Its blood pressure readings are the cuffless ones that
    /// note 10 (F4) does not recommend, and the server does not store them from a phone. A weight from a watch is kept.
    public static func isWatchSource(_ name: String?) -> Bool {
        (name ?? "").lowercased().contains("watch")
    }

    /// True when a weight in kilograms is one the server stores.
    public static func isPlausible(kg: Double) -> Bool { kgRange.contains(kg) }

    /// True when a reading is one the server stores: both numbers in range and the top one above the bottom one.
    public static func isPlausible(systolic: Int, diastolic: Int) -> Bool {
        systolicRange.contains(systolic) && diastolicRange.contains(diastolic) && systolic > diastolic
    }

    /// The rows split into groups of `size`, in the order given. No rows give no groups.
    public static func batches<T>(_ rows: [T], size: Int) throws -> [[T]] {
        guard size >= 1 else { throw BatchSizeError(size: size) }
        return stride(from: 0, to: rows.count, by: size).map { Array(rows[$0..<min($0 + size, rows.count)]) }
    }

    public struct BatchSizeError: Error, Equatable {
        public let size: Int
    }
}
