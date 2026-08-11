import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import TreeCore

final class AtomFirmwareAPIClientTests: XCTestCase {
    private var session: URLSession!
    private var client: AtomAPIClient!

    override func setUpWithError() throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        session = URLSession(configuration: configuration)
        client = AtomAPIClient(
            endpoint: try DeviceEndpoint("http://192.168.1.50"),
            session: session,
            requestTimeout: 5
        )
        URLProtocolStub.requests = []
        URLProtocolStub.requestBodies = []
        URLProtocolStub.handler = nil
    }

    override func tearDown() {
        session.invalidateAndCancel()
        session = nil
        client = nil
        URLProtocolStub.handler = nil
        URLProtocolStub.requests = []
        URLProtocolStub.requestBodies = []
    }

    func testClientConformsToSeparateFirmwareProtocol() {
        let firmwareAPI: any AtomFirmwareAPI = client
        XCTAssertNotNil(firmwareAPI)
    }

    func testFetchFirmwareCapabilityUsesGETRoute() async throws {
        URLProtocolStub.handler = { _ in
            .response(status: 200, body: Self.capabilityPayload)
        }

        let capability = try await client.fetchFirmwareCapability()

        XCTAssertEqual(capability.currentVersion, try SemanticVersion("1.2.3"))
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/v1/firmware")
        XCTAssertEqual(request.timeoutInterval, 5)
    }

    func testPairFirmwarePostsExactlyEmptyJSON() async throws {
        let otaKey = String(repeating: "01", count: 32)
        URLProtocolStub.handler = { _ in
            .response(
                status: 200,
                body: Data(#"{"paired":true,"ota_key":"\#(otaKey)"}"#.utf8)
            )
        }

        let response = try await client.pairFirmware()

        XCTAssertTrue(response.paired)
        XCTAssertEqual(response.otaKey, otaKey)
        try assertSingleEmptyJSONPost(path: "/v1/firmware/pair")
    }

    func testChallengePostsExactlyEmptyJSON() async throws {
        let nonce = String(repeating: "ab", count: 32)
        URLProtocolStub.handler = { _ in
            .response(
                status: 200,
                body: Data(#"{"nonce":"\#(nonce)","expires_in_ms":30000}"#.utf8)
            )
        }

        let response = try await client.requestFirmwareChallenge()

        XCTAssertEqual(response.nonce, nonce)
        XCTAssertEqual(response.expiresInMilliseconds, 30_000)
        try assertSingleEmptyJSONPost(path: "/v1/firmware/challenge")
    }

    func testUpdateFirmwareSendsOneMultipartPOSTWithContractHeadersAndBinary() async throws {
        let package = try makeBinaryPackage()
        let nonce = String(repeating: "ab", count: 32)
        let signature = String(repeating: "cd", count: 32)
        let otaKey = String(repeating: "01", count: 32)
        URLProtocolStub.handler = { _ in
            .response(
                status: 202,
                body: Data(#"{"accepted":true,"firmware_version":"1.2.4","restarting":true}"#.utf8)
            )
        }

        let response = try await client.updateFirmware(
            package: package,
            nonce: nonce,
            signature: signature
        )

        XCTAssertTrue(response.accepted)
        XCTAssertEqual(response.firmwareVersion, try SemanticVersion("1.2.4"))
        XCTAssertTrue(response.restarting)
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/v1/firmware/update")
        XCTAssertEqual(request.timeoutInterval, 120)
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Tree-Firmware-Target"), "m5stack-atom")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Tree-Firmware-Version"), "1.2.4")
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Tree-Firmware-Size"), "5")
        XCTAssertEqual(
            request.value(forHTTPHeaderField: "X-Tree-Firmware-SHA256"),
            "1151e4df6045153a472d1444fa216651a6c8bd93002410147de4ad3a4399ee0c"
        )
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Tree-Firmware-Nonce"), nonce)
        XCTAssertEqual(request.value(forHTTPHeaderField: "X-Tree-Firmware-Signature"), signature)
        XCTAssertNil(request.value(forHTTPHeaderField: "X-Tree-OTA-Key"))

        let contentType = try XCTUnwrap(request.value(forHTTPHeaderField: "Content-Type"))
        let boundaryPrefix = "multipart/form-data; boundary="
        XCTAssertTrue(contentType.hasPrefix(boundaryPrefix))
        let boundary = String(contentType.dropFirst(boundaryPrefix.count))
        var expectedBody = Data(
            ("--\(boundary)\r\n"
                + "Content-Disposition: form-data; name=\"firmware\"; filename=\"firmware.bin\"\r\n"
                + "Content-Type: application/octet-stream\r\n\r\n").utf8
        )
        expectedBody.append(Self.binaryFirmware)
        expectedBody.append(Data("\r\n--\(boundary)--\r\n".utf8))
        let body = try XCTUnwrap(URLProtocolStub.requestBodies.first ?? nil)
        XCTAssertEqual(body, expectedBody)
        XCTAssertFalse(String(decoding: body, as: UTF8.self).contains(otaKey))
    }

    func testUpdateTransportTimeoutIsNeverRetried() async throws {
        URLProtocolStub.handler = { _ in .failure(URLError(.timedOut)) }

        do {
            _ = try await client.updateFirmware(
                package: makeBinaryPackage(),
                nonce: String(repeating: "ab", count: 32),
                signature: String(repeating: "cd", count: 32)
            )
            XCTFail("Expected timeout")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .timedOut)
        }
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
    }

    func testUpdatePreservesFirmwareErrorCode() async throws {
        URLProtocolStub.handler = { _ in
            .response(status: 401, body: Data(#"{"error":"invalid_signature"}"#.utf8))
        }

        do {
            _ = try await client.updateFirmware(
                package: makeBinaryPackage(),
                nonce: String(repeating: "ab", count: 32),
                signature: String(repeating: "cd", count: 32)
            )
            XCTFail("Expected firmware rejection")
        } catch {
            XCTAssertEqual(
                error as? AtomAPIError,
                .http(status: 401, code: "invalid_signature")
            )
        }
    }

    func testUpdateRequiresAccepted202Response() async throws {
        URLProtocolStub.handler = { _ in
            .response(
                status: 200,
                body: Data(#"{"accepted":true,"firmware_version":"1.2.4","restarting":true}"#.utf8)
            )
        }

        do {
            _ = try await client.updateFirmware(
                package: makeBinaryPackage(),
                nonce: String(repeating: "ab", count: 32),
                signature: String(repeating: "cd", count: 32)
            )
            XCTFail("Expected invalid response")
        } catch {
            XCTAssertEqual(error as? AtomAPIError, .invalidResponse)
        }
    }

    private func assertSingleEmptyJSONPost(path: String) throws {
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, path)
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let body = try XCTUnwrap(URLProtocolStub.requestBodies.first ?? nil)
        let object = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertTrue(object.isEmpty)
    }

    private func makeBinaryPackage() throws -> FirmwarePackage {
        let capability = try JSONDecoder().decode(
            FirmwareCapability.self,
            from: Self.capabilityPayload
        )
        let manifest = try JSONDecoder().decode(
            FirmwareManifest.self,
            from: Data(
                #"{"schema_version":1,"device_type":"tree-watering","target":"m5stack-atom","firmware_version":"1.2.4","firmware_asset":"firmware.bin","sha256":"1151e4df6045153a472d1444fa216651a6c8bd93002410147de4ad3a4399ee0c","size":5}"#.utf8
            )
        )
        return try FirmwarePackage(
            manifest: manifest,
            firmwareData: Self.binaryFirmware,
            capability: capability
        )
    }

    private static let binaryFirmware = Data([0x00, 0xff, 0x10, 0x0d, 0x0a])
    private static let capabilityPayload = Data(
        #"{"device_type":"tree-watering","api_version":1,"target":"m5stack-atom","current_version":"1.2.3","ota_supported":true,"paired":true,"pairing_window_open":false,"max_firmware_bytes":1048576}"#.utf8
    )
}
