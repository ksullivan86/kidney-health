// Withings and Whoop from the iPhone app (owner, 2026-11-26): the sign-in address, the way back through the relay page, the token
// and data requests, and reading a token answer, as the server does (app/devices/withings.py, whoop.py).
import Foundation
import XCTest
@testable import KidneyHealthCore

final class DeviceLinksTests: XCTestCase {
    func testTheServersOwnPageOpensAtConnectedDevices() {
        XCTAssertEqual(DeviceLinks.serverPage("https://kidney.example.org", company: .withings)?.absoluteString,
                       "https://kidney.example.org/#/devices/open/withings")
        XCTAssertEqual(DeviceLinks.serverPage("https://example.org:8443/kidney/", company: .whoop)?.absoluteString,
                       "https://example.org:8443/kidney/#/devices/open/whoop")
        XCTAssertNil(DeviceLinks.serverPage("http://kidney.example.org", company: .withings))
    }

    func testTheSignInAskAndTheWayBack() throws {
        let url = try XCTUnwrap(DeviceLinks.authorize(.withings, clientID: "client-1", state: "s-123456789"))
        let items = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(url.host, "account.withings.com")
        XCTAssertEqual(items.first { $0.name == "redirect_uri" }?.value, DeviceLinks.relayURL)
        XCTAssertEqual(items.first { $0.name == "scope" }?.value, "user.metrics")
        let whoop = try XCTUnwrap(DeviceLinks.authorize(.whoop, clientID: "c", state: "s-123456789"))
        XCTAssertTrue(whoop.absoluteString.contains("read%3Acycles") || whoop.absoluteString.contains("read:cycles"))
        XCTAssertFalse(whoop.absoluteString.contains("read:profile") || whoop.absoluteString.contains("body_measurement"))
        XCTAssertTrue(DeviceLinks.relayURL.hasPrefix("https://"))

        let ok = URL(string: "kidneyhealth-devices://callback?code=abc123&state=s-123456789")!
        XCTAssertEqual(DeviceLinks.back(ok, expectedState: "s-123456789"), .code("abc123"))
        XCTAssertEqual(DeviceLinks.back(ok, expectedState: "s-other"), .wrongState)
        XCTAssertEqual(DeviceLinks.back(ok, expectedState: ""), .wrongState)
        XCTAssertEqual(DeviceLinks.back(URL(string: "kidneyhealth-devices://callback?error=access_denied&state=s-1")!, expectedState: "s-1"), .cancelled)
        XCTAssertEqual(DeviceLinks.back(URL(string: "kidneyhealth-devices://callback?code=a&code=b&state=s-1")!, expectedState: "s-1"), .cancelled)
        XCTAssertEqual(DeviceLinks.back(URL(string: "kidneyhealth-devices://callback?code=a&state=s-1&state=s-1")!, expectedState: "s-1"), .wrongState)
        XCTAssertEqual(DeviceLinks.back(URL(string: "https://evil.example/callback?code=a&state=s-1")!, expectedState: "s-1"), .unreadable)
        XCTAssertEqual(DeviceLinks.back(URL(string: "kidneyhealth-devices://other?code=a&state=s-1")!, expectedState: "s-1"), .unreadable)
    }

    func testTheRequestsAreTheServers() {
        let code = String(decoding: DeviceLinks.codeForm(.withings, clientID: "id", secret: "se&cret", code: "c1"), as: UTF8.self)
        XCTAssertEqual(code, "action=requesttoken&grant_type=authorization_code&client_id=id&client_secret=se%26cret&code=c1&redirect_uri="
                       + "https%3A%2F%2Fksullivan86.github.io%2Fkidney-health%2Foauth%2F")
        let refresh = String(decoding: DeviceLinks.refreshForm(.whoop, clientID: "id", secret: "s", refresh: "r"), as: UTF8.self)
        XCTAssertEqual(refresh, "grant_type=refresh_token&client_id=id&client_secret=s&refresh_token=r&scope=offline")
        XCTAssertEqual(String(decoding: DeviceLinks.withingsMeasureForm(since: 1700000000, offset: 5), as: UTF8.self),
                       "action=getmeas&meastypes=1%2C9%2C10%2C11&category=1&lastupdate=1700000000&offset=5")
        XCTAssertEqual(DeviceLinks.whoopPage("/developer/v2/cycle", start: DeviceLinks.isoUTC(0), nextToken: "n1")?.absoluteString,
                       "https://api.prod.whoop.com/developer/v2/cycle?limit=25&start=1970-01-01T00:00:00.000000Z&nextToken=n1")
        XCTAssertEqual(DeviceLinks.withingsSigned(["getnonce", "id", "123"]), "getnonce,id,123")
    }

    func testATokenAnswerIsReadAsTheServerDoes() {
        let withings = Data(#"{"status":0,"body":{"userid":42,"access_token":"a","refresh_token":"r","expires_in":10800,"scope":"user.metrics"}}"#.utf8)
        guard case .success(let t) = DeviceLinks.tokens(.withings, httpStatus: 200, body: withings, refreshing: false, now: 100) else {
            return XCTFail("refused")
        }
        XCTAssertEqual(t, DeviceLinks.Tokens(access: "a", refresh: "r", expiresAt: 10900, account: "42", scopes: "user.metrics"))
        let noScope = Data(#"{"status":0,"body":{"userid":42,"access_token":"a","refresh_token":"r","scope":"user.info"}}"#.utf8)
        XCTAssertEqual(try? DeviceLinks.tokens(.withings, httpStatus: 200, body: noScope, refreshing: false, now: 0).get(), nil)
        if case .failure(let p) = DeviceLinks.tokens(.withings, httpStatus: 200, body: noScope, refreshing: false, now: 0) { XCTAssertEqual(p, .scope) }
        let refused = Data(#"{"status":503,"body":{}}"#.utf8)
        if case .failure(let p) = DeviceLinks.tokens(.withings, httpStatus: 200, body: refused, refreshing: true, now: 0) { XCTAssertEqual(p, .auth) }
        if case .failure(let p) = DeviceLinks.tokens(.withings, httpStatus: 200, body: Data(#"{"status":601}"#.utf8), refreshing: true, now: 0) {
            XCTAssertEqual(p, .rateLimited)
        }
        let whoop = Data(#"{"access_token":"wa","refresh_token":"wr","expires_in":3600,"scope":"offline read:cycles"}"#.utf8)
        guard case .success(let w) = DeviceLinks.tokens(.whoop, httpStatus: 200, body: whoop, refreshing: false, now: 0) else { return XCTFail("refused") }
        XCTAssertEqual([w.access, w.refresh, w.account], ["wa", "wr", ""])
        if case .failure(let p) = DeviceLinks.tokens(.whoop, httpStatus: 400, body: Data(), refreshing: true, now: 0) { XCTAssertEqual(p, .auth) }
        if case .failure(let p) = DeviceLinks.tokens(.whoop, httpStatus: 400, body: Data(), refreshing: false, now: 0) { XCTAssertEqual(p, .refused) }
        XCTAssertTrue(DeviceLinks.isPlausibleCredential("abcdef0123456789"))
        XCTAssertFalse(DeviceLinks.isPlausibleCredential("short"))
        XCTAssertFalse(DeviceLinks.isPlausibleCredential("has a space in it"))
    }
}
