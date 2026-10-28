// Reads new weights and blood pressure readings from Health (design note 15 §4.2, facts I1 to I3). It asks for exactly the
// three read types of Body.readTypes, never asks to write, and keeps no values: they go straight into the request.
import Foundation
import HealthKit
import KidneyHealthCore

final class HealthSource {
    /// At most this many new samples of each kind per round, so a round fits in a few requests and its anchor can be kept.
    static let roundSize = 500

    let store = HKHealthStore()

    static var available: Bool { HKHealthStore.isHealthDataAvailable() }

    /// Weight and the two blood pressure numbers, from the package's list. A reading's correlation needs no type of its own.
    static var readTypes: Set<HKObjectType> {
        Set(Body.readTypes.map { HKQuantityType(HKQuantityTypeIdentifier(rawValue: $0)) })
    }

    func requestAccess() async throws {
        try await store.requestAuthorization(toShare: [], read: Self.readTypes)
    }

    /// The samples saved since the anchors in `stored`, at most `roundSize` of each kind, the anchors to keep once they reached the
    /// server, and whether there may be more.
    func newSamples(since stored: Data?) async throws -> (batch: SampleBatch, more: Bool) {
        let anchors = Anchors(stored)
        let weightQuery = HKAnchoredObjectQueryDescriptor(
            predicates: [.quantitySample(type: HKQuantityType(.bodyMass))], anchor: anchors.weights, limit: Self.roundSize)
        let weights = try await weightQuery.result(for: store)
        let readingQuery = HKAnchoredObjectQueryDescriptor(
            predicates: [.correlation(type: HKCorrelationType(.bloodPressure))], anchor: anchors.readings, limit: Self.roundSize)
        let readings = try await readingQuery.result(for: store)
        let unit = await preferredWeightUnit()
        let batch = SampleBatch(
            weights: weights.addedSamples.map { HealthMapping.weight($0, unit: unit) },
            readings: readings.addedSamples.compactMap(HealthMapping.reading),
            anchor: Anchors(weights: weights.newAnchor, readings: readings.newAnchor).encoded)
        let more = weights.addedSamples.count >= Self.roundSize || readings.addedSamples.count >= Self.roundSize
        return (batch, more)
    }

    /// Calls `onChange` when Health saves a new weight or reading, also with the app in the background. A reading is saved as two
    /// samples, so watching the top number is enough.
    func observe(_ onChange: @escaping () async -> Void) {
        for type in [HKQuantityType(.bodyMass), HKQuantityType(.bloodPressureSystolic)] {
            let query = HKObserverQuery(sampleType: type, predicate: nil) { _, completion, error in
                guard error == nil else { completion(); return }
                Task {
                    await onChange()
                    completion()
                }
            }
            store.execute(query)
            store.enableBackgroundDelivery(for: type, frequency: .immediate) { _, _ in }
        }
    }

    /// Pounds when the person's Health shows weights in pounds, else kilograms. The Health export writes the value in the unit
    /// it was entered in; matching it on a real phone is a check for the owner (design note 15 §6).
    private func preferredWeightUnit() async -> WeightSample.Unit {
        let type = HKQuantityType(.bodyMass)
        guard let units = try? await store.preferredUnits(for: [type]), let unit = units[type] else { return .kg }
        return unit == HKUnit.pound() ? .lb : .kg
    }
}

/// HealthKit samples to the package's plain values.
enum HealthMapping {
    static func weight(_ sample: HKQuantitySample, unit: WeightSample.Unit) -> WeightSample {
        let hkUnit = unit == .lb ? HKUnit.pound() : HKUnit.gramUnit(with: .kilo)
        return WeightSample(start: sample.startDate, zone: zone(of: sample), value: sample.quantity.doubleValue(for: hkUnit),
                            unit: unit, source: sample.sourceRevision.source.name)
    }

    /// The two numbers of a blood pressure correlation, or nil when one is missing.
    static func reading(_ correlation: HKCorrelation) -> ReadingSample? {
        let mmHg = HKUnit.millimeterOfMercury()
        guard let top = correlation.objects(for: HKQuantityType(.bloodPressureSystolic)).first as? HKQuantitySample,
              let bottom = correlation.objects(for: HKQuantityType(.bloodPressureDiastolic)).first as? HKQuantitySample else {
            return nil
        }
        return ReadingSample(start: correlation.startDate, zone: zone(of: correlation), systolic: top.quantity.doubleValue(for: mmHg),
                             diastolic: bottom.quantity.doubleValue(for: mmHg), source: correlation.sourceRevision.source.name)
    }

    /// The time zone the sample was taken in when its source saved it, else the phone's.
    static func zone(of sample: HKSample) -> TimeZone {
        (sample.metadata?[HKMetadataKeyTimeZone] as? String).flatMap(TimeZone.init(identifier:)) ?? .current
    }
}

/// The two HealthKit anchors, kept together as one Keychain item.
struct Anchors {
    var weights: HKQueryAnchor?
    var readings: HKQueryAnchor?

    init(weights: HKQueryAnchor?, readings: HKQueryAnchor?) {
        self.weights = weights
        self.readings = readings
    }

    init(_ data: Data?) {
        guard let data, let parts = try? JSONDecoder().decode([String: Data].self, from: data) else { return }
        weights = parts["weights"].flatMap(Self.anchor)
        readings = parts["readings"].flatMap(Self.anchor)
    }

    var encoded: Data? {
        var parts: [String: Data] = [:]
        if let weights, let data = try? NSKeyedArchiver.archivedData(withRootObject: weights, requiringSecureCoding: true) {
            parts["weights"] = data
        }
        if let readings, let data = try? NSKeyedArchiver.archivedData(withRootObject: readings, requiringSecureCoding: true) {
            parts["readings"] = data
        }
        return try? JSONEncoder().encode(parts)
    }

    private static func anchor(_ data: Data) -> HKQueryAnchor? {
        try? NSKeyedUnarchiver.unarchivedObject(ofClass: HKQueryAnchor.self, from: data)
    }
}
