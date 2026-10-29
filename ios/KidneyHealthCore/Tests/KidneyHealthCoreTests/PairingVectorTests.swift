// The pairing link of the QR code, read as the server reads it (tests/data/pairing_vectors.json, made by app/pairing.py).
import Foundation
import XCTest
@testable import KidneyHealthCore

final class PairingVectorTests: XCTestCase {
    func testTheConstantsAreTheServers() throws {
        let constants = try Vectors.load("pairing_vectors.json").object("constants")
        XCTAssertEqual(try constants.text("scheme"), Pairing.scheme)
        XCTAssertEqual(try constants.text("start"), Pairing.start)
        XCTAssertEqual(try constants.text("version"), Pairing.version)
        XCTAssertEqual(try XCTUnwrap(constants["fields"] as? [String]).sorted(), Pairing.fields)
        XCTAssertEqual(try constants.text("token_prefix"), "khd_")
    }

    func testEveryLinkTheServerMakesReadsBack() throws {
        let cases = try Vectors.load("pairing_vectors.json").list("link_cases")
        XCTAssertGreaterThan(cases.filter { $0["link"] is String }.count, 10)
        for c in cases {
            guard let link = c.optionalText("link") else { continue }
            let got = try XCTUnwrap(Pairing.parse(link), link)
            XCTAssertEqual(got, Pairing.Link(server: try c.text("server"), token: try c.text("token")), link)
        }
    }

    func testEachLinkIsTakenOrRefusedAsTheServerSays() throws {
        let cases = try Vectors.load("pairing_vectors.json").list("parse_cases")
        XCTAssertGreaterThan(cases.filter { $0["refused"] != nil }.count, 30)
        for c in cases {
            let link = try c.text("link")
            if c["refused"] != nil {
                XCTAssertNil(Pairing.parse(link), link)
            } else {
                XCTAssertEqual(Pairing.parse(link), Pairing.Link(server: try c.text("server"), token: try c.text("token")), link)
            }
        }
    }

    func testWhatALinkHoldsIsWhatTheSettingsScreenTakes() throws {
        for c in try Vectors.load("pairing_vectors.json").list("parse_cases") where c["refused"] == nil {
            let got = try XCTUnwrap(Pairing.parse(try c.text("link")))
            XCTAssertNotNil(Settings.pushURL(got.server), got.server)
            XCTAssertTrue(Settings.isDeviceToken(got.token), got.token)
        }
        let link = try XCTUnwrap(Pairing.parse("kidneyhealthsync://pair?v=1&server=https%3A%2F%2Fexample.org%3A8443&token=khd_"
                                               + String(repeating: "A", count: 43)))
        XCTAssertEqual(link.host, "example.org:8443")
    }
}
