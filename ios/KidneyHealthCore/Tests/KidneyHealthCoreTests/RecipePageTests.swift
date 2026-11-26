// A recipe page read on the iPhone keeps the server's rules (tests/data/recipe_page_vectors.json, made by app/recipe_import/fetch.py
// and app/egress.py): which links and addresses may be opened, the limits, and the charset names looked at.
import Foundation
import XCTest
@testable import KidneyHealthCore

final class RecipePageTests: XCTestCase {
    func testTheLimitsAreTheServers() throws {
        let constants = try Vectors.load("recipe_page_vectors.json").object("constants")
        XCTAssertEqual(try constants.int("max_redirects"), RecipePage.maxRedirects)
        XCTAssertEqual(try constants.int("max_page_bytes"), RecipePage.maxPageBytes)
        XCTAssertEqual(try constants.number("deadline_s"), RecipePage.deadline)
        XCTAssertEqual(Set(try XCTUnwrap(constants["allowed_ports"] as? [Int])), RecipePage.allowedPorts)
        XCTAssertEqual(Set(try XCTUnwrap(constants["html_types"] as? [String])), RecipePage.htmlTypes)
    }

    func testEachAddressIsJudgedAsTheServerJudgesIt() throws {
        let cases = try Vectors.load("recipe_page_vectors.json").list("address_cases")
        XCTAssertGreaterThan(cases.count, 50)
        for c in cases {
            let text = try c.text("address")
            let bytes = try XCTUnwrap(RecipePage.parseAddress(text), text)
            XCTAssertEqual(RecipePage.classify(bytes).rawValue, try c.text("class"), text)
        }
    }

    func testEachLinkIsTakenOrRefusedAsThePhoneRuleSays() throws {
        let cases = try Vectors.load("recipe_page_vectors.json").list("link_cases")
        XCTAssertGreaterThan(cases.count, 40)
        for c in cases {
            let url = try c.text("url")
            let ok = try c.text("phone") == "ok"
            XCTAssertEqual(RecipePage.checkLink(url) != nil, ok, url)
            if ok { XCTAssertEqual(try c.text("server"), "ok", "the phone never opens a link the server refuses: \(url)") }
        }
        let link = try XCTUnwrap(RecipePage.checkLink("https://Recipes.Example.com:443/a?b#c"))
        XCTAssertEqual(link, RecipePage.Link(host: "recipes.example.com", port: 443, address: nil))
        XCTAssertEqual(RecipePage.checkLink("https://192.168.1.20/r")?.address, [192, 168, 1, 20])
        XCTAssertEqual(RecipePage.checkLink("https://[::1]:80/")?.port, 80)
    }

    func testTheCharsetNamesAreTheServers() throws {
        for c in try Vectors.load("recipe_page_vectors.json").list("charset_cases") {
            let head = try c.text("head")
            let names = RecipePage.charsetNames(contentType: try c.text("content_type"), head: Array(head.utf8))
            XCTAssertEqual(names, try XCTUnwrap(c["names"] as? [String]), head)
        }
    }

    func testOnlyHTMLIsRead() {
        XCTAssertTrue(RecipePage.isHTML("text/html; charset=utf-8"))
        XCTAssertTrue(RecipePage.isHTML("Application/XHTML+XML"))
        XCTAssertTrue(RecipePage.isHTML(nil))
        XCTAssertFalse(RecipePage.isHTML("application/json"))
        XCTAssertFalse(RecipePage.isHTML("image/png"))
    }

    func testAddressesThatAreNotAddressesAreRefused() {
        for text in ["", "1.2.3", "1.2.3.4.5", "01.2.3.4", "256.1.1.1", "1:2", ":::", "1::2::3", "12345::", "g::1", "fe80::1%en0"] {
            XCTAssertNil(RecipePage.parseAddress(text), text)
        }
        XCTAssertEqual(RecipePage.classify([1, 2, 3]), .denied)
    }
}
