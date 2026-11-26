// Reminders as the iPhone's own notifications (design note 35 §7). No server, no Web Push.
//
// The page keeps the reminders in the log and plans the next 7 days (js/mock/phone_reminders.js). It asks through the "bridge":
// { kind: "reminders", action: "status" | "allow" | "schedule" | "test" | "openSettings" }. "schedule" replaces every pending
// reminder with the page's plan: items of { id, at: "YYYY-MM-DDTHH:MM", kind, meal }. Each is one notification with a calendar
// trigger and no time zone, so it goes off at that time in the phone's own zone.
//
// The words are written here, never by the page: the title "Food log" and the server's bodies (app/reminders.py BODIES), so the
// lock screen never shows health words or food names. Reminders are a convenience: there is no reminder about lows, insulin,
// medicines or glucose. A tap opens the matching screen (KH.openScreen in js/main.js) once the page has started.
import Foundation
import UIKit
import UserNotifications
import WebKit

@MainActor
final class LocalReminders: NSObject, UNUserNotificationCenterDelegate {
    static let shared = LocalReminders()

    static let title = "Food log"
    static let testBody = "This is a test. Your reminders will look like this."
    static let idPrefix = "reminder-"
    static let testID = "reminder-test"
    /// iOS keeps 64 pending notifications; the page plans at most 60.
    static let maxItems = 60
    static let bodies: [String: String] = [
        "log_meal:breakfast": "Time to log breakfast.",
        "log_meal:lunch": "Time to log lunch.",
        "log_meal:dinner": "Time to log dinner.",
        "log_meal:snack": "Time to log a snack.",
        "plan_tomorrow": "Time to plan tomorrow's meals.",
        "weigh_in": "Time to log your weight.",
    ]
    /// The screen each kind opens (app/reminders.py PAGES); the test opens Settings.
    static let screens: [String: String] = ["log_meal": "add", "plan_tomorrow": "plan", "weigh_in": "today"]
    static let allowedScreens: Set<String> = ["add", "plan", "today", "settings"]

    private var center: UNUserNotificationCenter { UNUserNotificationCenter.current() }
    private var pendingScreen: String?

    /// Set at launch (AppDelegate), so a tap that opens the app is not lost.
    func install() {
        center.delegate = self
    }

    // MARK: - The page's requests

    func answer(_ request: [String: Any]) async -> [String: Any] {
        switch request["action"] as? String {
        case "status":
            return await status()
        case "allow": // only from the person's tap on "Turn on notifications on this iPhone"
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
            return await status()
        case "schedule":
            return await schedule(request["items"])
        case "test":
            return await test()
        case "openSettings":
            if let url = URL(string: UIApplication.openNotificationSettingsURLString) {
                _ = await UIApplication.shared.open(url)
            }
            return ["ok": true]
        default:
            return FoodServices.problem("bad_request")
        }
    }

    private func permission() async -> String {
        let settings = await center.notificationSettings()
        switch settings.authorizationStatus {
        case .authorized, .provisional, .ephemeral: return "allowed"
        case .denied: return "denied"
        default: return "not_asked"
        }
    }

    private func status() async -> [String: Any] {
        let pending = await center.pendingNotificationRequests().filter { $0.identifier.hasPrefix(Self.idPrefix) }.count
        return ["ok": true, "permission": await permission(), "pending": pending]
    }

    /// The body for a kind and meal from the page, or nil when it is not one of ours.
    static func body(kind: String, meal: String?) -> String? {
        bodies[kind == "log_meal" ? "log_meal:\(meal ?? "")" : kind]
    }

    /// "YYYY-MM-DDTHH:MM" as calendar parts with no time zone: the phone's own zone when it goes off.
    static func parts(_ text: String) -> DateComponents? {
        let pieces = text.split(whereSeparator: { $0 == "-" || $0 == "T" || $0 == ":" }).map { Int($0) }
        guard text.count == 16, pieces.count == 5, let year = pieces[0], let month = pieces[1], let day = pieces[2],
              let hour = pieces[3], let minute = pieces[4], (2000...2100).contains(year), (1...12).contains(month),
              (1...31).contains(day), (0...23).contains(hour), (0...59).contains(minute) else { return nil }
        return DateComponents(year: year, month: month, day: day, hour: hour, minute: minute)
    }

    private func content(_ body: String, screen: String) -> UNMutableNotificationContent {
        let content = UNMutableNotificationContent()
        content.title = Self.title
        content.body = body
        content.sound = .default
        content.threadIdentifier = "reminders"
        content.userInfo = ["screen": screen]
        return content
    }

    private func schedule(_ raw: Any?) async -> [String: Any] {
        guard let items = raw as? [[String: Any]], items.count <= Self.maxItems else { return FoodServices.problem("bad_request") }
        var requests: [UNNotificationRequest] = []
        for item in items {
            guard let id = item["id"] as? String, id.hasPrefix(Self.idPrefix), id != Self.testID, id.count <= 64,
                  let kind = item["kind"] as? String, let screen = Self.screens[kind],
                  let body = Self.body(kind: kind, meal: item["meal"] as? String),
                  let at = item["at"] as? String, let when = Self.parts(at) else { return FoodServices.problem("bad_request") }
            let trigger = UNCalendarNotificationTrigger(dateMatching: when, repeats: false)
            requests.append(UNNotificationRequest(identifier: id, content: content(body, screen: screen), trigger: trigger))
        }
        // Replace: every pending reminder goes, then the new plan (a test that is waiting stays).
        let old = await center.pendingNotificationRequests().map(\.identifier).filter { $0.hasPrefix(Self.idPrefix) && $0 != Self.testID }
        center.removePendingNotificationRequests(withIdentifiers: old)
        let allowed = await permission()
        guard allowed == "allowed" else { return ["ok": true, "scheduled": 0, "permission": allowed] }
        var scheduled = 0
        for request in requests {
            if (try? await center.add(request)) != nil { scheduled += 1 }
        }
        return ["ok": true, "scheduled": scheduled, "permission": allowed]
    }

    private func test() async -> [String: Any] {
        guard await permission() == "allowed" else {
            return ["error": "not_allowed", "message": "Turn on notifications on this iPhone first."]
        }
        let trigger = UNTimeIntervalNotificationTrigger(timeInterval: 5, repeats: false)
        do {
            try await center.add(UNNotificationRequest(identifier: Self.testID, content: content(Self.testBody, screen: "settings"),
                                                       trigger: trigger))
            return ["ok": true]
        } catch {
            return ["error": "failed", "message": "The test could not be sent."]
        }
    }

    // MARK: - Shown and tapped

    /// While the app is open, the reminder still shows as a banner.
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                            withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                            withCompletionHandler completionHandler: @escaping () -> Void) {
        let screen = response.notification.request.content.userInfo["screen"] as? String
        Task { @MainActor in self.open(screen) }
        completionHandler()
    }

    func open(_ screen: String?) {
        guard let screen, Self.allowedScreens.contains(screen) else { return }
        pendingScreen = screen
        run()
    }

    /// Called when the page has loaded, and when a tap arrives: the screen opens once the page can take it.
    func run() {
        guard let screen = pendingScreen, PageBridge.shared.ready, let view = PageBridge.shared.webView else { return }
        pendingScreen = nil
        Task {
            _ = try? await view.callAsyncJavaScript("return await window.KH.openScreen(name);", arguments: ["name": screen],
                                                    in: nil, contentWorld: .page)
        }
    }
}
