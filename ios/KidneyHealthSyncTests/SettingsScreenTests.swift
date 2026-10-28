// What the settings screen accepts, and the words it answers with.
import KidneyHealthCore
import XCTest
@testable import KidneyHealthSync

@MainActor
final class SettingsScreenTests: XCTestCase {
    private func model(transport: PushTransport = URLSessionTransport()) -> SyncModel {
        let defaults = UserDefaults(suiteName: "SettingsScreenTests")!
        defaults.removePersistentDomain(forName: "SettingsScreenTests")
        return SyncModel(defaults: defaults, health: nil, transport: transport)
    }

    override func tearDown() async throws {
        Keychain.delete(.token)
        Keychain.delete(.anchors)
    }

    func testAnAddressMustBeHTTPSAndATokenMustBeAPhoneToken() {
        let m = model()
        XCTAssertEqual(m.save(address: "http://kidney.example.org", token: ""),
                       "Type the address of your server. It starts with https://.")
        XCTAssertEqual(m.save(address: "https://kidney.example.org", token: "kha_" + String(repeating: "a", count: 43)),
                       "That is not a phone token. Make one in Settings → Phone shortcuts. It starts with khd_.")
        XCTAssertFalse(m.hasToken)
        XCTAssertNil(m.save(address: " https://kidney.example.org ", token: "khd_" + String(repeating: "a", count: 43)))
        XCTAssertTrue(m.hasToken)
        XCTAssertEqual(m.address, "https://kidney.example.org")
        XCTAssertEqual(m.appURL?.absoluteString, "https://kidney.example.org/")
    }

    func testAnotherServerStartsAgainFromThreeMonthsBack() throws {
        let m = model()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        try Keychain.save(Data("anchor".utf8), as: .anchors)
        XCTAssertNil(m.save(address: "https://one.example.org/", token: ""))
        XCTAssertNotNil(Keychain.read(.anchors))
        XCTAssertNil(m.save(address: "https://two.example.org", token: ""))
        XCTAssertNil(Keychain.read(.anchors))
    }

    func testRemovingTheTokenForgetsTheAnchorsToo() throws {
        let m = model()
        XCTAssertNil(m.save(address: "https://one.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        try Keychain.save(Data("anchor".utf8), as: .anchors)
        m.removeToken()
        XCTAssertFalse(m.hasToken)
        XCTAssertNil(Keychain.read(.anchors))
        XCTAssertEqual(m.status, "The token was removed from this phone.")
    }

    func testTestConnectionSaysWhatTheServerAnswered() async throws {
        let m = model(transport: URLSessionTransport(session: URLSessionTransport.makeSession(protocolClasses: [StubProtocol.self])))
        await m.testConnection()
        XCTAssertEqual(m.checkResult, "Save the address and a token first.")
        XCTAssertNil(m.save(address: "https://kidney.example.org", token: "khd_" + String(repeating: "a", count: 43)))
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil)!, Data(#"{"ok": true}"#.utf8))
        }
        await m.testConnection()
        XCTAssertEqual(m.checkResult, "Connected. The server took the token.")
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 401, httpVersion: nil, headerFields: nil)!, Data())
        }
        await m.testConnection()
        XCTAssertEqual(m.checkResult, ConnectionCheck.badToken.text)
        XCTAssertNil(m.save(address: "https://kidney.example.org", token: ""))
        XCTAssertNil(m.checkResult)  // a new save clears the old answer
    }

    func testTheDayIsThePhonesCalendarDay() {
        XCTAssertEqual(SyncModel.day(Date(timeIntervalSince1970: 0)).count, 10)
    }
}
