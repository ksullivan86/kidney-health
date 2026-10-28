// The token and the Health anchors, in the Keychain for this device only (design note 15 §4.2, fact I4). They are readable after
// the first unlock, because Health wakes the app while the phone is locked. Nothing else the app keeps is a secret.
import Foundation
import Security

enum Keychain {
    static let service = "io.github.ksullivan86.kidneyhealth.sync"

    enum Item: String {
        case token
        case anchors
    }

    struct Failure: Error, Equatable {
        let status: OSStatus
    }

    static func save(_ data: Data, as item: Item) throws {
        delete(item)
        var query = base(item)
        query[kSecValueData as String] = data
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        let status = SecItemAdd(query as CFDictionary, nil)
        guard status == errSecSuccess else { throw Failure(status: status) }
    }

    static func read(_ item: Item) -> Data? {
        var query = base(item)
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    /// The accessibility class the item was stored with (for the tests).
    static func accessibility(_ item: Item) -> String? {
        var query = base(item)
        query[kSecReturnAttributes as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let attributes = result as? [String: Any] else { return nil }
        return attributes[kSecAttrAccessible as String] as? String
    }

    static func delete(_ item: Item) {
        SecItemDelete(base(item) as CFDictionary)
    }

    private static func base(_ item: Item) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: item.rawValue]
    }
}
