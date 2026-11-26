// Speaking a question for Ask (owner, 2026-11-26): the words are worked out on this iPhone and never leave it.
//
// The page's microphone button (js/views/ask-voice.js) asks { kind: "speechStatus" } and { kind: "dictate" } through the bridge.
// `dictate` shows a sheet that listens and shows the words as they come, with Done and Cancel, and stops by itself after 60 seconds,
// like the web app's recording. Apple's speech recognizer runs with requiresOnDeviceRecognition, so the sound and the words stay
// on the phone; a language this iPhone cannot do on the device is "not_on_device" and the page hides the microphone. Nothing is
// recorded to a file or kept. The answer is { ok: true, text }, or { error: "cancelled" | "not_allowed" | "unavailable" | "busy" |
// "failed", message }. The page puts the text into the question box; only the person's Send sends it.
import AVFoundation
import Speech
import SwiftUI
import UIKit

@MainActor
final class Dictation: NSObject {
    static let shared = Dictation()
    static let maxSeconds = 60

    private var continuation: CheckedContinuation<[String: Any], Never>?
    private let engine = AVAudioEngine()
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?
    private weak var sheet: UIViewController?
    private let model = DictationModel()
    private var turn = 0
    private var stopping = false
    private var resignObserver: NSObjectProtocol?

    /// A recognizer that works on this iPhone without a network, for the phone's language (else US English), or nil.
    static func recognizer() -> SFSpeechRecognizer? {
        for locale in [Locale.current, Locale(identifier: "en-US")] {
            if let recognizer = SFSpeechRecognizer(locale: locale), recognizer.supportsOnDeviceRecognition { return recognizer }
        }
        return nil
    }

    /// { ok, available, reason: "not_on_device" | "not_allowed" | "not_ready" | null }. Asks for nothing.
    static func status() -> [String: Any] {
        guard let recognizer = recognizer() else { return ["ok": true, "available": false, "reason": "not_on_device"] }
        let speech = SFSpeechRecognizer.authorizationStatus()
        if speech == .denied || speech == .restricted || AVAudioApplication.shared.recordPermission == .denied {
            return ["ok": true, "available": false, "reason": "not_allowed"]
        }
        guard recognizer.isAvailable else { return ["ok": true, "available": false, "reason": "not_ready"] }
        return ["ok": true, "available": true, "reason": NSNull()]
    }

    /// Asks for the two permissions the first time (iOS shows its own questions with the Info.plist sentences). Not on the main
    /// actor: iOS answers on a queue of its own.
    nonisolated private static func allowed() async -> Bool {
        let speech: SFSpeechRecognizerAuthorizationStatus = await withCheckedContinuation { next in
            SFSpeechRecognizer.requestAuthorization { next.resume(returning: $0) }
        }
        guard speech == .authorized else { return false }
        return await AVAudioApplication.requestRecordPermission()
    }

    func dictate() async -> [String: Any] {
        guard continuation == nil else { return ["error": "busy", "message": "The app is already listening."] }
        guard let recognizer = Self.recognizer() else {
            return ["error": "unavailable", "message": "This iPhone cannot turn speech into words on the phone itself. Type your question instead."]
        }
        guard await Self.allowed() else {
            return ["error": "not_allowed", "message": "To speak your question, allow the microphone and speech for this app in the iPhone's Settings."]
        }
        guard continuation == nil, let top = BarcodeScanner.topController() else { return ["error": "busy", "message": "The app is already listening."] }
        return await withCheckedContinuation { (next: CheckedContinuation<[String: Any], Never>) in
            continuation = next
            do {
                try start(recognizer)
            } catch {
                finish(["error": "failed", "message": "The microphone could not be started. Type your question instead."])
                return
            }
            present(on: top)
        }
    }

    // MARK: - Listening

    private func start(_ recognizer: SFSpeechRecognizer) throws {
        turn += 1
        stopping = false
        model.text = ""
        model.started = Date()
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(.record, mode: .measurement, options: .duckOthers)
        try session.setActive(true, options: .notifyOthersOnDeactivation)
        let request = SFSpeechAudioBufferRecognitionRequest()
        request.requiresOnDeviceRecognition = true // the sound and the words never leave this iPhone
        request.shouldReportPartialResults = true
        request.addsPunctuation = true
        self.request = request
        let input = engine.inputNode
        input.removeTap(onBus: 0)
        input.installTap(onBus: 0, bufferSize: 1024, format: input.outputFormat(forBus: 0), block: Self.tap(request))
        engine.prepare()
        try engine.start()
        task = recognizer.recognitionTask(with: request, resultHandler: Self.results(self, turn: turn))
        let mine = turn
        Task { @MainActor [weak self] in // the web app's limit: 60 seconds, then it stops by itself
            try? await Task.sleep(nanoseconds: UInt64(Self.maxSeconds) * 1_000_000_000)
            if let self, self.turn == mine, self.continuation != nil { self.done() }
        }
        resignObserver = NotificationCenter.default.addObserver(forName: UIApplication.willResignActiveNotification, object: nil,
                                                                queue: .main) { [weak self] _ in
            Task { @MainActor in self?.finish(["error": "cancelled"]) } // leaving the app keeps nothing, as on the web
        }
    }

    /// The microphone's sound goes to the request only (made outside the main actor: the audio thread calls it).
    nonisolated private static func tap(_ request: SFSpeechAudioBufferRecognitionRequest) -> AVAudioNodeTapBlock {
        { buffer, _ in request.append(buffer) }
    }

    nonisolated private static func results(_ owner: Dictation, turn: Int) -> @Sendable (SFSpeechRecognitionResult?, Error?) -> Void {
        { result, error in
            let text = result?.bestTranscription.formattedString
            let final = result?.isFinal ?? false
            let failed = error != nil
            Task { @MainActor in owner.heard(text, final: final, failed: failed, turn: turn) }
        }
    }

    private func heard(_ text: String?, final: Bool, failed: Bool, turn: Int) {
        guard turn == self.turn, continuation != nil else { return }
        if let text { model.text = text }
        if final || (failed && stopping) {
            finish(["ok": true, "text": model.text])
        } else if failed {
            if model.text.isEmpty {
                finish(["error": "failed", "message": "No words could be worked out. Try again, or type your question."])
            } else {
                finish(["ok": true, "text": model.text])
            }
        }
    }

    /// Done: no more sound; the last words come in a moment (or after a second at most).
    private func done() {
        guard continuation != nil, !stopping else { return }
        stopping = true
        stopAudio()
        request?.endAudio()
        let mine = turn
        Task { @MainActor [weak self] in
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            if let self, self.turn == mine { self.finish(["ok": true, "text": self.model.text]) }
        }
    }

    private func stopAudio() {
        if engine.isRunning { engine.stop() }
        engine.inputNode.removeTap(onBus: 0)
    }

    private func finish(_ answer: [String: Any]) {
        guard let next = continuation else { return }
        continuation = nil
        turn += 1
        stopAudio()
        request?.endAudio()
        task?.cancel()
        task = nil
        request = nil
        if let observer = resignObserver { NotificationCenter.default.removeObserver(observer) }
        resignObserver = nil
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        sheet?.dismiss(animated: true)
        sheet = nil
        let heard = model.text
        model.text = ""
        if answer["ok"] as? Bool == true {
            next.resume(returning: ["ok": true, "text": String(heard.prefix(2000))])
        } else {
            next.resume(returning: answer)
        }
    }

    // MARK: - The sheet

    private func present(on top: UIViewController) {
        let host = UIHostingController(rootView: DictationSheet(model: model, done: { [weak self] in self?.done() },
                                                                cancel: { [weak self] in self?.finish(["error": "cancelled"]) }))
        host.modalPresentationStyle = .pageSheet
        if let sheet = host.sheetPresentationController { sheet.detents = [.medium(), .large()] }
        host.presentationController?.delegate = self
        sheet = host
        top.present(host, animated: true)
    }
}

extension Dictation: UIAdaptivePresentationControllerDelegate {
    /// Swiping the sheet away is a cancel.
    nonisolated func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        Task { @MainActor in self.finish(["error": "cancelled"]) }
    }
}

@MainActor
final class DictationModel: ObservableObject {
    @Published var text = ""
    var started = Date()
}

struct DictationSheet: View {
    @ObservedObject var model: DictationModel
    let done: () -> Void
    let cancel: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    Label("Listening", systemImage: "mic.fill").foregroundStyle(.red)
                    Spacer()
                    TimelineView(.periodic(from: model.started, by: 1)) { context in
                        Text(Self.clock(context.date.timeIntervalSince(model.started)))
                            .monospacedDigit()
                            .foregroundStyle(.secondary)
                    }
                }
                .font(.headline)
                ScrollView {
                    Text(model.text.isEmpty ? "Say your question." : model.text)
                        .font(.title3)
                        .foregroundStyle(model.text.isEmpty ? .secondary : .primary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                Text("The words are worked out on this iPhone. Nothing is sent. You can check and change them before you send your question.")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding()
            .navigationTitle("Speak your question")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel", action: cancel) }
                ToolbarItem(placement: .confirmationAction) { Button("Done", action: done) }
            }
        }
    }

    static func clock(_ seconds: TimeInterval) -> String {
        let whole = min(60, max(0, Int(seconds)))
        let rest = whole % 60
        return "\(whole / 60):\(rest < 10 ? "0" : "")\(rest) of 1:00"
    }
}
