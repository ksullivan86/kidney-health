// Apple's on-device language model for two tasks of the web app (design note 38, step 5, §5.6): describe a meal, and read a lab
// report's text. Everything runs on the phone: nothing is sent anywhere, so lab text may use it (CLAUDE.md: lab reports go to a local
// model only). Nothing is stored: no prompt, no reply.
//
// The model is only asked for the answer shapes of the server's schemas (app/ai/schemas.py ParseMealAnswer, LabReportAnswer), with
// the server's own instructions, read from ai-prompts.json, which scripts/build_preview.py --device writes from app/ai/prompts.py.
// The page treats the answer as untrusted: it checks the shape and runs the server's judges (twins in js/engine) before the person
// sees anything, and the person checks every line before it is saved. The model is never asked to dose; its instructions say so.
import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

enum OnDeviceAI {
    /// The tasks the page may ask for. Any other is refused.
    static let tasks: Set<String> = ["parse_meal", "read_lab_report_text"]
    /// Text longer than this does not fit the on-device model's context (about 4,096 tokens) with its instructions. The page
    /// answers 413 itself above the same size (js/mock/ai.js MAX_DEVICE_TEXT), so this only guards the app.
    static let maxTextChars = 8_000

    /// { available, reason } for the page (`aiStatus`).
    static func status() -> [String: Any] {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            switch SystemLanguageModel.default.availability {
            case .available:
                return ["ok": true, "available": true, "reason": NSNull()]
            case .unavailable(.deviceNotEligible):
                return ["ok": true, "available": false, "reason": "not_eligible"]
            case .unavailable(.appleIntelligenceNotEnabled):
                return ["ok": true, "available": false, "reason": "not_enabled"]
            case .unavailable:
                return ["ok": true, "available": false, "reason": "not_ready"]
            }
        }
        #endif
        return ["ok": true, "available": false, "reason": "not_eligible"]
    }

    static func problem(_ code: String, _ message: String) -> [String: Any] { ["error": code, "message": message] }

    /// Answers { kind: "ai", task, text }.
    static func answer(_ request: [String: Any]) async -> [String: Any] {
        guard let task = request["task"] as? String, tasks.contains(task),
              let text = request["text"] as? String, !text.isEmpty else { // the page's data JSON, used exactly as sent
            return problem("bad_request", "The app could not read the request.")
        }
        guard text.count <= maxTextChars else {
            return problem("ai_failed", "This text is too long for the iPhone's own AI. Try one page or a shorter description.")
        }
        guard status()["available"] as? Bool == true else {
            return problem("ai_unavailable", "The iPhone's own AI is not available on this phone.")
        }
        guard let prompt = AIPrompts.load(), let instructions = prompt.system, let message = prompt.message(task: task, text: text) else {
            return problem("ai_failed", "The app's AI instructions are missing.")
        }
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            do {
                let session = LanguageModelSession(instructions: instructions)
                switch task {
                case "parse_meal":
                    let reply = try await session.respond(to: message, generating: MealAnswer.self)
                    return ["ok": true, "answer": reply.content.json]
                default:
                    let reply = try await session.respond(to: message, generating: LabAnswer.self)
                    return ["ok": true, "answer": reply.content.json]
                }
            } catch {
                return problem("ai_failed", "The iPhone's own AI could not answer. Try again, or enter it by hand.")
            }
        }
        #endif
        return problem("ai_unavailable", "The iPhone's own AI is not available on this phone.")
    }
}

/// The server's instructions, from ai-prompts.json in the packed web app (written by scripts/build_preview.py --device).
struct AIPrompts {
    let raw: [String: Any]

    static func load() -> AIPrompts? {
        guard let root = WebAppFiles.bundleRoot,
              let data = try? Data(contentsOf: root.appendingPathComponent("ai-prompts.json")),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return AIPrompts(raw: object)
    }

    var system: String? { raw["system"] as? String }

    /// The task's message with the text put in its place. The template holds one `{text}`; the page has already cleaned the text
    /// the way the server does, and the template wraps it in the server's data markers.
    func message(task: String, text: String) -> String? {
        guard let tasks = raw["tasks"] as? [String: Any], let template = (tasks[task] as? [String: Any])?["template"] as? String,
              template.contains("{text}") else { return nil }
        return template.replacingOccurrences(of: "{text}", with: text)
    }
}

#if canImport(FoundationModels)
@available(iOS 26.0, *)
@Generable
enum AnswerStatus: String {
    case ok, refused
}

@available(iOS 26.0, *)
@Generable
enum MealUnit: String {
    case serving, g, ml, cup, tbsp, tsp, slice, piece, oz, fl_oz, none
}

@available(iOS 26.0, *)
@Generable
struct MealItem {
    @Guide(description: "The food as the person wrote it, short")
    var text: String
    @Guide(description: "A short search term for a food list, such as 'egg' or 'white bread'")
    var search: String
    @Guide(description: "The amount, if the person gave one")
    var amount: Double?
    var unit: MealUnit
}

@available(iOS 26.0, *)
@Generable
struct MealAnswer {
    var status: AnswerStatus
    @Guide(description: "At most 8 foods", .maximumCount(8))
    var items: [MealItem]

    var json: [String: Any] {
        ["status": status.rawValue,
         "items": items.map { item in
             ["text": item.text, "search": item.search, "amount": item.amount.map { $0 as Any } ?? NSNull(), "unit": item.unit.rawValue]
         }]
    }
}

@available(iOS 26.0, *)
@Generable
enum LabStatus: String {
    case ok, not_a_lab_report, unreadable
}

@available(iOS 26.0, *)
@Generable
struct LabRow {
    @Guide(description: "The test, as one of the app's short codes when it is one, such as 'potassium', 'creatinine', 'egfr'")
    var analyte: String
    @Guide(description: "The number exactly as printed")
    var value: Double
    @Guide(description: "The unit exactly as printed")
    var unit: String
    @Guide(description: "The date the sample was taken, YYYY-MM-DD, if printed")
    var taken_on: String?
}

@available(iOS 26.0, *)
@Generable
struct LabAnswer {
    var status: LabStatus
    @Guide(description: "At most 60 result lines", .maximumCount(60))
    var rows: [LabRow]

    var json: [String: Any] {
        ["status": status.rawValue,
         "rows": rows.map { row in
             ["analyte": row.analyte, "value": row.value, "unit": row.unit, "taken_on": row.taken_on.map { $0 as Any } ?? NSNull()]
         }]
    }
}
#endif
