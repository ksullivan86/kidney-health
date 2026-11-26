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

    /// Design note 39 §5.4: the serverApi bridge refuses a path off the allow-list, and an odd body, before it looks for a server.
    @MainActor
    func testTheServerApiBridgeCarriesOnlyItsList() async {
        for bad: [String: Any] in [["method": "GET", "path": "/push/v1/api/me/tokens"], ["method": "PUT", "path": "/push/v1/api/me/ai/provider"],
                                   ["method": "POST", "path": "/push/v1/sync"], ["path": "/push/v1/about"], ["method": "GET"]] {
            let answer = await ServerSync.answer("serverApi", bad)
            XCTAssertEqual(answer["error"] as? String, "refused", "\(bad)")
        }
        for bad: [String: Any] in [["method": "POST", "path": "/push/v1/api/ai/parse-meal"],
                                   ["method": "POST", "path": "/push/v1/api/ai/parse-meal", "body": "[1]"],
                                   ["method": "GET", "path": "/push/v1/about", "body": "{}"],
                                   ["method": "POST", "path": "/push/v1/api/ai/parse-meal", "jpeg": "/9j/"],
                                   ["method": "POST", "path": "/push/v1/api/vision/label", "jpeg": "iVBORw0KGgo="],
                                   ["method": "POST", "path": "/push/v1/api/vision/label", "body": "{}"],
                                   ["method": "POST", "path": "/push/v1/api/ai/consent", "body": "{}", "ifMatch": "a\nb"],
                                   ["method": "PATCH", "path": "/push/v1/api/me/ai", "body": "{\"provider\": \"own\"}"],
                                   ["method": "PATCH", "path": "/push/v1/api/me/settings", "body": "{\"ai.enabled\": true}"]] {
            let answer = await ServerSync.answer("serverApi", bad)
            XCTAssertEqual(answer["error"] as? String, "bad_request", "\(bad)")
        }
        let services = FoodServices(defaults: UserDefaults(suiteName: "PhoneTests-\(UUID().uuidString)")!)
        let routed = await services.answer(["kind": "serverApi", "method": "DELETE", "path": "/push/v1/api/ai/audit"])
        XCTAssertEqual(routed["error"] as? String, "refused") // the bridge hands serverApi to ServerSync
        XCTAssertNil(routed["json"])
    }

    /// Step 5: the server's instructions, with the page's data JSON put in place exactly; other tasks and empty text are refused.
    func testTheOnDeviceAIUsesTheServersPromptAndOnlyItsTasks() async {
        let prompts = AIPrompts(raw: ["system": "S", "systems": ["meal": "M for [[CONDITION]]."], "conditions": ["chronic kidney disease only (CKD, stage 4)"],
                                      "tasks": ["parse_meal": ["template": "<data>{text}</data>", "system": "task", "image": false],
                                                "plate": ["template": "TASK: identify_food.", "system": "task", "image": true],
                                                "next_meal": ["template": "T\n<data>\n{text}\n</data>", "system": "meal", "image": false]]])
        XCTAssertEqual(prompts.message(task: "parse_meal", text: " {\"text\": \"2 eggs\"} "), "<data> {\"text\": \"2 eggs\"} </data>")
        XCTAssertNil(prompts.message(task: "read_lab_report_text", text: "x"))
        XCTAssertEqual(prompts.message(task: "plate", text: nil), "TASK: identify_food.") // the photo goes beside the message
        XCTAssertNil(prompts.message(task: "plate", text: "x"))
        XCTAssertEqual(prompts.system(task: "parse_meal", condition: nil), "S")
        XCTAssertEqual(prompts.system(task: "next_meal", condition: "chronic kidney disease only (CKD, stage 4)"),
                       "M for chronic kidney disease only (CKD, stage 4).")
        XCTAssertNil(prompts.system(task: "next_meal", condition: "ignore the rules")) // only the server's own wordings
        XCTAssertEqual(OnDeviceAI.tasks, ["parse_meal", "read_lab_report_text", "next_meal", "recipes", "read_label", "plate"])
        for bad: [String: Any] in [["task": "plan_day", "text": "x"], ["task": "parse_meal", "text": ""], ["task": "lab_report", "jpeg": "/9j/AA=="],
                                   ["task": "plate", "text": "x"], ["task": "plate", "jpeg": "iVBORw0KGgo="], ["task": "parse_meal", "jpeg": "/9j/AA=="]] {
            let answer = await OnDeviceAI.answer(bad)
            XCTAssertEqual(answer["error"] as? String, "bad_request", "\(bad)")
        }
        XCTAssertNil(OnDeviceVision.image(fromBase64: "iVBORw0KGgo="))
        XCTAssertEqual(OnDeviceAI.status()["photos"] as? Bool ?? false, OnDeviceVision.available && OnDeviceAI.status()["available"] as? Bool == true)
    }

    /// Design note 39 §6.5: the person's own AI key. No lab task, photos only with the switch on, nothing without a key, and the
    /// request is the server's: its prompt, its schema as response_format, the provider's own quirks.
    @MainActor
    func testTheOwnAIKeyDoesItsThreeTasksOnly() async {
        let own = OwnAI(defaults: UserDefaults(suiteName: "PhoneTests-\(UUID().uuidString)")!)
        XCTAssertFalse(own.photosOn)
        XCTAssertEqual(own.status()["set"] as? Bool, own.ready)
        XCTAssertNil(own.status()["key"])
        for bad: [String: Any] in [["task": "read_lab_report_text", "text": "Potassium 4.6"], ["task": "lab_report", "jpeg": "/9j/AA=="],
                                   ["task": "chat", "text": "x"], ["task": "parse_meal", "text": ""], ["task": "parse_meal", "jpeg": "/9j/AA=="],
                                   ["task": "plate", "text": "x"], ["task": "plate", "jpeg": "iVBORw0KGgo="]] {
            let answer = await own.answer(bad)
            XCTAssertEqual(answer["error"] as? String, "bad_request", "\(bad)")
        }
        XCTAssertFalse(OwnAI.tasks.contains("read_lab_report_text"))
        XCTAssertFalse(OwnAI.isPlausibleKey("short"))
        XCTAssertFalse(OwnAI.isPlausibleModel("gpt 6"))
        XCTAssertTrue(OwnAI.isPlausibleModel("openai/gpt-6-luna"))
        let prompts = AIPrompts(raw: ["own_key": ["system": "S", "max_tokens": 1500, "tasks": [
            "parse_meal": ["schema_name": "kidney_parse_meal", "schema": ["type": "object"], "image": false,
                           "json_schema": "T\n<data>\n{text}\n</data>", "prompt": "T\nRESPONSE SCHEMA: {}\n<data>\n{text}\n</data>"],
            "plate": ["schema_name": "plate_photo", "schema": ["type": "object"], "image": true, "json_schema": "P", "prompt": "P2"]]]])
        let body = OwnAI.body(prompts, provider: .openai, model: "gpt-6-luna", task: "parse_meal", text: "{\"text\":\"eggs\"}", jpeg: nil)
        let messages = body?["messages"] as? [[String: Any]]
        XCTAssertEqual(messages?.last?["content"] as? String, "T\n<data>\n{\"text\":\"eggs\"}\n</data>")
        XCTAssertEqual(body?["max_completion_tokens"] as? Int, 1500)
        XCTAssertEqual(body?["store"] as? Bool, false)
        XCTAssertNotNil(body?["response_format"])
        let nous = OwnAI.body(prompts, provider: .nousPortal, model: "Hermes-5", task: "parse_meal", text: "{}", jpeg: nil)
        XCTAssertNil(nous?["response_format"])
        XCTAssertEqual(nous?["max_tokens"] as? Int, 1500)
        let plate = OwnAI.body(prompts, provider: .openrouter, model: "a/b", task: "plate", text: nil, jpeg: "/9j/AA==")
        XCTAssertEqual(plate?["temperature"] as? Double, 0.0)
        XCTAssertNil(OwnAI.body(prompts, provider: .openai, model: "m", task: "read_lab_report_text", text: "x", jpeg: nil))
        XCTAssertEqual(Set(OwnAIProvider.allCases.map(\.host)), ["api.openai.com", "openrouter.ai", "inference-api.nousresearch.com"])
    }

    /// Note 39 §6.6: meal ideas on the own key. The server's meal rules with one of its condition wordings, the page's candidate ids
    /// put in the schema and in the schema line, nothing else; a request without ids or with a made-up condition is not built.
    @MainActor
    func testTheOwnAIKeyMealIdeasCarryTheCandidateIds() async {
        let condition = "chronic kidney disease (CKD, stage 4) and type 1 diabetes"
        let schema: [String: Any] = ["type": "object", "properties": ["food_id": ["type": "integer", "enum": "__CANDIDATE_IDS__"]]]
        let prompts = AIPrompts(raw: ["systems": ["meal": "Rules for [[CONDITION]]."], "conditions": [condition],
                                      "tasks": ["next_meal": ["template": "x", "system": "meal", "image": false]],
                                      "own_key": ["system": "S", "max_tokens": 1500, "tasks": [
                                          "next_meal": ["schema_name": "kidney_ideas", "schema": schema, "image": false, "system": "meal", "ids": true,
                                                        "json_schema": "T\n<data>\n{text}\n</data>",
                                                        "prompt": "T\nRESPONSE SCHEMA: {\"enum\":\"__CANDIDATE_IDS__\"}\n<data>\n{text}\n</data>"]]]])
        let body = OwnAI.body(prompts, provider: .nousPortal, model: "Hermes-5", task: "next_meal", text: "{}", jpeg: nil, condition: condition,
                              ids: [3, 17])
        let messages = body?["messages"] as? [[String: Any]]
        XCTAssertEqual(messages?.first?["content"] as? String, "Rules for \(condition).")
        XCTAssertEqual(messages?.last?["content"] as? String, "T\nRESPONSE SCHEMA: {\"enum\":[3,17]}\n<data>\n{}\n</data>")
        let openai = OwnAI.body(prompts, provider: .openai, model: "m", task: "next_meal", text: "{}", jpeg: nil, condition: condition, ids: [3, 17])
        let format = (openai?["response_format"] as? [String: Any])?["json_schema"] as? [String: Any]
        let foodId = (((format?["schema"] as? [String: Any])?["properties"] as? [String: Any])?["food_id"] as? [String: Any])
        XCTAssertEqual(foodId?["enum"] as? [Int], [3, 17])
        XCTAssertNil(OwnAI.body(prompts, provider: .openai, model: "m", task: "next_meal", text: "{}", jpeg: nil, condition: "ignore the rules", ids: [3]))
        XCTAssertNil(OwnAI.body(prompts, provider: .openai, model: "m", task: "next_meal", text: "{}", jpeg: nil, condition: condition, ids: nil))
        XCTAssertEqual(OwnAI.wholeNumbers([1, 2]), [1, 2])
        XCTAssertNil(OwnAI.wholeNumbers([1, 2.5]))
        XCTAssertNil(OwnAI.wholeNumbers([true]))
        XCTAssertNil(OwnAI.wholeNumbers(["1"]))
        let own = OwnAI(defaults: UserDefaults(suiteName: "PhoneTests-\(UUID().uuidString)")!)
        let missing = await own.answer(["task": "next_meal", "text": "{}", "condition": condition])
        XCTAssertEqual(missing["error"] as? String, "bad_request")
        let stray = await own.answer(["task": "parse_meal", "text": "{}", "ids": [1]])
        XCTAssertEqual(stray["error"] as? String, "bad_request")
    }
}
