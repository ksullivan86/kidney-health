// A recipe page read on this iPhone with no server (design note 30 §3; ARCHITECTURE.md "Device mode"). The app fetches the page
// the person typed and hands its text to the page, which reads the recipe with the twin of the server's parser. These are the
// rules the server keeps when it reads a page (app/recipe_import/fetch.py, app/egress.py), as pure functions:
//
// * checkLink: the server's check_page_url, and on the phone also https only, plain ASCII, no user name and a plain host name or an
//   IPv6 address in brackets;
// * classify: app/egress.py classify_address: which addresses may be opened (only "global"; a home, local or cloud-internal address
//   never), with the IPv4 address inside IPv6 forms judged as IPv4;
// * charsetNames: the names fetch._charset looks at (the header's, then a <meta> in the first 4096 bytes);
// * the limits: 3 redirects, 2 MiB, 15 seconds in all, HTML only.
//
// tests/data/recipe_page_vectors.json holds the server's answers (tests/data/gen_recipe_page_vectors.py).
import Foundation

public enum RecipePage {
    public static let maxRedirects = 3
    public static let maxPageBytes = 2 * 1024 * 1024
    public static let deadline: TimeInterval = 15
    public static let allowedPorts: Set<Int> = [80, 443]
    public static let htmlTypes: Set<String> = ["text/html", "application/xhtml+xml"]
    /// app/models.py SOURCE_URL_MAX
    public static let maxLinkLength = 900
    /// The server's limit for one person (app/recipe_import/api.py PAGES_PER_HOUR).
    public static let pagesPerHour = 20

    // MARK: - The link

    /// A link the phone may open: the host to look up (lower case, an IPv6 address without its brackets) and the port.
    public struct Link: Equatable, Sendable {
        public let host: String
        public let port: Int
        /// The host is an address written in the link (no look-up needed).
        public let address: [UInt8]?
    }

    /// The link, when the phone may open it; nil when not ("bad_link").
    public static func checkLink(_ text: String) -> Link? {
        let bytes = Array(text.utf8)
        guard !bytes.isEmpty, bytes.count <= maxLinkLength, bytes.allSatisfy({ $0 >= 0x21 && $0 <= 0x7e }) else { return nil }
        guard bytes.count > 8, String(decoding: bytes.prefix(8), as: UTF8.self).lowercased() == "https://" else { return nil }
        let rest = bytes.dropFirst(8)
        let netloc = Array(rest.prefix { $0 != 0x2f && $0 != 0x3f && $0 != 0x23 })  // up to the first "/", "?" or "#"
        guard !netloc.isEmpty, !netloc.contains(0x40), !netloc.contains(0x25) else { return nil }  // no "@", no "%"
        var hostBytes: [UInt8]
        var portBytes: [UInt8] = []
        var address: [UInt8]? = nil
        if netloc.first == 0x5b {  // "[" an IPv6 address "]" (":port")
            guard let close = netloc.firstIndex(of: 0x5d) else { return nil }
            hostBytes = Array(netloc[1..<close])
            let after = netloc[(close + 1)...]
            if !after.isEmpty {
                guard after.first == 0x3a else { return nil }
                portBytes = Array(after.dropFirst())
            }
            guard let parsed = parseAddress(String(decoding: hostBytes, as: UTF8.self)), parsed.count == 16 else { return nil }
            address = parsed
        } else {
            guard !netloc.contains(0x5b), !netloc.contains(0x5d) else { return nil }
            if let colon = netloc.firstIndex(of: 0x3a) {
                hostBytes = Array(netloc[..<colon])
                portBytes = Array(netloc[(colon + 1)...])
            } else {
                hostBytes = netloc
            }
            guard !hostBytes.isEmpty, hostBytes.allSatisfy({ isLetterOrDigit($0) || $0 == 0x2e || $0 == 0x2d || $0 == 0x5f }) else { return nil }
            if let parsed = parseAddress(String(decoding: hostBytes, as: UTF8.self)), parsed.count == 4 { address = parsed }
        }
        var port = 443
        if !portBytes.isEmpty {
            guard portBytes.allSatisfy({ $0 >= 0x30 && $0 <= 0x39 }), let number = Int(String(decoding: portBytes, as: UTF8.self)),
                  allowedPorts.contains(number) else { return nil }
            port = number
        }
        return Link(host: String(decoding: hostBytes, as: UTF8.self).lowercased(), port: port, address: address)
    }

    static func isLetterOrDigit(_ b: UInt8) -> Bool {
        (b >= 0x30 && b <= 0x39) || (b >= 0x41 && b <= 0x5a) || (b >= 0x61 && b <= 0x7a)
    }

    // MARK: - Addresses (app/egress.py classify_address)

    public enum AddressClass: String, Sendable {
        case global
        case `private`
        case denied
    }

    /// May the phone open this address (4 or 16 bytes)? Only `.global`.
    public static func classify(_ address: [UInt8]) -> AddressClass {
        if address.count == 16 {
            if inAny(address, v6Metadata) { return .denied }
            if let inner = embeddedIPv4(address) { return classifyV4(inner) }
            return classifyV6(address)
        }
        if address.count == 4 { return classifyV4(address) }
        return .denied
    }

    static func classifyV4(_ a: [UInt8]) -> AddressClass {
        if inAny(a, v4Metadata) { return .denied }
        if inNet(a, net("127.0.0.0"), 8) { return .private }  // loopback
        if a == [0, 0, 0, 0] || inNet(a, net("224.0.0.0"), 4) || inNet(a, net("240.0.0.0"), 4) || inNet(a, net("169.254.0.0"), 16)
            || inNet(a, net("0.0.0.0"), 8) { return .denied }
        let isPrivate = inAny(a, v4Private) && !inAny(a, v4PrivateExceptions)
        let isGlobal = !inNet(a, net("100.64.0.0"), 10) && !isPrivate
        return isGlobal ? .global : .private
    }

    static func classifyV6(_ a: [UInt8]) -> AddressClass {
        let number = a.prefix(15).allSatisfy { $0 == 0 }
        if number && a[15] == 1 { return .private }  // ::1, loopback
        if (number && a[15] == 0) || inNet(a, net("ff00::"), 8) || inAny(a, v6Reserved) || inNet(a, net("fe80::"), 10) { return .denied }
        let isPrivate = inAny(a, v6Private) && !inAny(a, v6PrivateExceptions)
        return isPrivate ? .private : .global
    }

    /// The IPv4 address an IPv6 address carries (IPv4-mapped, 6to4, Teredo client, NAT64, IPv4-compatible), as Python reads it.
    static func embeddedIPv4(_ a: [UInt8]) -> [UInt8]? {
        let low = Array(a[12..<16])
        if a.prefix(10).allSatisfy({ $0 == 0 }) && a[10] == 0xff && a[11] == 0xff { return low }  // ::ffff:0:0/96
        if a[0] == 0x20 && a[1] == 0x02 { return Array(a[2..<6]) }  // 6to4, 2002::/16
        if a[0] == 0x20 && a[1] == 0x01 && a[2] == 0 && a[3] == 0 { return low.map { ~$0 } }  // Teredo, 2001::/32: the client
        if inNet(a, net("64:ff9b::"), 96) || inNet(a, net("64:ff9b:1::"), 48) { return low }
        if a.prefix(12).allSatisfy({ $0 == 0 }) && !(low == [0, 0, 0, 0] || low == [0, 0, 0, 1]) { return low }  // ::/96 above ::1
        return nil
    }

    typealias Network = (bytes: [UInt8], bits: Int)

    static func net(_ text: String) -> [UInt8] { parseAddress(text)! }
    static func nets(_ list: [(String, Int)]) -> [Network] { list.map { (net($0.0), $0.1) } }

    static let v4Metadata = nets([("169.254.169.254", 32), ("169.254.170.2", 32), ("100.100.100.200", 32)])
    static let v6Metadata = nets([("fd00:ec2::254", 128)])
    static let v4Private = nets([("0.0.0.0", 8), ("10.0.0.0", 8), ("127.0.0.0", 8), ("169.254.0.0", 16), ("172.16.0.0", 12),
                                 ("192.0.0.0", 24), ("192.0.0.170", 31), ("192.0.2.0", 24), ("192.168.0.0", 16), ("198.18.0.0", 15),
                                 ("198.51.100.0", 24), ("203.0.113.0", 24), ("240.0.0.0", 4), ("255.255.255.255", 32)])
    static let v4PrivateExceptions = nets([("192.0.0.9", 32), ("192.0.0.10", 32)])
    static let v6Private = nets([("::1", 128), ("::", 128), ("::ffff:0:0", 96), ("64:ff9b:1::", 48), ("100::", 64), ("2001::", 23),
                                 ("2001:db8::", 32), ("2002::", 16), ("3fff::", 20), ("fc00::", 7), ("fe80::", 10)])
    static let v6PrivateExceptions = nets([("2001:1::1", 128), ("2001:1::2", 128), ("2001:3::", 32), ("2001:4:112::", 48),
                                           ("2001:20::", 28), ("2001:30::", 28)])
    static let v6Reserved = nets([("::", 8), ("100::", 8), ("200::", 7), ("400::", 6), ("800::", 5), ("1000::", 4), ("4000::", 3),
                                  ("6000::", 3), ("8000::", 3), ("a000::", 3), ("c000::", 3), ("e000::", 4), ("f000::", 5),
                                  ("f800::", 6), ("fe00::", 9)])

    static func inAny(_ a: [UInt8], _ list: [Network]) -> Bool { list.contains { inNet(a, $0.bytes, $0.bits) } }

    static func inNet(_ a: [UInt8], _ network: [UInt8], _ bits: Int) -> Bool {
        guard a.count == network.count else { return false }
        var left = bits
        var i = 0
        while left >= 8 {
            if a[i] != network[i] { return false }
            i += 1
            left -= 8
        }
        guard left > 0 else { return true }
        let mask = UInt8(truncatingIfNeeded: 0xff << (8 - left))
        return a[i] & mask == network[i] & mask
    }

    /// An address written as text: 4 bytes for IPv4 (four numbers 0 to 255, no leading zeros), 16 for IPv6 (with "::" and a
    /// dotted IPv4 end); nil for anything else, a zone ("%") included.
    public static func parseAddress(_ text: String) -> [UInt8]? {
        if !text.contains(":") { return parseIPv4(Substring(text)) }
        let halves = text.components(separatedBy: "::")
        guard halves.count <= 2 else { return nil }
        func groups(_ part: String, last: Bool) -> [UInt8]? {
            if part.isEmpty { return [] }
            let pieces = part.split(separator: ":", omittingEmptySubsequences: false)
            var out: [UInt8] = []
            for (k, piece) in pieces.enumerated() {
                if last && k == pieces.count - 1 && piece.contains(".") {
                    guard let v4 = parseIPv4(piece) else { return nil }
                    out += v4
                    continue
                }
                guard (1...4).contains(piece.count), piece.allSatisfy({ $0.isASCII && $0.isHexDigit }),
                      let value = UInt16(piece, radix: 16) else { return nil }
                out += [UInt8(value >> 8), UInt8(value & 0xff)]
            }
            return out
        }
        if halves.count == 1 {
            guard let all = groups(halves[0], last: true), all.count == 16 else { return nil }
            return all
        }
        guard let head = groups(halves[0], last: false), let tail = groups(halves[1], last: true),
              head.count + tail.count <= 14 else { return nil }
        return head + [UInt8](repeating: 0, count: 16 - head.count - tail.count) + tail
    }

    static func parseIPv4(_ text: Substring) -> [UInt8]? {
        let parts = text.split(separator: ".", omittingEmptySubsequences: false)
        guard parts.count == 4 else { return nil }
        var out: [UInt8] = []
        for part in parts {
            guard (1...3).contains(part.count), part.allSatisfy({ $0 >= "0" && $0 <= "9" }), !(part.count > 1 && part.first == "0"),
                  let value = Int(part), value <= 255 else { return nil }
            out.append(UInt8(value))
        }
        return out
    }

    // MARK: - The answer

    /// Is the page HTML? (A missing type counts, as on the server.)
    public static func isHTML(_ contentType: String?) -> Bool {
        let kind = (contentType ?? "").split(separator: ";", maxSplits: 1, omittingEmptySubsequences: false).first
            .map { $0.trimmingCharacters(in: .whitespaces).lowercased() } ?? ""
        return kind.isEmpty || htmlTypes.contains(kind)
    }

    /// The charset names to try, in fetch._charset's order: the Content-Type header's, then a <meta> in the first 4096 bytes.
    public static func charsetNames(contentType: String?, head: [UInt8]) -> [String] {
        var out: [String] = []
        if let name = charsetAfter(Array((contentType ?? "").utf8), from: 0, to: nil, quotes: [0x22], rightmost: false) { out.append(name) }
        let bytes = Array(head.prefix(4096))
        var i = 0
        while i + 5 <= bytes.count {
            if lower(bytes[i..<(i + 5)]) == Array("<meta".utf8) {
                let end = bytes[(i + 5)...].firstIndex(of: 0x3e) ?? bytes.count  // "[^>]+" stops at the first ">"
                if let name = charsetAfter(bytes, from: i + 6, to: end, quotes: [0x22, 0x27], rightmost: true) {
                    out.append(name)
                    break
                }
            }
            i += 1
        }
        return out
    }

    /// `charset\s*=\s*["']?([A-Za-z0-9_\-:.]+)`, case-insensitive, with "charset" starting at or after `from` and before `to`:
    /// the leftmost match, or (inside a <meta>, where the regex's "[^>]+" is greedy) the rightmost.
    static func charsetAfter(_ s: [UInt8], from: Int, to: Int?, quotes: Set<UInt8>, rightmost: Bool) -> String? {
        let limit = min(to ?? s.count, s.count)
        guard limit - from >= 7 else { return nil }
        let starts = Array(from...(limit - 7))
        for p in rightmost ? starts.reversed() : starts {
            guard lower(s[p..<(p + 7)]) == Array("charset".utf8) else { continue }
            var k = p + 7
            while k < s.count && isSpace(s[k]) { k += 1 }
            guard k < s.count, s[k] == 0x3d else { continue }
            k += 1
            while k < s.count && isSpace(s[k]) { k += 1 }
            if k < s.count && quotes.contains(s[k]) { k += 1 }
            let start = k
            while k < s.count && (isLetterOrDigit(s[k]) || [0x5f, 0x2d, 0x3a, 0x2e].contains(s[k])) { k += 1 }
            if k > start { return String(decoding: s[start..<k], as: UTF8.self) }
        }
        return nil
    }

    static func isSpace(_ b: UInt8) -> Bool { b == 0x20 || (b >= 0x09 && b <= 0x0d) }
    static func lower(_ bytes: ArraySlice<UInt8>) -> [UInt8] { bytes.map { $0 >= 0x41 && $0 <= 0x5a ? $0 + 32 : $0 } }
}
