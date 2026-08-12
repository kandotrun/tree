from __future__ import annotations

import json
import unittest
from pathlib import Path

IOS_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = IOS_ROOT / "TreeWatering/Features/DashboardView.swift"
SETUP = IOS_ROOT / "TreeWatering/Features/SetupView.swift"
SETTINGS = IOS_ROOT / "TreeWatering/Features/SettingsView.swift"
THEME = IOS_ROOT / "TreeWatering/Design/Theme.swift"
ROOT_VIEW = IOS_ROOT / "TreeWatering/App/RootView.swift"
WORKFLOW = IOS_ROOT.parent / ".github/workflows/ios.yml"
ACCENT = IOS_ROOT / "TreeWatering/Resources/Assets.xcassets/AccentColor.colorset/Contents.json"
PROJECT = IOS_ROOT / "project.yml"
UI_TESTS = IOS_ROOT / "TreeWateringUITests/TreeWateringAccessibilityUITests.swift"


class AppleNativeUIStructureTests(unittest.TestCase):
    def test_root_respects_system_appearance_and_sets_one_app_tint(self) -> None:
        source = ROOT_VIEW.read_text(encoding="utf-8")

        self.assertNotIn(".preferredColorScheme(", source)
        self.assertIn(".tint(Color.treeAccent)", source)

    def test_dashboard_uses_native_navigation_list_and_toolbar(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("NavigationStack", source)
        self.assertIn("List {", source)
        self.assertIn('.navigationTitle("木のみず")', source)
        self.assertIn("ToolbarItem(placement: .topBarTrailing)", source)
        self.assertIn('Image(systemName: "gearshape")', source)

        for decorative_marker in [
            "TreeGlassBackdrop",
            "BALCONY WATERING",
            "dashboardHeader",
            "StatusOrb",
            "MetricTile",
            ".treeCard()",
        ]:
            self.assertNotIn(decorative_marker, source)

    def test_dashboard_has_one_clear_primary_watering_action(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertEqual(source.count("model.requestDoseConfirmation()"), 1)
        self.assertIn("Picker(\"給水時間\"", source)
        self.assertIn(".pickerStyle(.menu)", source)
        self.assertIn(
            'Text("\\(model.selectedDurationSeconds)秒間給水を開始")',
            source,
        )
        self.assertIn(".buttonStyle(.borderedProminent)", source)
        self.assertIn("if !model.shouldShowStop", source)
        self.assertNotIn('Image(systemName: "arrow.right")', source)

    def test_watering_state_prioritizes_remaining_time_and_system_progress(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("private struct DeviceStatusHeader", source)
        self.assertIn("model.status?.wateringAvailability", source)
        self.assertIn('Text("残り \\(remainingSeconds)秒")', source)
        self.assertIn("ProgressView(value: remainingFraction)", source)
        self.assertIn(".monospacedDigit()", source)

    def test_watering_controls_are_hidden_while_stop_is_recommended(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        list_body = source[source.index("List {") : source.index(".listStyle(")]

        self.assertIn("if !model.shouldShowStop", list_body)
        self.assertIn("WateringControlsSection(model: model)", list_body)
        self.assertIn("HoldControlSection(model: model)", list_body)

    def test_watering_state_hides_secondary_navigation(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        list_body = source[source.index("List {") : source.index(".listStyle(")]
        toolbar = source[source.index(".toolbar {") : source.index(".safeAreaInset(")]

        protected = list_body[list_body.index("if !model.shouldShowStop {") :]
        self.assertIn("WateringControlsSection(model: model)", protected)
        self.assertIn("HoldControlSection(model: model)", protected)
        self.assertIn("DeviceInfoView(model: model)", protected)
        self.assertIn("if !model.shouldShowStop {", toolbar)
        self.assertIn("model.showSettings = true", toolbar)

    def test_watering_header_omits_redundant_connection_row_above_stop_bar(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        header = source[
            source.index("private struct DeviceStatusHeader") : source.index(
                "private struct WateringControlsSection"
            )
        ]

        self.assertIn("if !model.shouldShowStop {", header)
        self.assertIn("Label(connectionLabel, systemImage: connectionSymbol)", header)

    def test_emergency_stop_is_native_fixed_immediate_and_retryable(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        stop = source[
            source.index("private struct EmergencyStopBar") : source.index(
                "private struct InlineNotice"
            )
        ]

        self.assertIn(".safeAreaInset(edge: .bottom", source)
        self.assertIn('Text("給水を停止")', stop)
        self.assertIn(".buttonStyle(.borderedProminent)", stop)
        self.assertIn(".tint(.red)", stop)
        self.assertIn(".background(.bar)", stop)
        self.assertNotIn(".disabled(model.isStopping)", stop)
        self.assertNotIn(".glassEffect(", stop)

    def test_raw_device_metrics_move_to_a_native_detail_screen(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")

        self.assertIn("private struct DeviceInfoView", source)
        self.assertIn('Section("デバイス")', source)
        self.assertIn('LabeledContent("土センサー")', source)
        self.assertIn('LabeledContent("信号強度")', source)
        self.assertIn('LabeledContent("ファームウェア")', source)
        self.assertNotIn("private struct MetricTile", source)

    def test_setup_is_a_single_purpose_native_device_add_flow(self) -> None:
        source = SETUP.read_text(encoding="utf-8")

        self.assertIn("NavigationStack", source)
        self.assertIn("ContentUnavailableView", source)
        self.assertIn('.navigationTitle("デバイスを追加")', source)
        self.assertIn('Button("デバイスのアドレスを入力")', source)
        self.assertIn(".controlSize(.large)", source)
        self.assertIn("private struct ManualEndpointView", source)
        self.assertNotIn("TreeGlassBackdrop", source)
        self.assertNotIn("GlassEffectContainer", source)
        self.assertNotIn('.font(.system(size: 42', source)

    def test_settings_uses_plain_native_form_sections(self) -> None:
        source = SETTINGS.read_text(encoding="utf-8")

        self.assertIn("Form {", source)
        self.assertIn('Section("接続")', source)
        self.assertIn('Text("ファームウェア")', source)
        self.assertIn('.navigationTitle("設定")', source)
        self.assertIn("@State private var endpointDraft", source)
        self.assertIn("text: $endpointDraft", source)
        self.assertIn('Button("キャンセル")', source)
        self.assertIn("model.saveEndpoint(endpointDraft)", source)
        self.assertIn("!endpointChanged", source)
        self.assertNotIn('Section("このアプリ")', source)
        self.assertNotIn('LabeledContent("クラウド"', source)
        self.assertNotIn("TreeGlassBackdrop", source)
        self.assertNotIn(".scrollContentBackground(.hidden)", source)
        self.assertNotIn(".presentationDetents(", source)

    def test_theme_uses_semantic_colors_without_decorative_scene_chrome(self) -> None:
        source = THEME.read_text(encoding="utf-8")
        accent = json.loads(ACCENT.read_text(encoding="utf-8"))

        self.assertIn("static let treeAccent", source)
        self.assertIn("static let treeActionFill", source)
        self.assertIn('Color("AccentColor")', source)
        self.assertNotIn("static let treeAccent = Color(red:", source)
        self.assertNotIn(".systemGreen", source)
        self.assertNotIn("LinearGradient", source)
        self.assertNotIn("TreeGlassBackdrop", source)
        self.assertNotIn("TreeCardModifier", source)
        self.assertNotIn("treeCard()", source)

        colors = accent["colors"]
        self.assertEqual(len(colors), 2)
        dark = next(
            color
            for color in colors
            if color.get("appearances")
            == [{"appearance": "luminosity", "value": "dark"}]
        )
        light = next(color for color in colors if "appearances" not in color)

        def components(color: dict[str, object]) -> tuple[float, float, float]:
            values = color["color"]["components"]  # type: ignore[index]
            return (
                float(values["red"]),
                float(values["green"]),
                float(values["blue"]),
            )

        def luminance(rgb: tuple[float, float, float]) -> float:
            linear = tuple(
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
                for value in rgb
            )
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

        def contrast(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
            lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
            return (lighter + 0.05) / (darker + 0.05)

        self.assertGreaterEqual(contrast(components(light), (1.0, 1.0, 1.0)), 4.5)
        self.assertGreaterEqual(
            contrast(components(dark), (28 / 255, 28 / 255, 30 / 255)),
            4.5,
        )

    def test_primary_copy_uses_semantic_foreground_styles(self) -> None:
        sources = "\n".join(
            path.read_text(encoding="utf-8") for path in [DASHBOARD, SETUP, SETTINGS]
        )

        self.assertGreaterEqual(sources.count(".foregroundStyle(.secondary)"), 5)
        self.assertNotIn("Color.treeInk.opacity", sources)

    def test_hold_control_has_a_distinct_pressed_state(self) -> None:
        source = DASHBOARD.read_text(encoding="utf-8")
        view_model = (
            IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift"
        ).read_text(encoding="utf-8")
        hold = source[
            source.index("private struct HoldControlSection") : source.index(
                "private struct DeviceInfoView"
            )
        ]

        self.assertIn('model.holdGestureActive ? "給水中・離すと停止"', hold)
        self.assertIn(".listRowBackground(", hold)
        self.assertIn("Color.blue.opacity(0.12)", hold)
        self.assertIn(".accessibilityAddTraits(.isButton)", hold)
        self.assertIn(
            "if !model.shouldShowStop || model.shouldKeepHoldControlVisible",
            source,
        )

        keep_visible = view_model[
            view_model.index("var shouldKeepHoldControlVisible") : view_model.index(
                "var canAttemptEndpointChange"
            )
        ]
        for marker in ["holdGestureActive", "holdStartInFlight", "holdActive"]:
            self.assertIn(marker, keep_visible)

    def test_ci_captures_settings_alongside_operational_states(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")
        view_model = (
            IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift"
        ).read_text(encoding="utf-8")

        self.assertIn("TreeWatering-settings.png", workflow)
        self.assertIn("TreeWatering-dashboard-dark.png", workflow)
        for screenshot in [
            "TreeWatering-dashboard-ax5.png",
            "TreeWatering-watering-ax5.png",
            "TreeWatering-settings-ax5.png",
        ]:
            self.assertIn(screenshot, workflow)
        self.assertIn("simctl ui \"$simulator_id\" appearance dark", workflow)
        self.assertIn(
            'simctl ui "$simulator_id" content_size accessibility-extra-extra-extra-large',
            workflow,
        )
        self.assertIn("-ui-preview-settings", workflow)
        self.assertIn('"-ui-preview-settings"', view_model)
        self.assertNotIn('DeviceEndpoint("http://127.0.0.1")', view_model)
        self.assertIn('DeviceEndpoint("http://balcony-watering.local")', view_model)
        self.assertIn('"firmware_version":"0.6.0"', view_model)
        self.assertIn('"ota_supported":true', view_model)

        refresh = view_model[
            view_model.index("func refreshFirmwareCapability()") : view_model.index(
                "func refreshNow()"
            )
        ]
        self.assertIn("guard !isPreviewMode else { return }", refresh)

    def test_ax5_scroll_reachability_is_exercised_by_xcuitest(self) -> None:
        project = PROJECT.read_text(encoding="utf-8")
        workflow = WORKFLOW.read_text(encoding="utf-8")
        source = UI_TESTS.read_text(encoding="utf-8")

        self.assertIn("TreeWateringUITests:", project)
        self.assertIn("type: bundle.ui-testing", project)
        self.assertIn("GENERATE_INFOPLIST_FILE: YES", project)
        self.assertIn("TreeWateringUITests", project[project.index("schemes:") :])
        self.assertIn("xcodebuild", workflow)
        self.assertIn("-only-testing:TreeWateringUITests", workflow)
        self.assertIn("timeout-minutes: 30", workflow)
        self.assertIn("-derivedDataPath ios/build", workflow)
        self.assertIn("-parallel-testing-enabled NO", workflow)
        self.assertIn("-test-timeouts-enabled YES", workflow)
        self.assertIn("-default-test-execution-time-allowance 90", workflow)
        self.assertIn("-maximum-test-execution-time-allowance 180", workflow)
        self.assertIn("content_size accessibility-extra-extra-extra-large", workflow)

        for label in [
            'app.staticTexts["デバイス情報"]',
            'app.buttons["更新アクセスをペアリング"]',
            'app.buttons["更新を確認"]',
            'app.buttons["給水を停止"]',
        ]:
            self.assertIn(label, source)
        self.assertIn("app.swipeUp()", source)
        self.assertGreaterEqual(source.count("XCTAssertTrue"), 4)


if __name__ == "__main__":
    unittest.main()
