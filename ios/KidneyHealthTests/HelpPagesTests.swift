// The help pages packed with the web app (owner, 2026-11-26): only files inside the help folder, a folder address is its
// index.html, and a query or fragment only picks a place on the page.
@testable import KidneyHealth
import XCTest

final class HelpPagesTests: XCTestCase {
    private func url(_ text: String) throws -> URL { try XCTUnwrap(URL(string: text)) }

    func testAHelpAddressNamesAFileInTheFolder() throws {
        XCTAssertEqual(HelpPages.relativePath(for: try url("kidneyhealth-app://app/learn/")), "learn/index.html")
        XCTAssertEqual(HelpPages.relativePath(for: try url("kidneyhealth-app://app/learn/eat/potassium/")), "learn/eat/potassium/index.html")
        XCTAssertEqual(HelpPages.relativePath(for: try url("kidneyhealth-app://app/learn/eat/potassium/#on-dialysis")), "learn/eat/potassium/index.html")
        XCTAssertEqual(HelpPages.relativePath(for: try url("kidneyhealth-app://app/learn/search/search_index.json?x=1")), "learn/search/search_index.json")
        XCTAssertEqual(HelpPages.relativePath(for: try url("kidneyhealth-app://app/learn/assets/stylesheets/main.css")), "learn/assets/stylesheets/main.css")
    }

    func testEverythingElseIsNotAHelpPage() throws {
        for text in ["kidneyhealth-app://app/index.html", "kidneyhealth-app://app/learn", "kidneyhealth-app://app/learn/../index.html",
                     "kidneyhealth-app://app/learn/%2E%2E/index.html", "kidneyhealth-app://app/learn/.hidden/", "kidneyhealth-app://app/learn//x/",
                     "kidneyhealth-app://app/learn/eat/potassium", "kidneyhealth-app://app/learn/x.plist", "kidneyhealth-app://other/learn/",
                     "https://app/learn/", "kidneyhealth-app://app/learning/"] {
            XCTAssertNil(HelpPages.relativePath(for: try url(text)), text)
        }
    }

    func testTheMainPageServerDoesNotServeAFolderAddress() throws {
        XCTAssertNil(WebAppFiles.relativePath(for: try url("kidneyhealth-app://app/learn/eat/potassium/")))
    }
}
