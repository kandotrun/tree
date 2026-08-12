import Foundation
import XCTest
@testable import TreeCore

final class SemanticVersionTests: XCTestCase {
    func testAcceptsCanonicalUnsignedThreeComponentVersions() throws {
        for rawValue in ["0.0.0", "1.2.3", "4294967295.0.9"] {
            let version = try SemanticVersion(rawValue)

            XCTAssertEqual(version.rawValue, rawValue)
            XCTAssertEqual(version.description, rawValue)
        }
    }

    func testRejectsNoncanonicalVersions() {
        let invalidVersions = [
            "", "1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03",
            "+1.2.3", "-1.2.3", "1.2.3-beta", "1.2.3+1", " 1.2.3", "1.2.3 ",
            "1..3", "１.2.3", "4294967296.0.0",
        ]

        for rawValue in invalidVersions {
            XCTAssertThrowsError(try SemanticVersion(rawValue), rawValue)
        }
    }

    func testComparesComponentsNumerically() throws {
        XCTAssertLessThan(try SemanticVersion("1.2.9"), try SemanticVersion("1.10.0"))
        XCTAssertLessThan(try SemanticVersion("1.9.9"), try SemanticVersion("2.0.0"))
        XCTAssertEqual(try SemanticVersion("3.4.5"), try SemanticVersion("3.4.5"))
    }

    func testCodableUsesAndValidatesCanonicalString() throws {
        let version = try JSONDecoder().decode(SemanticVersion.self, from: Data(#""1.2.3""#.utf8))

        XCTAssertEqual(version, try SemanticVersion("1.2.3"))
        XCTAssertEqual(try JSONEncoder().encode(version), Data(#""1.2.3""#.utf8))
        XCTAssertThrowsError(
            try JSONDecoder().decode(SemanticVersion.self, from: Data(#""01.2.3""#.utf8))
        )
    }
}
