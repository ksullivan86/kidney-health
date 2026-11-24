// Design note 38, steps 2 and 3: Health rows for the log on this phone, the food services' rules, and the lock's default.
@testable import KidneyHealth
import KidneyHealthCore
import XCTest

final class PhoneTests: XCTestCase {
    func testHealthRowsArePlannedWithTheServersRules() {
        let request = Push.Request(
            weights: [Push.Weight(at: "2026-11-20T07:30:00-05:00", value: "154.5", unit: "lb", source: "Withings")],
            readings: [Push.Reading(at: "2026-11-20T07:35:00-05:00", systolic: 128, diastolic: 82, source: "Omron"),
                       Push.Reading(at: "2026-11-20T08:00:00-05:00", systolic: 120, diastolic: 80, source: "Apple Watch")])
        let rows = LocalLogTransport.rows(request, today: "2026-11-21")
        let weights = rows.body["weights"] as? [[String: Any]] ?? []
        let readings = rows.body["readings"] as? [[String: Any]] ?? []
        XCTAssertEqual(weights.count, 1)
        XCTAssertEqual(weights.first?["source"] as? String, "apple_health")
        XCTAssertEqual(weights.first?["date"] as? String, "2026-11-20")
        XCTAssertEqual(weights.first?["time"] as? String, "07:30")
        XCTAssertEqual((weights.first?["source_key"] as? String)?.count, 32)
        guard case .success(let planned) = Push.plan(request.weights[0], today: "2026-11-21") else { return XCTFail("planned") }
        XCTAssertEqual(weights.first?["source_key"] as? String, planned.key) // the same key the server and the Health import use
        XCTAssertEqual(readings.count, 1, "a reading from a watch is counted, not added")
        XCTAssertEqual(rows.watch, 1)
    }

    func testARowTheServerWouldRefuseIsLeftOut() {
        let request = Push.Request(weights: [Push.Weight(at: "not a time", value: "70", unit: "kg", source: "Scale")], readings: [])
        XCTAssertEqual((LocalLogTransport.rows(request, today: "2026-11-21").body["weights"] as? [Any])?.count, 0)
    }

    @MainActor
    func testFoodServicesAreOffUntilTurnedOnAndRefuseOddRequests() async {
        let defaults = UserDefaults(suiteName: "PhoneTests-\(UUID().uuidString)")!
        let services = FoodServices(defaults: defaults)
        XCTAssertFalse(services.usdaOn)
        XCTAssertFalse(services.offOn)
        let off = await services.answer(["kind": "offProduct", "code": "3017624010701"])
        XCTAssertEqual(off["error"] as? String, "off_off")
        for bad: [String: Any] in [["kind": "offProduct", "code": "301762401070x"], ["kind": "offProduct", "code": "12"],
                                   ["kind": "offProduct", "code": "3017624010701", "fields": "a b"], ["kind": "usdaFood", "fdcId": -1],
                                   ["kind": "usdaSearch", "q": "   "], ["kind": "somethingElse"]] {
            let answer = await services.answer(bad)
            XCTAssertEqual(answer["error"] as? String, "bad_request", "\(bad)")
        }
        let status = await services.answer(["kind": "services"])
        XCTAssertEqual(status["off"] as? Bool, false)
        _ = await services.answer(["kind": "enableOff"])
        XCTAssertTrue(services.offOn)
    }

    @MainActor
    func testAUsdaKeyMustLookLikeOne() {
        XCTAssertTrue(FoodServices.isPlausibleKey("abcdEFGH1234abcdEFGH1234abcdEFGH1234abcd"))
        XCTAssertFalse(FoodServices.isPlausibleKey("short"))
        XCTAssertFalse(FoodServices.isPlausibleKey("abcdEFGH1234abcdEFGH1234 abcdEFGH1234abcd"))
        XCTAssertFalse(FoodServices.userAgent.contains("@")) // the project's address, never a person's email
    }

    @MainActor
    func testTheLockIsOffByDefault() {
        let defaults = UserDefaults(suiteName: "PhoneTests-\(UUID().uuidString)")!
        let lock = AppLock(defaults: defaults)
        XCTAssertFalse(lock.enabled)
        XCTAssertFalse(lock.locked)
        lock.lockIfEnabled()
        XCTAssertFalse(lock.locked)
    }

    /// Step 5: the server's instructions, with the page's data JSON put in place exactly; other tasks and empty text are refused.
    func testTheOnDeviceAIUsesTheServersPromptAndOnlyTwoTasks() async {
        let prompts = AIPrompts(raw: ["system": "S", "tasks": ["parse_meal": ["template": "<data>{text}</data>"]]])
        XCTAssertEqual(prompts.message(task: "parse_meal", text: " {\"text\": \"2 eggs\"} "), "<data> {\"text\": \"2 eggs\"} </data>")
        XCTAssertNil(prompts.message(task: "read_lab_report_text", text: "x"))
        XCTAssertEqual(OnDeviceAI.tasks, ["parse_meal", "read_lab_report_text"])
        let other = await OnDeviceAI.answer(["task": "plan_day", "text": "x"])
        XCTAssertEqual(other["error"] as? String, "bad_request")
        let empty = await OnDeviceAI.answer(["task": "parse_meal", "text": ""])
        XCTAssertEqual(empty["error"] as? String, "bad_request")
    }
}
