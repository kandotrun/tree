import XCTest
@testable import TreeCore

final class AtomStatusTests: XCTestCase {
    func testDecodesFirmwareStatusPayload() throws {
        let payload = Data(
            #"{"state":"IDLE","pump":false,"uptime_ms":528831,"wifi_rssi":-69,"moisture_adc":1692,"armed":true,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":10000,"watering_mode":"NONE","hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"last_request_id":"ios-example","remaining_ms":0,"last_runtime_ms":10000,"last_stop_reason":"DOSE_COMPLETE","firmware_version":"0.4.1"}"#.utf8
        )

        let status = try JSONDecoder().decode(AtomStatus.self, from: payload)

        XCTAssertEqual(status.state, .idle)
        XCTAssertFalse(status.pump)
        XCTAssertEqual(status.moistureADC, 1692)
        XCTAssertTrue(status.armed)
        XCTAssertEqual(status.maximumDurationSeconds, 180)
        XCTAssertEqual(status.holdLeaseMilliseconds, 1_500)
        XCTAssertEqual(status.firmwareVersion, "0.4.1")
        XCTAssertTrue(status.canStartWatering)
        XCTAssertFalse(status.isCompatibleDiscoveryTarget)
    }

    func testDiscoveryAcceptsOnlyIdentifiedFirmwareWithExpectedSafetyContract() throws {
        let payload = Data(
            #"{"device_type":"tree-watering","api_version":1,"device_name":"balcony-watering","state":"IDLE","pump":false,"uptime_ms":528831,"wifi_rssi":-69,"moisture_adc":1692,"armed":true,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":0,"watering_mode":"NONE","hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"last_request_id":"","remaining_ms":0,"last_runtime_ms":0,"last_stop_reason":"","firmware_version":"0.5.0"}"#.utf8
        )

        let status = try JSONDecoder().decode(AtomStatus.self, from: payload)

        XCTAssertEqual(status.deviceType, "tree-watering")
        XCTAssertEqual(status.apiVersion, 1)
        XCTAssertEqual(status.deviceName, "balcony-watering")
        XCTAssertTrue(status.isCompatibleDiscoveryTarget)
    }

    func testDiscoveryRejectsMismatchedSafetyContract() throws {
        let payload = Data(
            #"{"device_type":"tree-watering","api_version":1,"device_name":"balcony-watering","state":"IDLE","pump":false,"uptime_ms":1,"wifi_rssi":-69,"moisture_adc":1692,"armed":true,"default_duration_sec":10,"max_duration_sec":181,"scheduled_ms":0,"watering_mode":"NONE","hold_lease_ms":1400,"hold_max_run_ms":600001,"hold_lease_remaining_ms":0,"last_request_id":"","remaining_ms":0,"last_runtime_ms":0,"last_stop_reason":"","firmware_version":"0.5.0"}"#.utf8
        )

        let status = try JSONDecoder().decode(AtomStatus.self, from: payload)

        XCTAssertFalse(status.isCompatibleDiscoveryTarget)
    }

    func testUnknownFirmwareStateRemainsRepresentable() throws {
        let payload = Data(
            #"{"state":"FUTURE_STATE","pump":false,"uptime_ms":1,"wifi_rssi":-70,"moisture_adc":1700,"armed":false,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":0,"watering_mode":"NONE","hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"last_request_id":"","remaining_ms":0,"last_runtime_ms":0,"last_stop_reason":"","firmware_version":"0.5.0"}"#.utf8
        )

        let status = try JSONDecoder().decode(AtomStatus.self, from: payload)

        XCTAssertEqual(status.state, .unknown("FUTURE_STATE"))
        XCTAssertFalse(status.canStartWatering)
    }
}
