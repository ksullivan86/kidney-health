// The person's own AI key (the owner, 2026-11-25: "if its not connected to the server it should be able to use their own keys";
// design note 39 §6.5). Settings → This device → Apple Health and server → Keys and services.
//
// The providers are the server's presets a person may use with their own key (app/ai/presets.py, user_allowed): OpenAI,
// OpenRouter and Nous Portal. Each has one fixed HTTPS host and path; all three take the OpenAI Chat Completions format.
//
// Rules, as on the server:
// * The key is written once to the Keychain (this device only) and never shown again, never sent to the page, never logged.
// * The page names a task and hands its data; the app builds the request from the server's own prompts and schemas
//   (ai-prompts.json "own_key", written by scripts/build_preview.py --device from app/ai). Only these tasks exist: describe a
//   meal, meal ideas, AI order, AI swaps, AI day plans and AI recipes (note 39 §6.6), and, only while the person's photo switch is
//   on, a label photo and a plate photo. There is no lab report task: lab reports, and anything showing the person's name or date
//   of birth, go only to a local model.
// * No cookies, no cache, no redirects, a size limit each way. Nothing about a prompt or a reply is kept.
// * The model is never asked to dose. The page checks every answer with the server's checks before the person sees it.
import Foundation

enum OwnAIProvider: String, CaseIterable, Identifiable {
    case openai
    case openrouter
    case nousPortal = "nous_portal"

    var id: String { rawValue }

    var label: String {
        switch self {
        case .openai: "OpenAI"
        case .openrouter: "OpenRouter"
        case .nousPortal: "Nous Portal"
        }
    }

    /// The only host the app talks to for this provider (presets.py base_url).
    var host: String {
        switch self {
        case .openai: "api.openai.com"
        case .openrouter: "openrouter.ai"
        case .nousPortal: "inference-api.nousresearch.com"
        }
    }

    var path: String {
        switch self {
        case .openai: "/v1/chat/completions"
        case .openrouter: "/api/v1/chat/completions"
        case .nousPortal: "/v1/chat/completions"
        }
    }

    var tokenField: String { self == .openai ? "max_completion_tokens" : "max_tokens" }
    /// Whether the provider is sent the answer's schema as response_format (json_schema), or reads it in the message (prompt).
    var schemaInRequest: Bool { self != .nousPortal }
    var temperature: Double? { self == .openai ? nil : 0.2 }
    var reasoningEffort: String? { self == .openai ? "low" : nil }
    var defaultModel: String? { self == .openai ? "gpt-6-luna" : nil }

    var extraBody: [String: Any] {
        switch self {
        case .openai: ["store": false]
        case .openrouter: ["provider": ["data_collection": "deny", "require_parameters": true]]
        case .nousPortal: [:]
        }
    }

    /// The server's consent line for this provider (presets.py POLICY_LINES).
    var policy: String {
        switch self {
        case .openai: "OpenAI does not use API data for training; it keeps abuse-monitoring logs for up to 30 days."
        case .openrouter: "OpenRouter routes the request only to model providers that do not collect data."
        case .nousPortal: "Nous Research's API receives the request; read their privacy policy before agreeing."
        }
    }
}

@MainActor
final class OwnAI: ObservableObject {
    static let shared = OwnAI()

    /// The tasks the page may ask for. Never a lab report task.
    static let tasks: Set<String> = ["parse_meal", "read_label", "plate", "next_meal", "recipes", "rerank", "swap", "plan"]
    static let photoTasks: Set<String> = ["read_label", "plate"]
    /// Meal ideas and recipes: the page names the person's condition (one of ai-prompts.json "conditions") and its candidate ids.
    static let candidateTasks: Set<String> = ["next_meal", "recipes"]
    /// AI order, AI swaps and AI day plans: the meal ideas rules with the person's condition too, but no ids (their answers name
    /// the page's refs and meals, and the page keeps only those it sent).
    static let conditionTasks: Set<String> = ["next_meal", "recipes", "rerank", "swap", "plan"]
    static let candidateIds = "\"__CANDIDATE_IDS__\""
    /// The page's data: about 400 characters to describe a meal (300 typed, cleaned and escaped as JSON); meal ideas and recipes
    /// send their candidates, trimmed by the page to fit the provider's prompt (as the server's features._fits).
    static let maxText = 60_000
    static let maxIds = 60
    /// A photo as base64 (the page sends a JPEG of at most 1,600 pixels on the long side).
    static let maxPhoto = 6 * 1024 * 1024
    static let maxAnswer = 1_000_000
    static let maxBody = 8 * 1024 * 1024

    @Published private(set) var provider: OwnAIProvider?
    @Published private(set) var model: String
    @Published private(set) var hasKey: Bool
    @Published private(set) var photosOn: Bool

    private let defaults: UserDefaults
    /// No cookies, no cache, no redirects (URLSessionTransport.swift), with time for a photo to be read.
    private let session = URLSessionTransport.makeSession(wait: 90)

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        provider = defaults.string(forKey: "ownAI.provider").flatMap(OwnAIProvider.init(rawValue:))
        model = defaults.string(forKey: "ownAI.model") ?? ""
        photosOn = defaults.bool(forKey: "ownAI.photos")
        hasKey = Keychain.read(.ownAIKey) != nil
    }

    var ready: Bool { provider != nil && hasKey && !model.isEmpty }

    /// What the page may know: whether a key is set, the provider, its host and model, and the photo switch. Never the key.
    func status() -> [String: Any] {
        guard ready, let provider else { return ["ok": true, "set": false] }
        return ["ok": true, "set": true, "provider": provider.rawValue, "label": provider.label, "host": provider.host, "model": model,
                "photos": photosOn]
    }

    static func isPlausibleKey(_ key: String) -> Bool {
        (20...300).contains(key.count) && key.unicodeScalars.allSatisfy { (33...126).contains($0.value) }
    }

    static func isPlausibleModel(_ model: String) -> Bool {
        (1...100).contains(model.count) && model.allSatisfy { $0.isASCII && ($0.isLetter || $0.isNumber || "._:/-@".contains($0)) }
    }

    /// Saves the provider, the model and a pasted key. An empty key keeps the saved one when the provider is the same.
    /// Nil when saved, else the problem in plain words.
    func save(provider: OwnAIProvider, model: String, key: String) -> String? {
        let model = model.trimmingCharacters(in: .whitespacesAndNewlines)
        let key = key.trimmingCharacters(in: .whitespacesAndNewlines)
        guard Self.isPlausibleModel(model) else { return "Enter the model's name exactly as \(provider.label) writes it." }
        if key.isEmpty {
            guard hasKey, provider == self.provider else { return "Paste your key from \(provider.label)." }
        } else {
            guard Self.isPlausibleKey(key) else { return "That does not look like a key. Paste the whole key." }
            do { try Keychain.save(Data(key.utf8), as: .ownAIKey) } catch { return "The key could not be saved on this phone." }
        }
        defaults.set(provider.rawValue, forKey: "ownAI.provider")
        defaults.set(model, forKey: "ownAI.model")
        self.provider = provider
        self.model = model
        hasKey = true
        return nil
    }

    func remove() {
        Keychain.delete(.ownAIKey)
        defaults.removeObject(forKey: "ownAI.provider")
        defaults.removeObject(forKey: "ownAI.model")
        defaults.set(false, forKey: "ownAI.photos")
        provider = nil
        model = ""
        hasKey = false
        photosOn = false
    }

    func setPhotos(_ on: Bool) {
        defaults.set(on, forKey: "ownAI.photos")
        photosOn = on
    }

    /// One tiny fixed request, to check the key. Sends nothing about the person.
    func test() async -> String {
        guard let provider, ready else { return "Save a key first." }
        var body: [String: Any] = ["model": model, "messages": [["role": "user", "content": "Reply with the word OK."]], "stream": false,
                                   provider.tokenField: 64]
        for (name, value) in provider.extraBody { body[name] = value }
        let answer = await send(provider, body: body)
        if answer["ok"] as? Bool == true { return "The key works." }
        return answer["message"] as? String ?? "The key could not be checked."
    }

    // MARK: - The page's requests

    static func problem(_ code: String, _ message: String? = nil) -> [String: Any] {
        let text: [String: String] = [
            "bad_request": "The app could not read the request.",
            "own_off": "Add your own AI key in Settings → This device → Apple Health and server → Keys and services.",
            "photos_off": "Photos do not go to your own AI key. You can turn that on in Keys and services.",
            "key_refused": "Your AI provider did not accept the key. Check it in Keys and services.",
            "rate_limited": "Your AI provider says too many requests just now. Try again in a little while.",
            "not_available": "Your AI provider is not answering just now. Try again later.",
            "offline": "The phone could not reach your AI provider. Check the connection and try again.",
            "ai_failed": "Your AI provider could not answer this. Check the model name in Keys and services.",
            "no_prompts": "The app's AI instructions are missing.",
        ]
        return ["error": code, "message": message ?? text[code] ?? "The AI request failed."]
    }

    /// Answers { kind: "ownAI", task, text?, jpeg? } with { ok, content, refusal } (the model's own words; the page checks them).
    func answer(_ request: [String: Any]) async -> [String: Any] {
        guard let task = request["task"] as? String, Self.tasks.contains(task) else { return Self.problem("bad_request") }
        let photo = Self.photoTasks.contains(task)
        let text = request["text"] as? String
        let jpeg = request["jpeg"] as? String
        if photo {
            guard text == nil, let jpeg, !jpeg.isEmpty, jpeg.count <= Self.maxPhoto, jpeg.hasPrefix("/9j/"),
                  Data(base64Encoded: jpeg) != nil else { return Self.problem("bad_request") }
        } else {
            guard jpeg == nil, let text, !text.isEmpty, text.count <= Self.maxText else { return Self.problem("bad_request") }
        }
        let condition = request["condition"] as? String
        let ids = Self.wholeNumbers(request["ids"])
        if Self.candidateTasks.contains(task) {
            guard condition != nil, let ids, !ids.isEmpty, ids.count <= Self.maxIds else { return Self.problem("bad_request") }
        } else if Self.conditionTasks.contains(task) {
            guard condition != nil, request["ids"] == nil else { return Self.problem("bad_request") }
        } else {
            guard request["condition"] == nil, request["ids"] == nil else { return Self.problem("bad_request") }
        }
        guard let provider, ready else { return Self.problem("own_off") }
        guard !photo || photosOn else { return Self.problem("photos_off") }
        guard let prompts = AIPrompts.load(), let body = Self.body(prompts, provider: provider, model: model, task: task, text: text, jpeg: jpeg,
                                                                   condition: condition, ids: ids) else {
            return Self.problem("no_prompts")
        }
        return await send(provider, body: body)
    }

    /// The page's candidate ids: whole numbers from 1 up, or nil.
    static func wholeNumbers(_ value: Any?) -> [Int]? {
        guard let list = value as? [Any] else { return nil }
        var out: [Int] = []
        for item in list {
            guard let number = item as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(), number.doubleValue == number.doubleValue.rounded(),
                  number.doubleValue >= 1, number.doubleValue < 9e15 else { return nil }
            out.append(number.intValue)
        }
        return out
    }

    /// The schema with the page's candidate ids where the server puts its list (gen_own_key_prompts.py CANDIDATE_IDS).
    static func withIds(_ node: Any, _ ids: [Int]) -> Any {
        if let text = node as? String, "\"\(text)\"" == candidateIds { return ids }
        if let dict = node as? [String: Any] { return dict.mapValues { withIds($0, ids) } }
        if let list = node as? [Any] { return list.map { withIds($0, ids) } }
        return node
    }

    /// The Chat Completions body, as the server's client.build_body makes it for this provider.
    static func body(_ prompts: AIPrompts, provider: OwnAIProvider, model: String, task: String, text: String?, jpeg: String?,
                     condition: String? = nil, ids: [Int]? = nil) -> [String: Any]? {
        guard tasks.contains(task), let own = prompts.raw["own_key"] as? [String: Any], let taskSystem = own["system"] as? String,
              let maxTokens = own["max_tokens"] as? Int, let entry = (own["tasks"] as? [String: Any])?[task] as? [String: Any],
              var schema = entry["schema"] as? [String: Any], let name = entry["schema_name"] as? String,
              var message = entry[provider.schemaInRequest ? "json_schema" : "prompt"] as? String else { return nil }
        let photo = entry["image"] as? Bool == true
        guard photo == photoTasks.contains(task) else { return nil }
        var system = taskSystem
        if candidateTasks.contains(task) {
            // The meal ideas or recipe rules with the person's condition (only a wording the server itself uses), and the ids.
            guard entry["ids"] as? Bool == true, let ids, !ids.isEmpty,
                  let condition, let rules = prompts.system(task: task, condition: condition),
                  let marked = withIds(schema, ids) as? [String: Any] else { return nil }
            system = rules
            schema = marked
            message = message.replacingOccurrences(of: candidateIds, with: "[" + ids.map(String.init).joined(separator: ",") + "]")
        } else if conditionTasks.contains(task) {
            // The meal ideas rules with the person's condition; no ids.
            guard entry["ids"] as? Bool == false, ids == nil, let condition,
                  let rules = prompts.system(task: task, condition: condition) else { return nil }
            system = rules
        } else if condition != nil || ids != nil {
            return nil
        }
        if let text {
            guard !photo, message.contains("{text}") else { return nil }
            message = message.replacingOccurrences(of: "{text}", with: text)
        } else if !photo {
            return nil
        }
        var content: Any = message
        if photo {
            guard let jpeg else { return nil }
            content = [["type": "text", "text": message], ["type": "image_url", "image_url": ["url": "data:image/jpeg;base64," + jpeg]]]
        }
        var body: [String: Any] = ["model": model, "messages": [["role": "system", "content": system], ["role": "user", "content": content]],
                                   "stream": false, provider.tokenField: maxTokens]
        if provider.schemaInRequest {
            body["response_format"] = ["type": "json_schema", "json_schema": ["name": name, "strict": true, "schema": schema]]
        }
        if let effort = provider.reasoningEffort { body["reasoning_effort"] = effort }
        if let temperature = provider.temperature { body["temperature"] = photo ? 0.0 : temperature }
        for (key, value) in provider.extraBody { body[key] = value }
        return body
    }

    /// One POST to the provider's fixed host with the Keychain key in a header. Nothing is logged or kept.
    private func send(_ provider: OwnAIProvider, body: [String: Any]) async -> [String: Any] {
        guard let key = Keychain.read(.ownAIKey).map({ String(decoding: $0, as: UTF8.self) }) else { return Self.problem("own_off") }
        var parts = URLComponents()
        parts.scheme = "https"
        parts.host = provider.host
        parts.path = provider.path
        guard let url = parts.url, let data = try? JSONSerialization.data(withJSONObject: body), data.count <= Self.maxBody else {
            return Self.problem("bad_request")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.httpBody = data
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization") // a header, so the key is never in a URL
        do {
            let (reply, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.url?.host == provider.host else { return Self.problem("not_available") }
            switch http.statusCode {
            case 200: break
            case 401, 403: return Self.problem("key_refused")
            case 429: return Self.problem("rate_limited")
            case 500...599: return Self.problem("not_available")
            default: return Self.problem("ai_failed")
            }
            guard reply.count <= Self.maxAnswer, let object = try? JSONSerialization.jsonObject(with: reply) as? [String: Any],
                  let choice = (object["choices"] as? [Any])?.first as? [String: Any],
                  let message = choice["message"] as? [String: Any] else { return Self.problem("ai_failed") }
            var content = ""
            if let text = message["content"] as? String {
                content = text
            } else if let parts = message["content"] as? [Any] {
                for case let part as [String: Any] in parts where ["text", "output_text"].contains(part["type"] as? String ?? "") {
                    content += part["text"] as? String ?? ""
                }
            }
            let refusal: Any = (message["refusal"] as? String).map { $0 as Any } ?? NSNull()
            let finish: Any = (choice["finish_reason"] as? String).map { $0 as Any } ?? NSNull()
            return ["ok": true, "content": content, "refusal": refusal, "finish": finish]
        } catch {
            return Self.problem("offline")
        }
    }
}
