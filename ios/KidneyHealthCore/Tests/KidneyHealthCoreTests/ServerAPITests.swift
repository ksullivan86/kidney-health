// Design note 39 §5.4: the app carries only the gateway requests on its allow-list, to the paired server, and tells the two kinds of
// token apart from GET /push/v1/about.
import Foundation
import XCTest
@testable import KidneyHealthCore

final class ServerAPITests: XCTestCase {
    func testOnlyRoutesOnTheListAreCarried() {
        XCTAssertNotNil(ServerAPI.route(method: "GET", path: "/push/v1/about"))
        XCTAssertNotNil(ServerAPI.route(method: "POST", path: "/push/v1/api/foods/barcode"))
        XCTAssertNotNil(ServerAPI.route(method: "POST", path: "/push/v1/api/ai/read-lab-report-text?dry_run=true"))
        let search = ServerAPI.route(method: "GET", path: "/push/v1/api/foods/usda/search?q=white%20rice")
        XCTAssertEqual(search?.query.first?.value, "white%20rice") // kept as the page encoded it
        for (method, path) in [
            ("GET", "/push/v1/api/me/tokens"), ("POST", "/push/v1/api/me/ai/provider"), ("PUT", "/push/v1/api/me/ai/provider"),
            ("GET", "/push/v1/api/admin/users"), ("POST", "/push/v1/api/auth/login"), ("GET", "/push/v1/api/export.zip"),
            ("DELETE", "/push/v1/api/ai/consent/1"), ("POST", "/push/v1/api/me/import"), ("GET", "/push/v1/api/log"),
            ("DELETE", "/push/v1/about"), ("GET", "/api/ai/status"), ("GET", "https://evil.example/push/v1/about"),
            ("GET", "//evil.example/push/v1/about"), ("GET", "/push/v1/api/ai/../admin/users"), ("GET", "/push/v1/about/"),
            ("GET", "/push/v1/%61bout"), ("GET", "/push/v1/about#x"), ("GET", "/push/v1/about?x=1"),
            ("GET", "/push/v1/api/foods/usda/search?q=a&q=b"), ("POST", "/push/v1/api/ai/parse-meal?debug=1"),
            ("get", "/push/v1/about"),
        ] {
            XCTAssertNil(ServerAPI.route(method: method, path: path), "\(method) \(path)")
        }
        // sync both ways (note 39 steps 6 and 7): the feed with its cursor, the phone's changes, and match
        let feed = ServerAPI.route(method: "GET", path: "/push/v1/changes?after=120&limit=500")
        XCTAssertEqual(feed?.query.map(\.name), ["after", "limit"])
        XCTAssertNotNil(ServerAPI.route(method: "GET", path: "/push/v1/changes"))
        XCTAssertNotNil(ServerAPI.route(method: "POST", path: "/push/v1/changes"))
        XCTAssertNotNil(ServerAPI.route(method: "POST", path: "/push/v1/match"))
        for (method, path) in [
            ("GET", "/push/v1/changes?after=1&since=2"), ("DELETE", "/push/v1/changes"), ("PUT", "/push/v1/changes"),
            ("GET", "/push/v1/match"), ("POST", "/push/v1/match?after=1"), ("GET", "/push/v1/changes?after=1&after=2"),
            ("GET", "/push/v1/changes/"), ("POST", "/push/v1/api/changes"),
        ] {
            XCTAssertNil(ServerAPI.route(method: method, path: path), "\(method) \(path)")
        }
        XCTAssertTrue(ServerAPI.route(method: "POST", path: "/push/v1/changes")!.route.allows(["changes": []]))
        XCTAssertEqual(ServerAPI.routes.filter(\.photo).map(\.path),
                       ["/push/v1/api/ai/read-lab-report", "/push/v1/api/vision/label", "/push/v1/api/vision/plate"])
        // a settings route takes only its own keys
        let consent = ServerAPI.route(method: "PATCH", path: "/push/v1/api/me/settings")!.route
        XCTAssertTrue(consent.allows(["food.off_consent": true]))
        XCTAssertFalse(consent.allows(["food.off_consent": true, "auth.two_step": false]))
        XCTAssertFalse(consent.allows([:]))
        let ai = ServerAPI.route(method: "PATCH", path: "/push/v1/api/me/ai")!.route
        XCTAssertTrue(ai.allows(["opt_in": true]))
        XCTAssertFalse(ai.allows(["provider": "own"]))
        XCTAssertTrue(ServerAPI.route(method: "POST", path: "/push/v1/api/ai/chat")!.route.allows(["messages": []]))
        // no route that needs the password, holds keys or tokens, or is an admin's
        for route in ServerAPI.routes {
            for word in ["/admin", "/auth", "/tokens", "/sessions", "/provider", "/me/import", "/export", "/keys"] {
                XCTAssertFalse(route.path.contains(word), route.path)
            }
        }
    }

    func testTheURLIsOnThePairedServerOnly() {
        let about = ServerAPI.url("https://kidney.example.org/", route: ServerAPI.about)
        XCTAssertEqual(about?.absoluteString, "https://kidney.example.org/push/v1/about")
        let found = ServerAPI.route(method: "GET", path: "/push/v1/api/foods/usda/search?q=rice")!
        XCTAssertEqual(ServerAPI.url("https://example.org:8443/kidney", route: found.route, query: found.query)?.absoluteString,
                       "https://example.org:8443/kidney/push/v1/api/foods/usda/search?q=rice")
        let plus = ServerAPI.route(method: "GET", path: "/push/v1/api/foods/usda/search?q=a%2Bb%20c")!
        XCTAssertEqual(ServerAPI.url("https://kidney.example.org", route: plus.route, query: plus.query)?.absoluteString,
                       "https://kidney.example.org/push/v1/api/foods/usda/search?q=a%2Bb%20c")
        XCTAssertNil(ServerAPI.url("http://kidney.example.org", route: ServerAPI.about))
    }

    func testTheTokenKindComesFromAbout() async {
        XCTAssertEqual(ServerAPI.tokenKind(HTTPReply(status: 200, body: Data(#"{"account": "a1", "api_version": 1}"#.utf8))), .bothWays)
        XCTAssertEqual(ServerAPI.tokenKind(HTTPReply(status: 401)), .addOnly)
        XCTAssertEqual(ServerAPI.tokenKind(HTTPReply(status: 404)), .oldServer)
        XCTAssertEqual(ServerAPI.tokenKind(HTTPReply(status: 200, body: Data("<html>".utf8))), .unknown)
        XCTAssertEqual(ServerAPI.tokenKind(nil), .unknown)
        XCTAssertNil(ServerAPI.text(.unknown))
        XCTAssertTrue(ServerAPI.text(.addOnly)!.contains("both ways"))
        let fake = FakeTransport([.success(HTTPReply(status: 401))])
        let reply = try? await fake.get(ServerAPI.url("https://kidney.example.org", route: ServerAPI.about)!, token: "khd_x")
        XCTAssertEqual(ServerAPI.tokenKind(reply), .addOnly)
        XCTAssertEqual(fake.checked.first?.url.path, "/push/v1/about")
    }
}
