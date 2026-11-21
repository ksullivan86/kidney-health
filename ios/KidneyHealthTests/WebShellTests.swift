// The web shell (design note 38, step 1): the packed web app is served only from its folder, under the app's own scheme, and
// the safety copy lands in Documents.
@testable import KidneyHealth
import XCTest

final class WebShellTests: XCTestCase {
    private func url(_ text: String) throws -> URL { try XCTUnwrap(URL(string: text)) }

    func testItServesFilesInsideTheFolder() throws {
        XCTAssertEqual(WebAppFiles.relativePath(for: WebShellConfig.url("/index.html")), "index.html")
        XCTAssertEqual(WebAppFiles.relativePath(for: WebShellConfig.url("/js/views/settings.js")), "js/views/settings.js")
        XCTAssertEqual(WebAppFiles.relativePath(for: WebShellConfig.url("/css/base.css")), "css/base.css")
    }

    func testItRefusesEverythingElse() throws {
        for text in ["kidneyhealth-app://app/../Info.plist", "kidneyhealth-app://app/js/../../KidneyHealth", "kidneyhealth-app://app/.hidden.js",
                     "kidneyhealth-app://app/", "kidneyhealth-app://app/index.html?x=1", "kidneyhealth-app://app/index.html#top",
                     "kidneyhealth-app://local/index.html", "https://app/index.html", "kidneyhealth-app://app/KidneyHealth",
                     "kidneyhealth-app://app/js//core.js", "kidneyhealth-app://app/Info.plist"] {
            XCTAssertNil(WebAppFiles.relativePath(for: try url(text)), text)
        }
    }

    func testAResolvedPathStaysInsideTheRoot() throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent("webshell-root", isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        let inside = try XCTUnwrap(WebAppFiles.fileURL(for: WebShellConfig.url("/js/core.js"), root: root))
        XCTAssertTrue(inside.path.hasSuffix("/webshell-root/js/core.js"))
        XCTAssertNil(WebAppFiles.fileURL(for: try url("kidneyhealth-app://app/%2E%2E/secret.js"), root: root))
    }

    func testThePackedWebAppIsInTheBundle() throws {
        let root = try XCTUnwrap(WebAppFiles.bundleRoot, "ios/WebApp: run scripts/build_preview.py --device ios/WebApp before building")
        let index = try String(contentsOf: root.appendingPathComponent("index.html"), encoding: .utf8)
        XCTAssertTrue(index.contains("device-flag.js"))
        let flag = try String(contentsOf: root.appendingPathComponent("device-flag.js"), encoding: .utf8)
        XCTAssertTrue(flag.contains("window.KDL_DEVICE = true;"))
    }

    func testTheSafetyCopyIsWrittenToDocuments() throws {
        try? FileManager.default.removeItem(at: SafetyCopy.fileURL)
        SafetyCopy.write("{\"format\":\"kidney-health-export\"}\n")
        let text = try String(contentsOf: SafetyCopy.fileURL, encoding: .utf8)
        XCTAssertTrue(text.contains("kidney-health-export"))
        SafetyCopy.write("") // an empty message never replaces a good copy
        XCTAssertTrue(try String(contentsOf: SafetyCopy.fileURL, encoding: .utf8).contains("kidney-health-export"))
        try? FileManager.default.removeItem(at: SafetyCopy.fileURL)
    }
}
