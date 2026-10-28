// The token is kept in the Keychain for this device only, readable after the first unlock (design note 15, fact I4).
import XCTest
@testable import KidneyHealthSync

final class KeychainTests: XCTestCase {
    override func tearDown() {
        Keychain.delete(.token)
    }

    func testTheTokenIsKeptForThisDeviceOnly() throws {
        try Keychain.save(Data("khd_one".utf8), as: .token)
        try Keychain.save(Data("khd_two".utf8), as: .token)
        XCTAssertEqual(Keychain.read(.token), Data("khd_two".utf8))
        XCTAssertEqual(Keychain.accessibility(.token), kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly as String)
        Keychain.delete(.token)
        XCTAssertNil(Keychain.read(.token))
    }
}
