// Connected devices on the paired server (owner, 2026-11-26): the app carries the person's status, Sync now and Disconnect for
// each company by name, and the Whoop days, and never the start of a connection or its way back (the server's own page does that).
import Foundation
import XCTest
@testable import KidneyHealthCore

final class DeviceRouteTests: XCTestCase {
    func testTheDeviceRoutesAreCarriedByName() {
        XCTAssertNotNil(ServerAPI.route(method: "GET", path: "/push/v1/api/devices"))
        for company in ["withings", "whoop"] {
            XCTAssertNotNil(ServerAPI.route(method: "POST", path: "/push/v1/api/devices/\(company)/sync"))
            XCTAssertNotNil(ServerAPI.route(method: "DELETE", path: "/push/v1/api/devices/\(company)"))
            XCTAssertNotNil(ServerAPI.route(method: "DELETE", path: "/push/v1/api/devices/\(company)?delete_readings=true"))
        }
        XCTAssertNotNil(ServerAPI.route(method: "GET", path: "/push/v1/api/activity?start=2026-10-01&end=2026-11-26"))
        XCTAssertNotNil(ServerAPI.route(method: "PUT", path: "/push/v1/api/activity/extra"))
        for (method, path) in [
            ("POST", "/push/v1/api/devices/withings/start"), ("POST", "/push/v1/api/devices/whoop/start"),
            ("GET", "/push/v1/api/devices/withings/callback?code=x&state=y"), ("POST", "/push/v1/api/devices/fitbit/sync"),
            ("DELETE", "/push/v1/api/devices"), ("DELETE", "/push/v1/api/devices/withings?all=1"),
            ("GET", "/push/v1/api/activity?days=9"), ("POST", "/push/v1/api/activity/extra"),
            ("GET", "/push/v1/api/shared/1/activity"),
        ] {
            XCTAssertNil(ServerAPI.route(method: method, path: path), "\(method) \(path)")
        }
    }
}
