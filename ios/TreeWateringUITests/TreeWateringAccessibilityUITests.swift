import XCTest

final class TreeWateringAccessibilityUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testDashboardDetailsRemainReachableAtAX5() {
        let app = launch(arguments: ["-ui-preview"])
        let details = app.staticTexts["デバイス情報"]

        assertHittable(details, in: app)
    }

    func testFirmwareActionsRemainReachableAtAX5() {
        let app = launch(arguments: ["-ui-preview-settings"])
        let pair = app.buttons["更新アクセスをペアリング"]
        let check = app.buttons["更新を確認"]

        assertHittable(pair, in: app)
        assertHittable(check, in: app)
    }

    func testEmergencyStopRemainsImmediatelyReachableAtAX5() {
        let app = launch(arguments: ["-ui-preview-watering"])
        let stop = app.buttons["給水を停止"]

        XCTAssertTrue(stop.waitForExistence(timeout: 5))
        XCTAssertTrue(stop.isHittable)
    }

    private func launch(arguments: [String]) -> XCUIApplication {
        let app = XCUIApplication()
        app.launchArguments = arguments
        app.launch()
        XCTAssertTrue(app.wait(for: .runningForeground, timeout: 5))
        return app
    }

    private func assertHittable(
        _ element: XCUIElement,
        in app: XCUIApplication,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        for _ in 0 ..< 8 {
            if element.exists, element.isHittable {
                return
            }
            app.swipeUp()
        }
        XCTAssertTrue(element.exists, file: file, line: line)
        XCTAssertTrue(element.isHittable, file: file, line: line)
    }
}
