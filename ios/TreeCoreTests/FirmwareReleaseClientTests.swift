import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import XCTest
@testable import TreeCore

final class GitHubURLProtocolStub: URLProtocol, @unchecked Sendable {
    struct StubResponse {
        let status: Int
        let body: Data
        var headers: [String: String] = [:]
        var responseURL: URL?
    }

    static var handler: ((URLRequest) throws -> StubResponse)?
    static var requests: [URLRequest] = []

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.requests.append(request)
        do {
            guard let handler = Self.handler else {
                throw URLError(.badServerResponse)
            }
            let stub = try handler(request)
            let response = HTTPURLResponse(
                url: stub.responseURL ?? request.url!,
                statusCode: stub.status,
                httpVersion: "HTTP/1.1",
                headerFields: stub.headers
            )!
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: stub.body)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

final class FirmwareReleaseClientTests: XCTestCase {
    private var session: URLSession!
    private var client: FirmwareReleaseClient!

    override func setUp() {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [GitHubURLProtocolStub.self]
        session = URLSession(configuration: configuration)
        client = FirmwareReleaseClient(session: session, requestTimeout: 10)
        GitHubURLProtocolStub.requests = []
        GitHubURLProtocolStub.handler = nil
    }

    override func tearDown() {
        session.invalidateAndCancel()
        session = nil
        client = nil
        GitHubURLProtocolStub.handler = nil
        GitHubURLProtocolStub.requests = []
    }

    func testDownloadsNewestEligibleReleaseManifestAndMatchingBinary() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/releases/download/firmware-v1.2.4/firmware-manifest.json"
        let binaryURL = "https://release-assets.githubusercontent.com/tree/firmware.bin"
        let releases = try releasesData([
            release(tag: "firmware-v9.0.0", draft: true, assets: [asset("firmware-manifest.json", manifestURL, 200)]),
            release(tag: "firmware-v8.0.0", prerelease: true, assets: [asset("firmware-manifest.json", manifestURL, 200)]),
            release(tag: "app-v7.0.0", assets: [asset("firmware-manifest.json", manifestURL, 200)]),
            release(tag: "firmware-v6.0.0", assets: [asset("notes.txt", manifestURL, 10)]),
            release(
                tag: "firmware-v1.2.4",
                assets: [
                    asset("firmware-manifest.json", manifestURL, manifestData().count),
                    asset("firmware.bin", binaryURL, 5),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            switch request.url?.absoluteString {
            case Self.releasesURL:
                return .init(status: 200, body: releases)
            case manifestURL:
                return .init(status: 200, body: self.manifestData())
            case binaryURL:
                return .init(status: 200, body: Data("hello".utf8))
            default:
                throw URLError(.unsupportedURL)
            }
        }

        let package = try await client.fetchLatestPackage(for: makeCapability())

        XCTAssertEqual(package?.manifest.firmwareVersion, try SemanticVersion("1.2.4"))
        XCTAssertEqual(package?.firmwareData, Data("hello".utf8))
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 3)
        let firstRequest = try XCTUnwrap(GitHubURLProtocolStub.requests.first)
        XCTAssertEqual(firstRequest.url?.absoluteString, Self.releasesURL)
        XCTAssertEqual(firstRequest.httpMethod, "GET")
        XCTAssertEqual(firstRequest.timeoutInterval, 10)
        XCTAssertEqual(firstRequest.value(forHTTPHeaderField: "Accept"), "application/vnd.github+json")
        for request in GitHubURLProtocolStub.requests {
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "User-Agent"),
                "TreeWatering/1.0"
            )
            XCTAssertFalse(
                request.allHTTPHeaderFields?.values.contains(where: {
                    $0.contains(String(repeating: "01", count: 32))
                }) ?? false
            )
        }
    }

    func testChoosesHighestSemanticFirmwareTagInsteadOfAPIOrder() async throws {
        let olderManifestURL = "https://github.com/kandotrun/tree/firmware-v1.2.4.json"
        let newerManifestURL = "https://github.com/kandotrun/tree/firmware-v1.10.0.json"
        let binaryURL = "https://github.com/kandotrun/tree/firmware.bin"
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", olderManifestURL, 200)]
            ),
            release(
                tag: "firmware-v1.10.0",
                assets: [
                    asset("firmware-manifest.json", newerManifestURL, 200),
                    asset("firmware.bin", binaryURL, 5),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            switch request.url?.absoluteString {
            case Self.releasesURL:
                return .init(status: 200, body: releases)
            case newerManifestURL:
                return .init(status: 200, body: self.manifestData(version: "1.10.0"))
            case binaryURL:
                return .init(status: 200, body: Data("hello".utf8))
            default:
                throw URLError(.unsupportedURL)
            }
        }

        let package = try await client.fetchLatestPackage(for: makeCapability())

        XCTAssertEqual(package?.manifest.firmwareVersion, try SemanticVersion("1.10.0"))
        XCTAssertFalse(GitHubURLProtocolStub.requests.contains { $0.url?.absoluteString == olderManifestURL })
    }

    func testRejectsManifestWhoseVersionDiffersFromReleaseTag() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let manifest = manifestData(version: "1.2.4")
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.5",
                assets: [asset("firmware-manifest.json", manifestURL, manifest.count)]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            request.url?.absoluteString == Self.releasesURL
                ? .init(status: 200, body: releases)
                : .init(status: 200, body: manifest)
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 2)
    }

    func testReturnsNilWithoutEligibleRelease() async throws {
        let releases = try releasesData([
            release(tag: "app-v1.2.4", assets: []),
            release(tag: "firmware-v1.2.4", draft: true, assets: []),
            release(tag: "firmware-v1.2.4", prerelease: true, assets: []),
        ])
        GitHubURLProtocolStub.handler = { _ in .init(status: 200, body: releases) }

        let package = try await client.fetchLatestPackage(for: makeCapability())

        XCTAssertNil(package)
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 1)
    }

    func testReturnsNilWhenNewestPackageIsNotNewerWithoutDownloadingBinary() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/releases/download/firmware-v1.2.3/firmware-manifest.json"
        let manifest = manifestData(version: "1.2.3")
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.3",
                assets: [
                    asset("firmware-manifest.json", manifestURL, manifest.count),
                    asset("firmware.bin", "https://github.com/kandotrun/tree/firmware.bin", 5),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            if request.url?.absoluteString == Self.releasesURL {
                return .init(status: 200, body: releases)
            }
            if request.url?.absoluteString == manifestURL {
                return .init(status: 200, body: manifest)
            }
            throw URLError(.unsupportedURL)
        }

        let package = try await client.fetchLatestPackage(for: makeCapability())

        XCTAssertNil(package)
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 2)
    }

    func testRejectsManifestAssetOnWrongHostBeforeRequest() async throws {
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", "https://example.com/manifest.json", 100)]
            ),
        ])
        GitHubURLProtocolStub.handler = { _ in .init(status: 200, body: releases) }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 1)
    }

    func testRejectsBinaryAssetOnWrongHostBeforeRequest() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let manifest = manifestData()
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [
                    asset("firmware-manifest.json", manifestURL, manifest.count),
                    asset("firmware.bin", "https://example.com/firmware.bin", 5),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            request.url?.absoluteString == Self.releasesURL
                ? .init(status: 200, body: releases)
                : .init(status: 200, body: manifest)
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 2)
    }

    func testRejectsRedirectToNonAllowlistedHost() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", manifestURL, manifestData().count)]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            if request.url?.absoluteString == Self.releasesURL {
                return .init(status: 200, body: releases)
            }
            return .init(
                status: 200,
                body: self.manifestData(),
                responseURL: URL(string: "https://evil.example/redirected-manifest.json")
            )
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
    }

    func testRedirectPolicyFollowsOnlyAllowlistedHTTPSURLs() throws {
        let allowed = URLRequest(
            url: try XCTUnwrap(
                URL(string: "https://release-assets.githubusercontent.com/firmware.bin")
            )
        )
        let evil = URLRequest(
            url: try XCTUnwrap(URL(string: "https://evil.example/firmware.bin"))
        )
        let cleartext = URLRequest(
            url: try XCTUnwrap(URL(string: "http://github.com/firmware.bin"))
        )

        XCTAssertEqual(
            FirmwareReleaseRedirectPolicy.allowedRedirect(allowed)?.url,
            allowed.url
        )
        XCTAssertNil(FirmwareReleaseRedirectPolicy.allowedRedirect(evil))
        XCTAssertNil(FirmwareReleaseRedirectPolicy.allowedRedirect(cleartext))
    }

    func testRejectsNon200Response() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", manifestURL, manifestData().count)]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            if request.url?.absoluteString == Self.releasesURL {
                return .init(status: 200, body: releases)
            }
            return .init(
                status: 302,
                body: Data(),
                headers: ["Location": "https://evil.example/manifest.json"]
            )
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
    }

    func testRejectsReleaseAssetMetadataSizeMismatch() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let binaryURL = "https://github.com/kandotrun/tree/firmware.bin"
        let manifest = manifestData()
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [
                    asset("firmware-manifest.json", manifestURL, manifest.count),
                    asset("firmware.bin", binaryURL, 6),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            request.url?.absoluteString == Self.releasesURL
                ? .init(status: 200, body: releases)
                : .init(status: 200, body: manifest)
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
        XCTAssertEqual(GitHubURLProtocolStub.requests.count, 2)
    }

    func testRejectsActualBinarySizeMismatch() async throws {
        try await assertRejectedBinary(Data("hell".utf8), manifest: manifestData())
    }

    func testRejectsActualBinaryHashMismatch() async throws {
        try await assertRejectedBinary(Data("jello".utf8), manifest: manifestData())
    }

    func testRejectsMalformedManifestVersion() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let manifest = manifestData(version: "01.2.4")
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", manifestURL, manifest.count)]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            request.url?.absoluteString == Self.releasesURL
                ? .init(status: 200, body: releases)
                : .init(status: 200, body: manifest)
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
    }

    func testRejectsMismatchedContentLength() async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let manifest = manifestData()
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [asset("firmware-manifest.json", manifestURL, manifest.count)]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            if request.url?.absoluteString == Self.releasesURL {
                return .init(status: 200, body: releases)
            }
            return .init(
                status: 200,
                body: manifest,
                headers: ["Content-Length": String(manifest.count + 1)]
            )
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
    }

    private func assertRejectedBinary(_ binary: Data, manifest: Data) async throws {
        let manifestURL = "https://github.com/kandotrun/tree/firmware-manifest.json"
        let binaryURL = "https://github.com/kandotrun/tree/firmware.bin"
        let releases = try releasesData([
            release(
                tag: "firmware-v1.2.4",
                assets: [
                    asset("firmware-manifest.json", manifestURL, manifest.count),
                    asset("firmware.bin", binaryURL, 5),
                ]
            ),
        ])
        GitHubURLProtocolStub.handler = { request in
            switch request.url?.absoluteString {
            case Self.releasesURL: .init(status: 200, body: releases)
            case manifestURL: .init(status: 200, body: manifest)
            case binaryURL: .init(status: 200, body: binary)
            default: throw URLError(.unsupportedURL)
            }
        }

        await XCTAssertThrowsErrorAsync {
            _ = try await self.client.fetchLatestPackage(for: self.makeCapability())
        }
    }

    private func makeCapability() throws -> FirmwareCapability {
        try JSONDecoder().decode(
            FirmwareCapability.self,
            from: Data(
                #"{"device_type":"tree-watering","api_version":1,"target":"m5stack-atom","current_version":"1.2.3","ota_supported":true,"paired":true,"pairing_window_open":false,"max_firmware_bytes":1048576}"#.utf8
            )
        )
    }

    private func manifestData(version: String = "1.2.4") -> Data {
        Data(
            #"{"schema_version":1,"device_type":"tree-watering","target":"m5stack-atom","firmware_version":"\#(version)","firmware_asset":"firmware.bin","sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824","size":5,"source_sha":"abc123"}"#.utf8
        )
    }

    private func releasesData(_ releases: [[String: Any]]) throws -> Data {
        try JSONSerialization.data(withJSONObject: releases, options: [.sortedKeys])
    }

    private func release(
        tag: String,
        draft: Bool = false,
        prerelease: Bool = false,
        assets: [[String: Any]]
    ) -> [String: Any] {
        ["tag_name": tag, "draft": draft, "prerelease": prerelease, "assets": assets]
    }

    private func asset(_ name: String, _ url: String, _ size: Int) -> [String: Any] {
        ["name": name, "browser_download_url": url, "size": size]
    }

    private static let releasesURL = "https://api.github.com/repos/kandotrun/tree/releases?per_page=20"
}

private func XCTAssertThrowsErrorAsync(
    _ expression: () async throws -> Void,
    file: StaticString = #filePath,
    line: UInt = #line
) async {
    do {
        try await expression()
        XCTFail("Expected expression to throw", file: file, line: line)
    } catch {}
}
