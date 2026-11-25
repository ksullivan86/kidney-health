// Apple's on-device language model for some tasks of the web app (design note 38, step 5, §5.6; note 39 §6.6): describe a meal,
// read a lab report's text, meal ideas, AI recipes, and on iOS 27 a photo of a plate or a label (OnDeviceVision.swift). Everything
// runs on the phone: nothing is sent anywhere, so lab text and photos may use it (CLAUDE.md: lab reports go to a local model only).
// Nothing is stored: no prompt, no reply.
//
// The model is only asked for the answer shapes of the server's schemas (app/ai/schemas.py ParseMealAnswer, LabReportAnswer,
// LabelAnswer, PlateAnswer, IdeasAnswer, RecipesAnswer), with the server's own instructions, read from ai-prompts.json, which
// scripts/build_preview.py --device writes from app/ai/prompts.py. The page treats the answer as untrusted: it checks the shape and
// runs the server's judges (twins in js/engine) before the person sees anything, and the person checks every line before it is
// saved. The model is never asked to dose; its instructions say so.
import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

enum OnDeviceAI {
    /// The tasks the page may ask for. Any other is refused.
    static let tasks: Set<String> = ["parse_meal", "read_lab_report_text", "next_meal", "recipes", "read_label", "plate"]
    /// Tasks that take a photo (a JPEG the page made) in place of text: iOS 27 and a build with OnDeviceVision only.
    static let photoTasks: Set<String> = ["read_label", "plate"]
    /// Tasks whose instructions name the person's condition (one of ai-prompts.json "conditions", never free text).
    static let conditionTasks: Set<String> = ["next_meal", "recipes"]
    /// Text longer than this does not fit the on-device model's context (about 4,096 tokens) with its instructions. The page
    /// answers 413 itself above the same size (js/mock/ai.js MAX_DEVICE_TEXT) and trims meal and recipe candidates to fit
    /// (DEVICE_DATA_CHARS), so this only guards the app.
    static let maxTextChars = 8_000
    /// A photo as base64 (the page sends a JPEG of at most 1,600 pixels on the long side).
    static let maxPhoto = 6 * 1024 * 1024

    /// { available, reason, photos } for the page (`aiStatus`). `photos`: this phone's model can read a photo (iOS 27).
    static func status() -> [String: Any] {
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            switch SystemLanguageModel.default.availability {
            case .available:
                return ["ok": true, "available": true, "reason": NSNull(), "photos": OnDeviceVision.available]
            case .unavailable(.deviceNotEligible):
                return ["ok": true, "available": false, "reason": "not_eligible", "photos": false]
            case .unavailable(.appleIntelligenceNotEnabled):
                return ["ok": true, "available": false, "reason": "not_enabled", "photos": false]
            case .unavailable:
                return ["ok": true, "available": false, "reason": "not_ready", "photos": false]
            }
        }
        #endif
        return ["ok": true, "available": false, "reason": "not_eligible", "photos": false]
    }

    static func problem(_ code: String, _ message: String) -> [String: Any] { ["error": code, "message": message] }

    /// Answers { kind: "ai", task, text } or, for a photo, { kind: "ai", task, jpeg }; meal ideas and recipes also name the
    /// person's `condition`.
    static func answer(_ request: [String: Any]) async -> [String: Any] {
        guard let task = request["task"] as? String, tasks.contains(task) else {
            return problem("bad_request", "The app could not read the request.")
        }
        let photo = photoTasks.contains(task)
        let text = request["text"] as? String // the page's data JSON, used exactly as sent
        let jpeg = request["jpeg"] as? String
        if photo {
            guard text == nil, let jpeg, !jpeg.isEmpty, jpeg.count <= maxPhoto, jpeg.hasPrefix("/9j/") else {
                return problem("bad_request", "The app could not read the request.")
            }
        } else {
            guard jpeg == nil, let text, !text.isEmpty else { return problem("bad_request", "The app could not read the request.") }
            guard text.count <= maxTextChars else {
                return problem("ai_failed", "This text is too long for the iPhone's own AI. Try one page or a shorter description.")
            }
        }
        guard status()["available"] as? Bool == true else {
            return problem("ai_unavailable", "The iPhone's own AI is not available on this phone.")
        }
        if photo && !OnDeviceVision.available {
            return problem("photos_unavailable", "The iPhone's own AI cannot read photos on this phone.")
        }
        guard let prompts = AIPrompts.load() else { return problem("ai_failed", "The app's AI instructions are missing.") }
        let condition = request["condition"] as? String
        if conditionTasks.contains(task) {
            guard let condition, prompts.conditions.contains(condition) else {
                return problem("bad_request", "The app could not read the request.")
            }
        }
        guard let instructions = prompts.system(task: task, condition: condition),
              let message = prompts.message(task: task, text: text) else {
            return problem("ai_failed", "The app's AI instructions are missing.")
        }
        #if canImport(FoundationModels)
        if #available(iOS 26.0, *) {
            do {
                let session = LanguageModelSession(instructions: instructions)
                switch task {
                case "parse_meal":
                    return ["ok": true, "answer": try await session.respond(to: message, generating: MealAnswer.self).content.json]
                case "read_lab_report_text":
                    return ["ok": true, "answer": try await session.respond(to: message, generating: LabAnswer.self).content.json]
                case "next_meal":
                    return ["ok": true, "answer": try await session.respond(to: message, generating: IdeasReply.self).content.json]
                case "recipes":
                    return ["ok": true, "answer": try await session.respond(to: message, generating: RecipesReply.self).content.json]
                default: // a photo: read_label or plate
                    guard let jpeg, let answer = try await OnDeviceVision.answer(session, task: task, message: message, jpeg: jpeg) else {
                        return problem("photos_unavailable", "The iPhone's own AI cannot read photos on this phone.")
                    }
                    return ["ok": true, "answer": answer]
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
    /// Every way the server words a person's condition (prompts.condition_text): the only text the app puts into the meal ideas
    /// and recipe instructions.
    var conditions: Set<String> { Set(raw["conditions"] as? [String] ?? []) }

    private func entry(_ task: String) -> [String: Any]? { (raw["tasks"] as? [String: Any])?[task] as? [String: Any] }

    /// The task's instructions: the server's fixed task rules, or its meal ideas or recipe rules with the condition put in.
    func system(task: String, condition: String?) -> String? {
        let kind = entry(task)?["system"] as? String ?? "task"
        if kind == "task" { return system }
        guard let condition, conditions.contains(condition),
              let template = (raw["systems"] as? [String: Any])?[kind] as? String, template.contains("[[CONDITION]]") else { return nil }
        return template.replacingOccurrences(of: "[[CONDITION]]", with: condition)
    }

    /// The task's message with the text put in its place. A text task's template holds one `{text}`; the page has already cleaned
    /// the text the way the server does, and the template wraps it in the server's data markers. A photo task's template is the
    /// message alone (the photo goes beside it).
    func message(task: String, text: String?) -> String? {
        guard let entry = entry(task), let template = entry["template"] as? String else { return nil }
        if entry["image"] as? Bool == true { return text == nil && !template.contains("{text}") ? template : nil }
        guard let text, template.contains("{text}") else { return nil }
        return template.replacingOccurrences(of: "{text}", with: text)
    }
}

/// JSON null for a missing number or text.
func jsonValue<T>(_ value: T?) -> Any { value.map { $0 as Any } ?? NSNull() }

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
             ["text": item.text, "search": item.search, "amount": jsonValue(item.amount), "unit": item.unit.rawValue]
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
             ["analyte": row.analyte, "value": row.value, "unit": row.unit, "taken_on": jsonValue(row.taken_on)]
         }]
    }
}

// MARK: - Photos (schemas.read_label_schema, plate_schema), read on iOS 27 only (OnDeviceVision.swift)

@available(iOS 26.0, *)
@Generable
enum LabelStatus: String {
    case ok, not_a_label, unreadable
}

@available(iOS 26.0, *)
@Generable
enum LabelBasis: String {
    case per_serving, per_100g, per_100ml
}

@available(iOS 26.0, *)
@Generable
enum LabelStyle: String {
    case us_nutrition_facts, eu_nutrition_declaration, other
}

@available(iOS 26.0, *)
@Generable
struct LabelValues {
    var calories_kcal: Double?
    var protein_g: Double?
    var fat_g: Double?
    var sat_fat_g: Double?
    var carbs_g: Double?
    var fiber_g: Double?
    var sugar_g: Double?
    var sodium_mg: Double?
    var potassium_mg: Double?
    var phosphorus_mg: Double?
    var calcium_mg: Double?

    var json: [String: Any] {
        ["calories_kcal": jsonValue(calories_kcal), "protein_g": jsonValue(protein_g), "fat_g": jsonValue(fat_g),
         "sat_fat_g": jsonValue(sat_fat_g), "carbs_g": jsonValue(carbs_g), "fiber_g": jsonValue(fiber_g), "sugar_g": jsonValue(sugar_g),
         "sodium_mg": jsonValue(sodium_mg), "potassium_mg": jsonValue(potassium_mg), "phosphorus_mg": jsonValue(phosphorus_mg),
         "calcium_mg": jsonValue(calcium_mg)]
    }
}

@available(iOS 26.0, *)
@Generable
struct LabelPercentDV {
    var sodium: Double?
    var potassium: Double?
    var phosphorus: Double?
    var calcium: Double?

    var json: [String: Any] {
        ["sodium": jsonValue(sodium), "potassium": jsonValue(potassium), "phosphorus": jsonValue(phosphorus), "calcium": jsonValue(calcium)]
    }
}

@available(iOS 26.0, *)
@Generable
struct LabelReply {
    var status: LabelStatus
    @Guide(description: "The product name as printed, if printed")
    var product_name: String?
    @Guide(description: "The serving size as printed, if printed")
    var serving_text: String?
    @Guide(description: "The serving size in grams, if printed")
    var serving_g: Double?
    var basis: LabelBasis
    @Guide(description: "The values exactly as printed, for the basis above; null when not printed")
    var per_serving: LabelValues
    @Guide(description: "Salt in grams, if printed")
    var salt_g: Double?
    @Guide(description: "The % Daily Value as printed; null when not printed")
    var percent_dv: LabelPercentDV
    @Guide(description: "The ingredient list as printed, if printed")
    var ingredients_text: String?
    var label_style: LabelStyle

    var json: [String: Any] {
        ["status": status.rawValue, "product_name": jsonValue(product_name), "serving_text": jsonValue(serving_text),
         "serving_g": jsonValue(serving_g), "basis": basis.rawValue, "per_serving": per_serving.json, "salt_g": jsonValue(salt_g),
         "percent_dv": percent_dv.json, "ingredients_text": jsonValue(ingredients_text), "label_style": label_style.rawValue]
    }
}

@available(iOS 26.0, *)
@Generable
enum PlateStatus: String {
    case ok, no_food, unsure
}

@available(iOS 26.0, *)
@Generable
enum PlateConfidence: String {
    case low, medium, high
}

@available(iOS 26.0, *)
@Generable
struct PlateItem {
    @Guide(description: "A short name of the food you can see")
    var name: String
    @Guide(description: "A short generic name a food list would use, such as 'rice' or 'green beans'")
    var search: String
    @Guide(description: "A rough weight in grams, if you can judge it")
    var grams_estimate: Double?
    var confidence: PlateConfidence
}

@available(iOS 26.0, *)
@Generable
struct PlateReply {
    var status: PlateStatus
    @Guide(description: "At most 8 foods", .maximumCount(8))
    var items: [PlateItem]

    var json: [String: Any] {
        ["status": status.rawValue,
         "items": items.map { item in
             ["name": item.name, "search": item.search, "grams_estimate": jsonValue(item.grams_estimate), "confidence": item.confidence.rawValue]
         }]
    }
}

// MARK: - Meal ideas and recipes (schemas.ideas_schema, recipes_schema). The candidate ids are per request, so the shape only says
// "a whole number"; the page drops any id that is not one of its candidates (the server's judge, js/engine/aimeal.js).

@available(iOS 26.0, *)
@Generable
enum IdeaTheme: String {
    case light, hearty, familiar, new_idea
}

@available(iOS 26.0, *)
@Generable
enum ReasonCode: String {
    case low_potassium, low_phosphorus, low_sodium, fits_carb_goal, adds_protein, adds_missing_group, you_eat_often, you_like
}

@available(iOS 26.0, *)
@Generable
enum IdeasRefusal: String {
    case none, outside_scope, no_fit
}

@available(iOS 26.0, *)
@Generable
struct FoodQuarters {
    @Guide(description: "The \"id\" of one of the foods in the data")
    var food_id: Int
    @Guide(description: "Quarters of that food's listed serving")
    var quarters: Int

    var json: [String: Any] { ["food_id": food_id, "quarters": quarters] }
}

@available(iOS 26.0, *)
@Generable
struct IdeaReply {
    var theme: IdeaTheme
    @Guide(description: "One to five foods", .maximumCount(5))
    var items: [FoodQuarters]
    @Guide(description: "One to three of the app's reasons that are true of this idea", .maximumCount(3))
    var reason_codes: [ReasonCode]
    @Guide(description: "At most two slugs from HANDBOOK_PAGES", .maximumCount(2))
    var handbook: [String]
}

@available(iOS 26.0, *)
@Generable
struct IdeasReply {
    @Guide(description: "At most three ideas", .maximumCount(3))
    var ideas: [IdeaReply]
    var status: AnswerStatus
    var refusal: IdeasRefusal

    var json: [String: Any] {
        ["ideas": ideas.map { idea in
            ["theme": idea.theme.rawValue, "items": idea.items.map(\.json), "reason_codes": idea.reason_codes.map(\.rawValue),
             "handbook": idea.handbook]
         },
         "status": status.rawValue, "refusal": refusal.rawValue]
    }
}

@available(iOS 26.0, *)
@Generable
enum RecipeDish: String {
    case soup, stew, bowl, stir_fry, bake, salad, sandwich, pasta, rice_dish, egg_dish, porridge, snack, drink
}

@available(iOS 26.0, *)
@Generable
struct RecipeReply {
    var dish: RecipeDish
    var theme: IdeaTheme
    @Guide(description: "Two to twelve foods; quarters are for the whole recipe", .maximumCount(12))
    var ingredients: [FoodQuarters]
    @Guide(description: "One to three of the app's reasons that are true of one serving", .maximumCount(3))
    var reason_codes: [ReasonCode]
}

@available(iOS 26.0, *)
@Generable
struct RecipesReply {
    @Guide(description: "At most two recipes", .maximumCount(2))
    var recipes: [RecipeReply]
    var status: AnswerStatus
    var refusal: IdeasRefusal

    /// No cooking steps: the phone never shows steps from AI (the server's recipe rule 10 without steps).
    var json: [String: Any] {
        ["recipes": recipes.map { recipe in
            ["dish": recipe.dish.rawValue, "theme": recipe.theme.rawValue, "ingredients": recipe.ingredients.map(\.json), "steps": [String](),
             "reason_codes": recipe.reason_codes.map(\.rawValue)]
         },
         "status": status.rawValue, "refusal": refusal.rawValue]
    }
}
#endif
