import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public final class FirmwareReleaseClient: @unchecked Sendable {
    private static let releasesURL = URL(
        string: "https://api.github.com/repos/kandotrun/tree/releases?per_page=20"
    )!
    private static let allowedHosts: Set<String> = [
        "api.github.com",
        "github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    ]
    private static let manifestAssetName = "firmware-manifest.json"
    private static let maximumManifestBytes = 64 * 1024

    private let session: URLSession
    private let requestTimeout: TimeInterval

    public convenience init(requestTimeout: TimeInterval = 30) {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = requestTimeout
        configuration.timeoutIntervalForResource = max(requestTimeout, 180)
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.init(
            session: URLSession(configuration: configuration),
            requestTimeout: requestTimeout
        )
    }

    public init(session: URLSession, requestTimeout: TimeInterval) {
        self.session = session
        self.requestTimeout = requestTimeout
    }

    public func fetchLatestPackage(
        for capability: FirmwareCapability
    ) async throws -> FirmwarePackage? {
        var releasesRequest = try request(url: Self.releasesURL)
        releasesRequest.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        releasesRequest.setValue("2022-11-28", forHTTPHeaderField: "X-GitHub-Api-Version")
        let (releaseData, _) = try await fetch(releasesRequest, checkContentLength: false)
        let releases = try JSONDecoder().decode([GitHubRelease].self, from: releaseData)

        let candidates = releases.compactMap { release -> Candidate? in
            guard !release.draft,
                  !release.prerelease,
                  release.tagName.hasPrefix("firmware-v"),
                  let version = try? SemanticVersion(
                      String(release.tagName.dropFirst("firmware-v".count))
                  ),
                  let manifestAsset = release.assets.first(where: {
                      $0.name == Self.manifestAssetName
                  }),
                  manifestAsset.size > 0,
                  manifestAsset.size <= Self.maximumManifestBytes else {
                return nil
            }
            return Candidate(release: release, version: version, manifestAsset: manifestAsset)
        }.sorted { $0.version > $1.version }

        guard let candidate = candidates.first else { return nil }
        let manifestURL = try validatedGitHubURL(candidate.manifestAsset.downloadURL)
        let (manifestData, _) = try await fetch(try request(url: manifestURL))
        guard manifestData.count <= Self.maximumManifestBytes else {
            throw FirmwareValidationError.invalidManifest
        }
        let manifest = try JSONDecoder().decode(FirmwareManifest.self, from: manifestData)
        guard manifest.firmwareVersion == candidate.version else {
            throw FirmwareValidationError.invalidManifest
        }
        guard manifest.firmwareVersion > capability.currentVersion else { return nil }
        guard let binaryAsset = candidate.release.assets.first(where: {
            $0.name == manifest.firmwareAsset
        }),
        binaryAsset.size == manifest.size,
        binaryAsset.size <= capability.maxFirmwareBytes else {
            throw FirmwareValidationError.invalidPackage
        }
        let binaryURL = try validatedGitHubURL(binaryAsset.downloadURL)
        let (firmwareData, _) = try await fetch(try request(url: binaryURL))
        return try FirmwarePackage(
            manifest: manifest,
            firmwareData: firmwareData,
            capability: capability
        )
    }

    private func request(url: URL) throws -> URLRequest {
        _ = try validatedGitHubURL(url)
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.httpMethod = "GET"
        request.timeoutInterval = requestTimeout
        request.setValue("TreeWatering/1.0", forHTTPHeaderField: "User-Agent")
        return request
    }

    private func fetch(
        _ request: URLRequest,
        checkContentLength: Bool = true
    ) async throws -> (Data, HTTPURLResponse) {
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              let finalURL = http.url else {
            throw FirmwareValidationError.invalidPackage
        }
        _ = try validatedGitHubURL(finalURL)
        if checkContentLength,
           http.value(forHTTPHeaderField: "Content-Encoding") == nil,
           let rawLength = http.value(forHTTPHeaderField: "Content-Length"),
           let expectedLength = Int(rawLength),
           expectedLength != data.count {
            throw FirmwareValidationError.invalidPackage
        }
        return (data, http)
    }

    private func validatedGitHubURL(_ url: URL) throws -> URL {
        guard url.scheme?.lowercased() == "https",
              let host = url.host?.lowercased(),
              Self.allowedHosts.contains(host),
              url.user == nil,
              url.password == nil else {
            throw FirmwareValidationError.invalidPackage
        }
        return url
    }
}

private struct Candidate {
    let release: GitHubRelease
    let version: SemanticVersion
    let manifestAsset: GitHubAsset
}

private struct GitHubRelease: Decodable {
    let tagName: String
    let draft: Bool
    let prerelease: Bool
    let assets: [GitHubAsset]

    enum CodingKeys: String, CodingKey {
        case tagName = "tag_name"
        case draft
        case prerelease
        case assets
    }
}

private struct GitHubAsset: Decodable {
    let name: String
    let downloadURL: URL
    let size: Int

    enum CodingKeys: String, CodingKey {
        case name
        case downloadURL = "browser_download_url"
        case size
    }
}
