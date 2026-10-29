// The pairing link in the QR code that the web app shows with a new phone token (Settings → Phone shortcuts; design note 15 §4.3):
// kidneyhealthsync://pair?v=1&server=https%3A%2F%2Fkidney.example.org&token=khd_…
// The server builds it (app/pairing.py). This reads it exactly as the server's reference reading does, so a link is taken only in the
// form the server makes. tests/data/pairing_vectors.json holds the server's answers, including the links it refuses.
import Foundation

public enum Pairing {
    /// The scheme the app registers. The server's copy is PAIRING_SCHEME in app/brand.py.
    public static let scheme = "kidneyhealthsync"
    public static let version = "1"
    static let start = "://pair?"
    static let fields = ["server", "token", "v"]

    /// What a pairing link holds: the address to send to and the phone token.
    public struct Link: Equatable, Sendable {
        public let server: String
        public let token: String

        /// The server's name to show in "Pair with …?".
        public var host: String { String(server.dropFirst("https://".count)) }
    }

    /// The address and token of a pairing link, or nil when it is not one exactly as the server makes it.
    public static func parse(_ text: String) -> Link? {
        let bytes = Array(text.utf8)
        guard !bytes.isEmpty, bytes.allSatisfy({ $0 >= 0x21 && $0 <= 0x7e }), !bytes.contains(0x23) else { return nil }  // printable, no #
        guard bytes.count > scheme.utf8.count, String(decoding: bytes.prefix(scheme.utf8.count), as: UTF8.self).lowercased() == scheme,
              String(decoding: bytes.dropFirst(scheme.utf8.count), as: UTF8.self).hasPrefix(start) else { return nil }
        let query = String(decoding: bytes.dropFirst(scheme.utf8.count + start.utf8.count), as: UTF8.self)
        var values: [String: String] = [:]
        var names: [String] = []
        for field in query.split(separator: "&", omittingEmptySubsequences: false) {
            guard let equals = field.firstIndex(of: "="),
                  let name = unescape(field[..<equals]), let value = unescape(field[field.index(after: equals)...]) else { return nil }
            names.append(name)
            values[name] = value
        }
        guard names.sorted() == fields, values["v"] == version,
              let server = values["server"], serverOK(server), let token = values["token"], tokenOK(token) else { return nil }
        return Link(server: server, token: token)
    }

    /// `https://` and a host of letters, digits, dots and hyphens, with an optional port from 1 to 65535, and nothing else.
    static func serverOK(_ server: String) -> Bool {
        guard server.hasPrefix("https://") else { return false }
        let rest = Array(server.utf8.dropFirst("https://".count))
        let colon = rest.firstIndex(of: 0x3a) ?? rest.endIndex
        let host = rest[..<colon]
        guard !host.isEmpty, host.allSatisfy({ isLetterOrDigit($0) || $0 == 0x2e || $0 == 0x2d }) else { return false }
        if colon == rest.endIndex { return true }
        let port = rest[rest.index(after: colon)...]
        guard (1...5).contains(port.count), port.allSatisfy({ $0 >= 0x30 && $0 <= 0x39 }),
              let number = Int(String(decoding: port, as: UTF8.self)) else { return false }
        return (1...65535).contains(number)
    }

    /// `khd_` and 43 base64url characters, with nothing around them.
    static func tokenOK(_ token: String) -> Bool {
        let bytes = Array(token.utf8)
        return bytes.count == 47 && token.hasPrefix("khd_")
            && bytes.dropFirst(4).allSatisfy { isLetterOrDigit($0) || $0 == 0x2d || $0 == 0x5f }
    }

    /// A query name or value: `+` is a space, then percent escapes are read as UTF-8. Nil for an escape that is not one.
    static func unescape(_ part: Substring) -> String? {
        String(part).replacingOccurrences(of: "+", with: " ").removingPercentEncoding
    }

    private static func isLetterOrDigit(_ byte: UInt8) -> Bool {
        (byte >= 0x41 && byte <= 0x5a) || (byte >= 0x61 && byte <= 0x7a) || (byte >= 0x30 && byte <= 0x39)
    }
}
