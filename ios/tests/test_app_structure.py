from pathlib import Path
import json
import re
import unittest

IOS_ROOT = Path(__file__).resolve().parents[1]


class IOSAppStructureTests(unittest.TestCase):
    def test_project_declares_local_network_permissions(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")

        self.assertIn("NSLocalNetworkUsageDescription", project)
        self.assertIn("NSAllowsLocalNetworking", project)
        self.assertNotIn("NSAllowsArbitraryLoads: true", project)

    def test_app_contains_required_safe_control_surfaces(self) -> None:
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted((IOS_ROOT / "TreeWatering").rglob("*.swift"))
        )

        self.assertIn("今すぐ停止", source)
        self.assertIn("押している間だけ給水", source)
        self.assertIn("給水を開始しますか", source)
        self.assertIn("scenePhase", source)
        self.assertIn("handleSceneInactive", source)

    def test_ci_captures_setup_and_dashboard_screens(self) -> None:
        workflow = (IOS_ROOT.parent / ".github/workflows/ios.yml").read_text()
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text()
        self.assertIn("TreeWatering-setup.png", workflow)
        self.assertIn("TreeWatering-dashboard.png", workflow)
        self.assertIn("TreeWatering-watering.png", workflow)
        self.assertIn('"-ui-preview"', view_model)
        self.assertIn('"-ui-preview-watering"', view_model)

    def test_dashboard_preview_fixture_is_valid_json(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text()
        matches = re.findall(r'Data\(#"(.+?)"#\.utf8\)', view_model)
        self.assertEqual(len(matches), 2)
        payloads = [json.loads(value) for value in matches]
        required = {
            "state", "pump", "armed", "watering_mode", "moisture_adc",
            "default_duration_sec", "max_duration_sec", "scheduled_ms", "remaining_ms",
            "hold_lease_ms", "hold_max_run_ms", "hold_lease_remaining_ms",
            "uptime_ms", "wifi_rssi", "firmware_version", "last_request_id",
            "last_runtime_ms", "last_stop_reason", "error_reason",
        }
        for payload in payloads:
            self.assertEqual(required - payload.keys(), set())
            self.assertTrue(payload["armed"])
        self.assertEqual([payload["state"] for payload in payloads], ["IDLE", "WATERING"])
        self.assertEqual([payload["pump"] for payload in payloads], [False, True])

    def test_emergency_stop_is_fixed_outside_scroll_content(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text()
        self.assertIn(".safeAreaInset(edge: .bottom", dashboard)
        scroll_start = dashboard.index("LazyVStack")
        scroll_end = dashboard.index(".refreshable")
        self.assertNotIn("StopCard(model: model)", dashboard[scroll_start:scroll_end])

    def test_setup_does_not_force_keyboard_on_first_launch(self) -> None:
        setup = (IOS_ROOT / "TreeWatering/Features/SetupView.swift").read_text()
        self.assertNotIn(".onAppear { endpointFocused", setup)

    def test_repository_does_not_embed_installed_device_address(self) -> None:
        committed_sources = [IOS_ROOT / "project.yml"] + sorted(
            (IOS_ROOT / "TreeWatering").rglob("*.swift")
        )
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in committed_sources
        )

        self.assertNotIn("192.168.1.244", text)
        self.assertNotIn("tree.2-38.com", text)


if __name__ == "__main__":
    unittest.main()
