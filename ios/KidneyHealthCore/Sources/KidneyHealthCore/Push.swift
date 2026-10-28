// The request of POST /push/v1/body and the server's checks on each row (app/push.py), for the iOS Health sync app.
// One row the server refuses makes the whole request a 400 and nothing is stored, so the app checks every row the same way
// first and leaves out what the server would refuse. tests/data/push_vectors.json holds the server's answers.
import Foundation

public enum Push {
    public static let path = "/push/v1/body"
    /// Weights and readings together, in one request.
    public static let maxRows = 50
    public static let maxBodyBytes = 32 * 1024
    public static let maxSourceChars = 60

    // MARK: - The moment a sample was taken

    /// A sample's time as the person's clock showed it: the `date` and `time` the server stores, and the `stamp` its key holds
    /// (`YYYY-MM-DD HH:MM:SS +HHMM`, the form the Health export writes). Nothing is converted to UTC.
    public struct Moment: Equatable, Sendable {
        public let date: String
        public let time: String
        public let stamp: String
        public let minutes: Int
    }

    /// The `at` text to send for an instant in a time zone, `YYYY-MM-DDTHH:MM:SS±HH:MM` (seconds, no fraction).
    public static func at(_ instant: Date, in zone: TimeZone) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = zone
        let whole = Date(timeIntervalSince1970: (instant.timeIntervalSince1970).rounded(.down))
        let c = calendar.dateComponents([.year, .month, .day, .hour, .minute, .second], from: whole)
        let offset = zone.secondsFromGMT(for: whole)
        let sign = offset < 0 ? "-" : "+"
        let magnitude = abs(offset) / 60
        return pad(c.year!, 4) + "-" + pad(c.month!, 2) + "-" + pad(c.day!, 2) + "T" + pad(c.hour!, 2) + ":" + pad(c.minute!, 2) + ":"
            + pad(c.second!, 2) + sign + pad(magnitude / 60, 2) + ":" + pad(magnitude % 60, 2)
    }

    /// What the server reads from an `at` text, or nil where it answers 400. The rules of `parse_at`: ISO 8601 with its zone
    /// (`Z`, `±HH`, `±HHMM` or `±HH:MM`), `T` or a space between date and time, seconds and a fraction optional, ASCII digits only.
    public static func moment(_ text: String) -> Moment? {
        let b = Array(stripped(text).utf8)
        var i = 0
        func digits(_ count: Int) -> Int? {
            guard i + count <= b.count else { return nil }
            var value = 0
            for byte in b[i..<i + count] {
                guard byte >= 0x30 && byte <= 0x39 else { return nil }
                value = value * 10 + Int(byte - 0x30)
            }
            i += count
            return value
        }
        func take(_ byte: UInt8) -> Bool {
            guard i < b.count, b[i] == byte else { return false }
            i += 1
            return true
        }
        guard let year = digits(4), take(0x2d), let month = digits(2), take(0x2d), let day = digits(2) else { return nil }
        guard take(0x54) || take(0x20), let hour = digits(2), take(0x3a), let minute = digits(2) else { return nil }
        var second = 0
        if take(0x3a) {
            guard let s = digits(2) else { return nil }
            second = s
            if take(0x2e) || take(0x2c) {
                var count = 0
                while count < 9, i < b.count, b[i] >= 0x30 && b[i] <= 0x39 { i += 1; count += 1 }
                if count == 0 { return nil }
            }
        }
        _ = take(0x20)
        var offset: String?
        if take(0x5a) {
            offset = "+0000"
        } else if i < b.count, b[i] == 0x2b || b[i] == 0x2d {
            let sign = b[i] == 0x2b ? "+" : "-"
            i += 1
            guard let hours = digits(2) else { return nil }
            var minutes = 0
            if i < b.count {
                _ = take(0x3a)
                guard let m = digits(2) else { return nil }
                minutes = m
            }
            guard hours <= 23 && minutes <= 59 else { return nil }
            offset = sign + pad(hours, 2) + pad(minutes, 2)
        }
        guard i == b.count, let offset else { return nil }
        guard hour <= 23, minute <= 59, second <= 59, isCalendarDate(year, month, day) else { return nil }
        let dayText = pad(year, 4) + "-" + pad(month, 2) + "-" + pad(day, 2)
        let time = pad(hour, 2) + ":" + pad(minute, 2)
        return Moment(date: dayText, time: time, stamp: "\(dayText) \(time):\(pad(second, 2)) \(offset)", minutes: hour * 60 + minute)
    }

    // MARK: - Values and sources

    /// The text to send as a weight's `value` for a number the app holds: the server's text for the same JSON number (its
    /// shortest form when that is 1 to 3 digits and up to 3 decimals, else the number to 3 decimals), or nil where the server
    /// would refuse it. The key is built from this text, so sending it gives the key that sending the number would.
    public static func valueText(_ value: Double) -> String? {
        guard value.isFinite, abs(value) < 1e9 else { return nil }
        let shortest = "\(value)"
        if isPlainDecimal(shortest) { return shortest }
        var text = String(format: "%.3f", value)
        while text.hasSuffix("0") { text.removeLast() }
        if text.hasSuffix(".") { text.removeLast() }
        return isPlainDecimal(text) ? text : nil
    }

    /// A source name as the server keeps it (NFC, no control or format characters, single spaces), or nil when it is empty or
    /// longer than 60 characters after that.
    public static func cleanSource(_ raw: String) -> String? {
        let nfc = raw.precomposedStringWithCanonicalMapping
        var words: [String] = []
        var word = String.UnicodeScalarView()
        for scalar in nfc.unicodeScalars {
            switch scalar.properties.generalCategory {
            case .control, .format, .surrogate, .privateUse, .unassigned:
                continue
            default:
                break
            }
            if isPythonSpace(scalar) {
                if !word.isEmpty { words.append(String(word)); word = String.UnicodeScalarView() }
            } else {
                word.append(scalar)
            }
        }
        if !word.isEmpty { words.append(String(word)) }
        let text = words.joined(separator: " ")
        guard !text.isEmpty, text.unicodeScalars.count <= maxSourceChars else { return nil }
        return text
    }

    // MARK: - Rows

    /// A weight as the request sends it. `value` is a decimal text in `unit` (`kg` or `lb`).
    public struct Weight: Codable, Equatable, Sendable {
        public let at: String
        public let value: String
        public let unit: String
        public let source: String

        public init(at: String, value: String, unit: String, source: String) {
            self.at = at; self.value = value; self.unit = unit; self.source = source
        }
    }

    /// A blood pressure reading as the request sends it: the two numbers as whole numbers.
    public struct Reading: Codable, Equatable, Sendable {
        public let at: String
        public let systolic: Int
        public let diastolic: Int
        public let source: String

        public init(at: String, systolic: Int, diastolic: Int, source: String) {
            self.at = at; self.systolic = systolic; self.diastolic = diastolic; self.source = source
        }
    }

    /// A blood pressure number as the request sends it: HealthKit holds a double, the server takes whole numbers, and the
    /// Health export import rounds half up the same way.
    public static func wholeMmHg(_ value: Double) -> Int? {
        guard value.isFinite, abs(value) < 10_000 else { return nil }
        return Int(Body.halfUp(value, places: 0))
    }

    /// What the server makes of a weight it accepts.
    public struct PlannedWeight: Equatable, Sendable {
        public let date: String
        public let time: String
        public let kg: Double
        public let context: String
        public let keyText: String
        public let key: String
    }

    /// What the server makes of a reading it accepts. A reading from a watch is accepted and counted, but not stored.
    public struct PlannedReading: Equatable, Sendable {
        public let date: String
        public let time: String
        public let systolic: Int
        public let diastolic: Int
        public let context: String
        public let keyText: String
        public let key: String
        public let watch: Bool
    }

    /// The field the server names when it refuses a row.
    public enum Field: String, Equatable, Sendable {
        case at, value, unit, source, systolic, diastolic
    }

    /// The server's checks on one weight, in its order: `at`, `value`, `source`, then the date and the range. `today` is the
    /// person's date (`YYYY-MM-DD`); a date more than one day after it is refused, as is one before 1900.
    public static func plan(_ row: Weight, today: String) -> Result<PlannedWeight, Refusal> {
        guard let moment = moment(row.at) else { return .failure(Refusal(.at)) }
        let text = stripped(row.value)
        guard isPlainDecimal(text), let number = Double(text) else { return .failure(Refusal(.value)) }
        guard row.unit == "kg" || row.unit == "lb" else { return .failure(Refusal(.unit)) }
        guard let source = cleanSource(row.source) else { return .failure(Refusal(.source)) }
        guard isAllowedDate(moment.date, today: today) else { return .failure(Refusal(.at)) }
        let kg = row.unit == "lb" ? Body.lbToKg(number) : Body.roundKg(number)
        guard Body.isPlausible(kg: kg) else { return .failure(Refusal(.value)) }
        let keyText = "\(Body.weightType)|\(moment.stamp)|\(text)|\(source)"
        return .success(PlannedWeight(date: moment.date, time: moment.time, kg: kg, context: Body.context(.weight, minutes: moment.minutes),
                                      keyText: keyText, key: sourceKey(keyText)))
    }

    /// The server's checks on one reading, in its order: `at`, the two numbers, `source`, the date, the ranges, then
    /// systolic above diastolic.
    public static func plan(_ row: Reading, today: String) -> Result<PlannedReading, Refusal> {
        guard let moment = moment(row.at) else { return .failure(Refusal(.at)) }
        guard (0...999).contains(row.systolic) else { return .failure(Refusal(.systolic)) }
        guard (0...999).contains(row.diastolic) else { return .failure(Refusal(.diastolic)) }
        guard let source = cleanSource(row.source) else { return .failure(Refusal(.source)) }
        guard isAllowedDate(moment.date, today: today) else { return .failure(Refusal(.at)) }
        guard Body.systolicRange.contains(row.systolic) else { return .failure(Refusal(.systolic)) }
        guard Body.diastolicRange.contains(row.diastolic) else { return .failure(Refusal(.diastolic)) }
        guard row.systolic > row.diastolic else { return .failure(Refusal(.systolic)) }
        let keyText = "BloodPressure|\(moment.stamp)|\(row.systolic)/\(row.diastolic)|\(source)"
        return .success(PlannedReading(date: moment.date, time: moment.time, systolic: row.systolic, diastolic: row.diastolic,
                                       context: Body.context(.reading, minutes: moment.minutes), keyText: keyText,
                                       key: sourceKey(keyText), watch: Body.isWatchSource(source)))
    }

    public struct Refusal: Error, Equatable, Sendable {
        public let field: Field
        public init(_ field: Field) { self.field = field }
    }

    /// The first 32 hex characters of the SHA-256 of the key text: the key the server and the Health export import build.
    public static func sourceKey(_ text: String) -> String { String(SHA256.hex(text).prefix(32)) }

    // MARK: - Requests

    /// One request body: `{"weights": [...], "readings": [...]}`.
    public struct Request: Codable, Equatable, Sendable {
        public let weights: [Weight]
        public let readings: [Reading]

        public init(weights: [Weight], readings: [Reading]) {
            self.weights = weights
            self.readings = readings
        }
    }

    /// The rows the app sends, and what it left out because the server would refuse them or not store them.
    public struct Plan: Equatable, Sendable {
        /// The request bodies, each with at most 50 rows, in the order the rows were given (weights first).
        public let requests: [Request]
        /// Rows the server would refuse, by the field it would name.
        public let refused: [Field: Int]
        /// Readings from a watch: the server counts them and stores nothing.
        public let watchReadings: Int
    }

    /// Checks every row, leaves out what the server would refuse and the readings from a watch, and splits the rest into
    /// requests of at most 50 rows. The per-day limits count rows already on the server, so only the server can check them.
    public static func plan(weights: [Weight], readings: [Reading], today: String) -> Plan {
        var refused: [Field: Int] = [:]
        var watch = 0
        var rows: [Row] = []
        for weight in weights {
            switch plan(weight, today: today) {
            case .success: rows.append(.weight(weight))
            case .failure(let refusal): refused[refusal.field, default: 0] += 1
            }
        }
        for reading in readings {
            switch plan(reading, today: today) {
            case .success(let planned) where planned.watch: watch += 1
            case .success: rows.append(.reading(reading))
            case .failure(let refusal): refused[refusal.field, default: 0] += 1
            }
        }
        let requests = stride(from: 0, to: rows.count, by: maxRows).map { start -> Request in
            let slice = rows[start..<min(start + maxRows, rows.count)]
            return Request(weights: slice.compactMap { if case .weight(let w) = $0 { w } else { nil } },
                        readings: slice.compactMap { if case .reading(let r) = $0 { r } else { nil } })
        }
        return Plan(requests: requests, refused: refused, watchReadings: watch)
    }

    /// The JSON bytes of a request body.
    public static func encode(_ body: Request) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return try encoder.encode(body)
    }

    private enum Row {
        case weight(Weight)
        case reading(Reading)
    }

    /// The first day the first sync sends: three months before `today`, on the same day of the month or the last day of a
    /// shorter month. The Health export import offers the same start (`defaultSince` in js/engine/apple_health.js). Nil for a
    /// `today` that is not a date.
    public static func defaultSince(_ today: String) -> String? {
        let parts = today.split(separator: "-", omittingEmptySubsequences: false)
        guard parts.count == 3, parts[0].count == 4, parts[1].count == 2, parts[2].count == 2,
              let y = Int(parts[0]), let m = Int(parts[1]), let d = Int(parts[2]), isCalendarDate(y, m, d) else { return nil }
        var (year, month) = (y, m - 3)
        if month < 1 { (year, month) = (year - 1, month + 12) }
        var day = d
        while !isCalendarDate(year, month, day) { day -= 1 }
        return pad(year, 4) + "-" + pad(month, 2) + "-" + pad(day, 2)
    }

    // MARK: - Helpers

    private static func pad(_ value: Int, _ width: Int) -> String {
        let text = String(value)
        return text.count >= width ? text : String(repeating: "0", count: width - text.count) + text
    }

    /// 1 to 3 ASCII digits, then optionally a point and 1 to 3 ASCII digits.
    static func isPlainDecimal(_ text: String) -> Bool {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 1 || parts.count == 2 else { return false }
        return parts.allSatisfy { part in (1...3).contains(part.count) && part.utf8.allSatisfy { $0 >= 0x30 && $0 <= 0x39 } }
    }

    private static func isCalendarDate(_ year: Int, _ month: Int, _ day: Int) -> Bool {
        guard year >= 1, (1...12).contains(month), day >= 1 else { return false }
        let leap = (year % 4 == 0 && year % 100 != 0) || year % 400 == 0
        let days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
        return day <= days
    }

    /// Not before 1900 and not more than one day after `today`.
    private static func isAllowedDate(_ date: String, today: String) -> Bool {
        guard date >= "1900-01-01" else { return false }
        guard let latest = dayAfter(today) else { return true }
        return date <= latest
    }

    private static func dayAfter(_ day: String) -> String? {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 3, isCalendarDate(parts[0], parts[1], parts[2]) else { return nil }
        var (year, month, date) = (parts[0], parts[1], parts[2] + 1)
        if !isCalendarDate(year, month, date) { (month, date) = (month + 1, 1) }
        if month > 12 { (year, month) = (year + 1, 1) }
        return pad(year, 4) + "-" + pad(month, 2) + "-" + pad(date, 2)
    }

    /// Python's `str.isspace` for the characters left after the control and format characters are removed.
    private static func isPythonSpace(_ scalar: Unicode.Scalar) -> Bool {
        scalar.properties.isWhitespace || (0x1c...0x1f).contains(scalar.value)
    }

    /// Python's `str.strip()`: whitespace removed from both ends.
    private static func stripped(_ text: String) -> String {
        var scalars = Substring(text).unicodeScalars[...]
        while let first = scalars.first, isPythonSpace(first) { scalars.removeFirst() }
        while let last = scalars.last, isPythonSpace(last) { scalars.removeLast() }
        return String(scalars)
    }
}
