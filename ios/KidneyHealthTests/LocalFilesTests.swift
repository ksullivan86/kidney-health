// The local file handler serves only its listed files, under its own scheme and host (design note 38 §5.1, step 0).
@testable import KidneyHealth
import XCTest

final class LocalFilesTests: XCTestCase {
    func testItServesTheListedFiles() throws {
        let page = try XCTUnwrap(LocalFiles.resource(for: LocalFiles.url("/storage-check.html")))
        XCTAssertEqual(page.name, "storage-check")
        XCTAssertEqual(page.mime, "text/html; charset=utf-8")
        XCTAssertNotNil(LocalFiles.resource(for: LocalFiles.url("/storage-check.js")))
        XCTAssertNotNil(Bundle(for: SyncModel.self).url(forResource: "storage-check", withExtension: "js")
                        ?? Bundle.main.url(forResource: "storage-check", withExtension: "js"))
    }

    func testItRefusesEverythingElse() throws {
        for text in ["kidneyhealth-app://local/../Info.plist", "kidneyhealth-app://local/Info.plist", "kidneyhealth-app://other/storage-check.html",
                     "https://local/storage-check.html", "kidneyhealth-app://local/storage-check.html?x=1",
                     "kidneyhealth-app://local/storage-check.html#x", "kidneyhealth-app://local/"] {
            let url = try XCTUnwrap(URL(string: text))
            XCTAssertNil(LocalFiles.resource(for: url), text)
        }
    }

    func testThePageMayNotReachTheNetwork() {
        XCTAssertTrue(LocalFiles.contentSecurityPolicy.contains("connect-src 'none'"))
        XCTAssertTrue(LocalFiles.contentSecurityPolicy.contains("script-src 'self'"))
        XCTAssertFalse(LocalFiles.contentSecurityPolicy.contains("unsafe-inline"))
    }

    func testTheFileCheckCountsOpens() throws {
        try? FileManager.default.removeItem(at: StorageCheck.fileURL)
        XCTAssertTrue(StorageCheck.recordFileOpen(now: Date(timeIntervalSince1970: 0)).hasPrefix("Opened 1 time, first 1970-01-01"))
        XCTAssertTrue(StorageCheck.recordFileOpen().hasPrefix("Opened 2 times, first 1970-01-01"))
        try? FileManager.default.removeItem(at: StorageCheck.fileURL)
    }

    func testThePageReportReadsInPlainWords() {
        let json = #"{"origin":"kidneyhealth-app://local","indexedDB":{"count":3,"first":"2026-11-21T10:00:00.000Z"},"#
            + #""localStorage":{"error":"SecurityError"},"storage":{"persisted":false}}"#
        let text = StorageCheck.describe(json)
        XCTAssertTrue(text.contains("indexedDB: opened 3 times, first 2026-11-21T10:00:00.000Z"))
        XCTAssertTrue(text.contains("localStorage: could not be used (SecurityError)"))
        XCTAssertTrue(text.contains("Kept for good: no"))
        XCTAssertEqual(StorageCheck.describe("not json"), "The page sent no report.")
    }
}
