import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import TreeCore

final class URLProtocolStub: URLProtocol, @unchecked Sendable {
    enum StubResult {
        case response(status: Int, body: Data)
        case failure(Error)
    }

    static var handler: ((URLRequest) throws -> StubResult)?
    static var requests: [URLRequest] = []
    static var requestBodies: [Data?] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.requests.append(request)
        Self.requestBodies.append(Self.bodyData(from: request))
        do {
            guard let handler = Self.handler else {
                throw URLError(.badServerResponse)
            }
            switch try handler(request) {
            case let .response(status, body):
                let response = HTTPURLResponse(
                    url: request.url!,
                    statusCode: status,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                )!
                client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
                client?.urlProtocol(self, didLoad: body)
                client?.urlProtocolDidFinishLoading(self)
            case let .failure(error):
                client?.urlProtocol(self, didFailWithError: error)
            }
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}

    private static func bodyData(from request: URLRequest) -> Data? {
        if let body = request.httpBody {
            return body
        }
        guard let stream = request.httpBodyStream else {
            return nil
        }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}

final class AtomAPIClientTests: XCTestCase {
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

    func testInjectedSessionRemainsCallerOwnedAfterClientDeinit() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let injectedSession = URLSession(configuration: configuration)
        var injectedClient: AtomAPIClient? = AtomAPIClient(
            endpoint: try DeviceEndpoint("http://192.168.1.50"),
            session: injectedSession,
            requestTimeout: 5
        )
        XCTAssertNotNil(injectedClient)

        injectedClient = nil

        URLProtocolStub.handler = { _ in
            .response(status: 200, body: Data("still-owned".utf8))
        }
        let (data, response) = try await injectedSession.data(
            from: URL(string: "http://192.168.1.50/ownership-probe")!
        )

        XCTAssertEqual(String(decoding: data, as: UTF8.self), "still-owned")
        XCTAssertEqual((response as? HTTPURLResponse)?.statusCode, 200)
        injectedSession.invalidateAndCancel()
    }

    func testFetchStatusUsesNoStoreGET() async throws {
        URLProtocolStub.handler = { request in
            .response(status: 200, body: Self.statusPayload)
        }

        let status = try await client.fetchStatus()

        XCTAssertEqual(status.state, .idle)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.httpMethod, "GET")
        XCTAssertEqual(request.url?.path, "/v1/status")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Accept"), "application/json")
        XCTAssertEqual(request.cachePolicy, .reloadIgnoringLocalCacheData)
        XCTAssertEqual(request.timeoutInterval, 5)
    }

    func testStartWateringSendsOneBoundedRequest() async throws {
        URLProtocolStub.handler = { request in
            .response(
                status: 202,
                body: Data(
                    #"{"accepted":true,"request_id":"ios-request-1","state":"WATERING","scheduled_ms":10000}"#.utf8
                )
            )
        }

        let acknowledgement = try await client.startWatering(
            requestID: "ios-request-1",
            durationSeconds: 10
        )

        XCTAssertTrue(acknowledgement.accepted)
        XCTAssertEqual(acknowledgement.requestID, "ios-request-1")
        XCTAssertEqual(acknowledgement.scheduledMilliseconds, 10_000)
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.httpMethod, "POST")
        XCTAssertEqual(request.url?.path, "/v1/water")
        XCTAssertEqual(request.value(forHTTPHeaderField: "Content-Type"), "application/json")
        let body = try XCTUnwrap(URLProtocolStub.requestBodies.first ?? nil)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertEqual(json["request_id"] as? String, "ios-request-1")
        XCTAssertEqual(json["duration_sec"] as? Int, 10)
        XCTAssertEqual(json.count, 2)
    }

    func testRedirectDelegateDeclinesRedirect() throws {
        let delegate = NoRedirectURLSessionDelegate()
        let session = URLSession(configuration: .ephemeral)
        let task = session.dataTask(with: URL(string: "http://192.168.1.50/v1/status")!)
        let response = try XCTUnwrap(HTTPURLResponse(
            url: URL(string: "http://192.168.1.50/v1/status")!,
            statusCode: 302,
            httpVersion: "HTTP/1.1",
            headerFields: ["Location": "https://example.com/collect"]
        ))
        let redirected = URLRequest(url: URL(string: "https://example.com/collect")!)
        let completion = expectation(description: "redirect decision")

        delegate.urlSession(
            session,
            task: task,
            willPerformHTTPRedirection: response,
            newRequest: redirected
        ) { request in
            XCTAssertNil(request)
            completion.fulfill()
        }

        wait(for: [completion], timeout: 1)
    }

    func testTransportFailureDoesNotRetryWatering() async throws {
        URLProtocolStub.handler = { _ in
            .failure(URLError(.timedOut))
        }

        do {
            _ = try await client.startWatering(requestID: "ios-timeout", durationSeconds: 10)
            XCTFail("Expected timeout")
        } catch {
            XCTAssertEqual((error as? URLError)?.code, .timedOut)
        }
        XCTAssertEqual(URLProtocolStub.requests.count, 1)
    }

    func testHTTPErrorPreservesFirmwareCode() async {
        URLProtocolStub.handler = { _ in
            .response(status: 409, body: Data(#"{"error":"boot_guard"}"#.utf8))
        }

        do {
            _ = try await client.startWatering(requestID: "ios-rejected", durationSeconds: 10)
            XCTFail("Expected HTTP error")
        } catch {
            XCTAssertEqual(error as? AtomAPIError, .http(status: 409, code: "boot_guard"))
        }
    }

    func testStopSendsEmptyJSONBody() async throws {
        URLProtocolStub.handler = { _ in
            .response(status: 200, body: Data(#"{"stopped":true,"state":"IDLE"}"#.utf8))
        }

        let acknowledgement = try await client.stop()

        XCTAssertTrue(acknowledgement.stopped)
        let request = try XCTUnwrap(URLProtocolStub.requests.first)
        XCTAssertEqual(request.url?.path, "/v1/stop")
        let body = try XCTUnwrap(URLProtocolStub.requestBodies.first ?? nil)
        let json = try XCTUnwrap(JSONSerialization.jsonObject(with: body) as? [String: Any])
        XCTAssertTrue(json.isEmpty)
    }

    private static let statusPayload = Data(
        #"{"state":"IDLE","pump":false,"uptime_ms":528831,"wifi_rssi":-69,"moisture_adc":1692,"armed":true,"default_duration_sec":10,"max_duration_sec":180,"scheduled_ms":10000,"watering_mode":"NONE","hold_lease_ms":1500,"hold_max_run_ms":600000,"hold_lease_remaining_ms":0,"last_request_id":"ios-example","remaining_ms":0,"last_runtime_ms":10000,"last_stop_reason":"DOSE_COMPLETE","firmware_version":"0.4.1"}"#.utf8
    )
}
