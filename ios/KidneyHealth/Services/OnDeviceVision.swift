// A photo of a plate or of a nutrition label, read by Apple's on-device model (owner, 2026-11-25: "can the apple Ai take a photo of
// a meal and add it to the log or plan?"; design note 39 §6.6). The photo is the JPEG the page made (no location data), the same
// one the server's photo routes take. It never leaves the phone and is not kept.
//
// THE IMAGE API. Image input to Foundation Models is new in iOS 27. A plain CGImage is not a prompt part (the first try, on
// 2026-11-25, failed with "Only Prompt and PromptRepresentable are supported"). The iOS 27.2 SDK's FoundationModels interface,
// printed by the CI probe, declares `struct Attachment<Content>: PromptRepresentable` with
// `init(_ cgImage: CGImage, orientation:)` where Content == ImageAttachmentContent, so the photo goes in as an Attachment:
//
//     let prompt = Prompt { message; Attachment(image) }
//     try await session.respond(to: prompt, generating: PlateReply.self)
//
// So that a wrong guess can only remove this feature and never break the build, the guessed lines compile only with the Swift
// flag KH_ONDEVICE_IMAGES, which the project does not set. The CI job "iOS app" first builds once with the flag (a probe that may
// fail) and, if that compiles, runs the tests with it; it says which in its log. Turn it on for good by adding KH_ONDEVICE_IMAGES
// to SWIFT_ACTIVE_COMPILATION_CONDITIONS in ios/KidneyHealth.xcodeproj once the probe passes. Without it, `available` is false
// and the page offers photos only through the server or the person's own AI key.
import Foundation
import ImageIO
#if canImport(FoundationModels)
import FoundationModels
#endif

enum OnDeviceVision {
    /// This build has the guessed iOS 27 image call (the KH_ONDEVICE_IMAGES flag).
    static var compiled: Bool {
        #if canImport(FoundationModels) && KH_ONDEVICE_IMAGES
        return true
        #else
        return false
        #endif
    }

    /// The iPhone's model can be given a photo here: the flag is on and the phone runs iOS 27 or later.
    static var available: Bool {
        guard compiled else { return false }
        if #available(iOS 27.0, *) { return true }
        return false
    }

    /// The page's JPEG (base64) as an image of at most 1,600 pixels on the long side, or nil when it is not a JPEG.
    static func image(fromBase64 jpeg: String) -> CGImage? {
        guard jpeg.hasPrefix("/9j/"), let data = Data(base64Encoded: jpeg),
              let source = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let options: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 1_600,
                                        kCGImageSourceCreateThumbnailWithTransform: true]
        return CGImageSourceCreateThumbnailAtIndex(source, 0, options as CFDictionary)
    }

    #if canImport(FoundationModels)
    /// The model's answer to a photo task in the server's shape, or nil when this build or phone cannot give it a photo.
    @available(iOS 26.0, *)
    static func answer(_ session: LanguageModelSession, task: String, message: String, jpeg: String) async throws -> [String: Any]? {
        guard let picture = image(fromBase64: jpeg) else { return nil }
        #if KH_ONDEVICE_IMAGES
        if #available(iOS 27.0, *) {
            let prompt = Prompt {
                message
                FoundationModels.Attachment(picture)  // the iOS 27 SDK's Attachment<ImageAttachmentContent>, a PromptRepresentable
            }
            switch task {
            case "plate":
                return try await session.respond(to: prompt, generating: PlateReply.self).content.json
            case "read_label":
                return try await session.respond(to: prompt, generating: LabelReply.self).content.json
            default:
                return nil
            }
        }
        #endif
        _ = (session, task, message, picture)
        return nil
    }
    #endif
}
