import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public enum AtomAPIError: Error, Equatable, Sendable {
    case invalidResponse
    case http(status: Int, code: String)
}

final class NoRedirectURLSessionDelegate: NSObject, URLSessionTaskDelegate, @unchecked Sendable {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

public struct WateringAcknowledgement: Codable, Equatable, Sendable {
    public let accepted: Bool
    public let requestID: String
    public let state: AtomState
    public let scheduledMilliseconds: Int

    enum CodingKeys: String, CodingKey {
        case accepted
        case requestID = "request_id"
        case state
        case scheduledMilliseconds = "scheduled_ms"
    }
}

public struct HoldAcknowledgement: Codable, Equatable, Sendable {
    public let accepted: Bool
    public let requestID: String
    public let state: AtomState
    public let wateringMode: String
    public let leaseMilliseconds: Int
    public let maximumRunMilliseconds: Int

    enum CodingKeys: String, CodingKey {
        case accepted
        case requestID = "request_id"
        case state
        case wateringMode = "watering_mode"
        case leaseMilliseconds = "lease_ms"
        case maximumRunMilliseconds = "max_run_ms"
    }
}

public struct HoldRenewalAcknowledgement: Codable, Equatable, Sendable {
    public let renewed: Bool
    public let requestID: String
    public let leaseMilliseconds: Int
    public let remainingMilliseconds: Int

    enum CodingKeys: String, CodingKey {
        case renewed
        case requestID = "request_id"
        case leaseMilliseconds = "lease_ms"
        case remainingMilliseconds = "remaining_ms"
    }
}

public struct StopAcknowledgement: Codable, Equatable, Sendable {
    public let stopped: Bool
    public let state: AtomState
}

public protocol AtomAPI: Sendable {
    func fetchStatus() async throws -> AtomStatus
    func startWatering(requestID: String, durationSeconds: Int) async throws
        -> WateringAcknowledgement
    func startHold(requestID: String) async throws -> HoldAcknowledgement
    func renewHold(requestID: String) async throws -> HoldRenewalAcknowledgement
    func stop() async throws -> StopAcknowledgement
}

public final class AtomAPIClient: AtomAPI, @unchecked Sendable {
    private struct RequestIDPayload: Encodable {
        let requestID: String

        enum CodingKeys: String, CodingKey {
            case requestID = "request_id"
        }
    }

    private struct WateringPayload: Encodable {
        let requestID: String
        let durationSeconds: Int

        enum CodingKeys: String, CodingKey {
            case requestID = "request_id"
            case durationSeconds = "duration_sec"
        }
    }

    private struct EmptyPayload: Encodable {}
    private struct ErrorPayload: Decodable { let error: String }

    private let endpoint: DeviceEndpoint
    private let session: URLSession
    private let requestTimeout: TimeInterval
    private let retainedSessionDelegate: NoRedirectURLSessionDelegate?
    private let ownsSession: Bool

    public init(
        endpoint: DeviceEndpoint,
        session: URLSession,
        requestTimeout: TimeInterval = 5
    ) {
        self.endpoint = endpoint
        self.session = session
        self.requestTimeout = requestTimeout
        retainedSessionDelegate = nil
        ownsSession = false
    }

    private init(
        endpoint: DeviceEndpoint,
        session: URLSession,
        requestTimeout: TimeInterval,
        retainedSessionDelegate: NoRedirectURLSessionDelegate
    ) {
        self.endpoint = endpoint
        self.session = session
        self.requestTimeout = requestTimeout
        self.retainedSessionDelegate = retainedSessionDelegate
        ownsSession = true
    }

    public convenience init(endpoint: DeviceEndpoint, requestTimeout: TimeInterval = 5) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = requestTimeout
        configuration.timeoutIntervalForResource = requestTimeout
        let delegate = NoRedirectURLSessionDelegate()
        self.init(
            endpoint: endpoint,
            session: URLSession(
                configuration: configuration,
                delegate: delegate,
                delegateQueue: nil
            ),
            requestTimeout: requestTimeout,
            retainedSessionDelegate: delegate
        )
    }

    deinit {
        if ownsSession {
            session.finishTasksAndInvalidate()
        }
    }

    public func fetchStatus() async throws -> AtomStatus {
        try await send(path: "v1/status", method: "GET", response: AtomStatus.self)
    }

    public func startWatering(
        requestID: String,
        durationSeconds: Int
    ) async throws -> WateringAcknowledgement {
        try await send(
            path: "v1/water",
            method: "POST",
            payload: WateringPayload(requestID: requestID, durationSeconds: durationSeconds),
            response: WateringAcknowledgement.self
        )
    }

    public func startHold(requestID: String) async throws -> HoldAcknowledgement {
        try await send(
            path: "v1/hold/start",
            method: "POST",
            payload: RequestIDPayload(requestID: requestID),
            response: HoldAcknowledgement.self
        )
    }

    public func renewHold(requestID: String) async throws -> HoldRenewalAcknowledgement {
        try await send(
            path: "v1/hold/keepalive",
            method: "POST",
            payload: RequestIDPayload(requestID: requestID),
            response: HoldRenewalAcknowledgement.self
        )
    }

    public func stop() async throws -> StopAcknowledgement {
        try await send(
            path: "v1/stop",
            method: "POST",
            payload: EmptyPayload(),
            response: StopAcknowledgement.self
        )
    }

    private func send<Response: Decodable>(
        path: String,
        method: String,
        response: Response.Type
    ) async throws -> Response {
        let request = makeRequest(path: path, method: method)
        return try await perform(request: request, response: response)
    }

    private func send<Payload: Encodable, Response: Decodable>(
        path: String,
        method: String,
        payload: Payload,
        response: Response.Type
    ) async throws -> Response {
        var request = makeRequest(path: path, method: method)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(payload)
        return try await perform(request: request, response: response)
    }

    private func makeRequest(path: String, method: String) -> URLRequest {
        var request = URLRequest(
            url: endpoint.url(for: path),
            cachePolicy: .reloadIgnoringLocalCacheData,
            timeoutInterval: requestTimeout
        )
        request.httpMethod = method
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        // The ATOM server prefers one request per socket; URLSession may still manage
        // this reserved header according to its own connection policy.
        request.setValue("close", forHTTPHeaderField: "Connection")
        return request
    }

    private func perform<Response: Decodable>(
        request: URLRequest,
        response: Response.Type
    ) async throws -> Response {
        let (data, urlResponse) = try await session.data(for: request)
        guard let httpResponse = urlResponse as? HTTPURLResponse else {
            throw AtomAPIError.invalidResponse
        }
        guard (200 ... 299).contains(httpResponse.statusCode) else {
            let code = (try? JSONDecoder().decode(ErrorPayload.self, from: data).error)
                ?? "http_error"
            throw AtomAPIError.http(status: httpResponse.statusCode, code: code)
        }
        return try JSONDecoder().decode(Response.self, from: data)
    }
}
