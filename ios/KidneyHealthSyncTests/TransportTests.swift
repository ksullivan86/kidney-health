// The request the app sends, and that a redirect is never followed.
import KidneyHealthCore
import XCTest
@testable import KidneyHealthSync

/// Answers every request from a handler set by the test.
final class StubProtocol: URLProtocol {
    nonisolated(unsafe) static var handler: ((URLRequest) -> (HTTPURLResponse, Data))?
    nonisolated(unsafe) static var seen: [URLRequest] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.seen.append(request)
        guard let handler = Self.handler else { return }
        let (response, data) = handler(request)
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

final class TransportTests: XCTestCase {
    let url = URL(string: "https://kidney.example.org/push/v1/body")!

    override func setUp() {
        StubProtocol.seen = []
    }

    private func body(_ request: URLRequest) -> Data? {
        if let data = request.httpBody { return data }
        guard let stream = request.httpBodyStream else { return nil }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let read = stream.read(&buffer, maxLength: buffer.count)
            if read <= 0 { break }
            data.append(buffer, count: read)
        }
        return data
    }

    func testTheRequestIsAJSONPostWithTheBearerToken() async throws {
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!,
             Data(#"{"added": {"weights": 1, "readings": 0}, "already_there": {"weights": 0, "readings": 0}, "refused": {"watch": 0}}"#.utf8))
        }
        let transport = URLSessionTransport(session: URLSessionTransport.makeSession(protocolClasses: [StubProtocol.self]))
        let request = Push.Request(weights: [Push.Weight(at: "2026-10-22T07:15:00-04:00", value: "70.5", unit: "kg", source: "Health")],
                                   readings: [])
        let reply = try await transport.post(try Push.encode(request), to: url, token: "khd_test")
        XCTAssertEqual(reply.status, 200)
        let sent = try XCTUnwrap(StubProtocol.seen.first)
        XCTAssertEqual(sent.httpMethod, "POST")
        XCTAssertEqual(sent.url, url)
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Authorization"), "Bearer khd_test")
        XCTAssertEqual(sent.value(forHTTPHeaderField: "Content-Type"), "application/json")
        XCTAssertNil(sent.value(forHTTPHeaderField: "Cookie"))
        XCTAssertEqual(try JSONDecoder().decode(Push.Request.self, from: try XCTUnwrap(body(sent))), request)
    }

    func testARedirectIsNotFollowed() throws {
        let task = URLSession.shared.dataTask(with: url)
        let response = try XCTUnwrap(HTTPURLResponse(url: url, statusCode: 307, httpVersion: nil,
                                                     headerFields: ["Location": "https://elsewhere.example.com/collect"]))
        var followed: URLRequest? = URLRequest(url: url)
        NoRedirects().urlSession(URLSession.shared, task: task, willPerformHTTPRedirection: response,
                                 newRequest: URLRequest(url: URL(string: "https://elsewhere.example.com/collect")!)) { followed = $0 }
        XCTAssertNil(followed)
    }

    func testAnErrorStatusComesBackAsItIs() async throws {
        StubProtocol.handler = { request in
            (HTTPURLResponse(url: request.url!, statusCode: 429, httpVersion: nil, headerFields: ["Retry-After": "120"])!, Data())
        }
        let transport = URLSessionTransport(session: URLSessionTransport.makeSession(protocolClasses: [StubProtocol.self]))
        let reply = try await transport.post(Data("{}".utf8), to: url, token: "khd_test")
        XCTAssertEqual(reply.status, 429)
        XCTAssertEqual(reply.header("retry-after"), "120")
    }
}
