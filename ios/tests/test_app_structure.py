import json
import re
import unittest
from pathlib import Path

IOS_ROOT = Path(__file__).resolve().parents[1]


class IOSAppStructureTests(unittest.TestCase):
    def test_project_declares_local_network_permissions(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")

        self.assertIn("NSLocalNetworkUsageDescription", project)
        self.assertIn("NSAllowsLocalNetworking", project)
        self.assertIn("NSExceptionDomains", project)
        for network in [
            "10.0.0.0/8",
            "127.0.0.0/8",
            "169.254.0.0/16",
            "172.16.0.0/12",
            "192.168.0.0/16",
            "fc00::/7",
            "fe80::/10",
        ]:
            self.assertIn(network, project)
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
        workflow = (IOS_ROOT.parent / ".github/workflows/ios.yml").read_text(
            encoding="utf-8"
        )
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("TreeWatering-setup.png", workflow)
        self.assertIn("TreeWatering-dashboard.png", workflow)
        self.assertIn("TreeWatering-watering.png", workflow)
        self.assertIn('"-ui-preview"', view_model)
        self.assertIn('"-ui-preview-watering"', view_model)

    def test_dashboard_preview_fixture_is_valid_json(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        matches = re.findall(r'Data\(#"(.+?)"#\.utf8\)', view_model)
        self.assertEqual(len(matches), 2)
        payloads = [json.loads(value) for value in matches]
        required = {
            "state",
            "pump",
            "armed",
            "watering_mode",
            "moisture_adc",
            "default_duration_sec",
            "max_duration_sec",
            "scheduled_ms",
            "remaining_ms",
            "hold_lease_ms",
            "hold_max_run_ms",
            "hold_lease_remaining_ms",
            "uptime_ms",
            "wifi_rssi",
            "firmware_version",
            "last_request_id",
            "last_runtime_ms",
            "last_stop_reason",
            "error_reason",
        }
        for payload in payloads:
            self.assertEqual(required - payload.keys(), set())
            self.assertTrue(payload["armed"])
        self.assertEqual(
            [payload["state"] for payload in payloads], ["IDLE", "WATERING"]
        )
        self.assertEqual([payload["pump"] for payload in payloads], [False, True])

    def test_emergency_stop_is_fixed_outside_scroll_content(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn(".safeAreaInset(edge: .bottom", dashboard)
        scroll_start = dashboard.index("LazyVStack")
        scroll_end = dashboard.index(".refreshable")
        inset_index = dashboard.index(".safeAreaInset(edge: .bottom")
        toolbar_index = dashboard.index(".toolbar(.hidden")
        self.assertLess(inset_index, toolbar_index)
        self.assertNotIn("StopCard(model: model)", dashboard[scroll_start:scroll_end])

    def test_manual_stop_invalidates_pending_hold_completion(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("holdOperationGeneration += 1", view_model)
        self.assertIn("let generationAtStart = holdOperationGeneration", view_model)
        self.assertIn("holdOperationGeneration != generationAtStart", view_model)
        self.assertIn("holdStartTask?.cancel()", view_model)
        self.assertIn(
            "coordinator.beginHold(operationGeneration: generationAtStart)",
            view_model,
        )
        self.assertIn(
            "coordinator.stop(operationGeneration: generationAtStop)",
            view_model,
        )
        self.assertIn(
            "coordinator.endHold(operationGeneration: operationGeneration)",
            view_model,
        )
        self.assertNotIn("_ = try? await coordinator.stop()", view_model)
        hold_ended = view_model[
            view_model.index("func holdGestureEnded()") : view_model.index("private func install")
        ]
        self.assertIn("guard !isStopping", hold_ended)

    def test_unconfirmed_stop_blocks_new_watering_start(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        can_start = view_model[
            view_model.index("var canStartWatering") : view_model.index("var shouldShowStop")
        ]
        self.assertIn("&& !stopRecommended", can_start)

    def test_endpoint_change_is_blocked_during_watering_operations(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        endpoint_change_guards = view_model[
            view_model.index("var canAttemptEndpointChange") : view_model.index("func activate()")
        ]
        for state in [
            "isActionInFlight",
            "isStopping",
            "holdGestureActive",
            "holdStartInFlight",
            "holdEndInFlight",
            "holdActive",
            "shouldShowStop",
        ]:
            self.assertIn(state, endpoint_change_guards)

    def test_offline_endpoint_change_requires_physical_stop_confirmation(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        settings = (IOS_ROOT / "TreeWatering/Features/SettingsView.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("showForceEndpointConfirmation", view_model)
        self.assertIn("connectionState == .offline", view_model)
        self.assertIn("confirmOfflineEndpointChange", view_model)
        self.assertIn("canAttemptEndpointChange", settings)
        self.assertIn("ポンプが停止していることを直接確認", settings)

    def test_endpoint_change_invalidates_inflight_status_refresh(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        refresh = view_model[
            view_model.index("private func refresh()") : view_model.index(
                "private func performHoldEnd"
            )
        ]
        install = view_model[
            view_model.index("private func install") : view_model.index(
                "private func startPolling"
            )
        ]
        self.assertIn("endpointGeneration += 1", install)
        self.assertIn("let generationAtStart = endpointGeneration", refresh)
        self.assertIn("endpointGeneration == generationAtStart", refresh)
        self.assertIn("activeRefreshGeneration", refresh)
        self.assertIn(
            "await coordinator?.reconcile(status: latest)\n"
            "            guard endpointGeneration == generationAtStart else { return }\n"
            "            await syncSafetyState()",
            refresh,
        )

        sync_safety_state = view_model[
            view_model.index("private func syncSafetyState") : view_model.index(
                "private func endpointErrorMessage"
            )
        ]
        self.assertIn("let generationAtStart = endpointGeneration", sync_safety_state)
        self.assertIn(
            "guard endpointGeneration == generationAtStart else { return }",
            sync_safety_state,
        )

    def test_owned_url_session_is_invalidated_on_client_deinit(self) -> None:
        client = (IOS_ROOT / "TreeCore/AtomAPIClient.swift").read_text(encoding="utf-8")
        self.assertIn("private let ownsSession", client)
        self.assertIn("ownsSession = false", client)
        self.assertIn("ownsSession = true", client)
        self.assertIn("if ownsSession", client)
        self.assertIn("session.finishTasksAndInvalidate()", client)

    def test_ipv6_url_normalization_uses_encoded_host(self) -> None:
        endpoint = (IOS_ROOT / "TreeCore/DeviceEndpoint.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("percentEncodedHost", endpoint)

    def test_setup_does_not_force_keyboard_on_first_launch(self) -> None:
        setup = (IOS_ROOT / "TreeWatering/Features/SetupView.swift").read_text(
            encoding="utf-8"
        )
        self.assertIsNone(
            re.search(r"\.onAppear\s*\{[^}]*endpointFocused", setup, re.DOTALL)
        )

    def test_setup_associates_validation_error_with_address_field(self) -> None:
        setup = (IOS_ROOT / "TreeWatering/Features/SetupView.swift").read_text(
            encoding="utf-8"
        )
        self.assertIsNotNone(
            re.search(
                r"\.accessibilityHint\s*\(\s*model\.endpointValidationMessage\s*\?\?",
                setup,
                re.DOTALL,
            )
        )

    def test_icon_regeneration_dependency_and_command_are_documented(self) -> None:
        requirements = IOS_ROOT / "scripts/requirements.txt"
        self.assertTrue(requirements.is_file())
        self.assertIn("Pillow==", requirements.read_text(encoding="utf-8"))
        readme = (IOS_ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("pip install -r scripts/requirements.txt", readme)
        self.assertIn("python3 scripts/generate_icon.py", readme)

    def test_icon_generator_uses_bounded_gradient_working_size(self) -> None:
        script = (IOS_ROOT / "scripts/generate_icon.py").read_text(encoding="utf-8")
        self.assertIn("GRADIENT_SIZE", script)
        self.assertIn("gradient.resize", script)

    def test_repository_does_not_embed_installed_device_address(self) -> None:
        runtime_sources = (
            [IOS_ROOT / "project.yml"]
            + sorted((IOS_ROOT / "TreeCore").rglob("*.swift"))
            + sorted((IOS_ROOT / "TreeWatering").rglob("*.swift"))
        )
        committed_sources = [IOS_ROOT / "README.md"] + runtime_sources
        text = "\n".join(
            path.read_text(encoding="utf-8") for path in committed_sources
        )
        runtime_text = "\n".join(
            path.read_text(encoding="utf-8") for path in runtime_sources
        )

        allowed_placeholders = {
            "10.0.0.0",
            "127.0.0.0",
            "127.0.0.1",
            "169.254.0.0",
            "172.16.0.0",
            "192.168.0.0",
            "fc00::",
            "fe80::",
        }
        private_ipv4 = re.compile(
            r"\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"
            r"|\b192\.168\.\d{1,3}\.\d{1,3}\b"
            r"|\b169\.254\.\d{1,3}\.\d{1,3}\b"
            r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
        )
        private_ipv6 = re.compile(
            r"(?i)(?<![0-9a-f:])"
            r"(?:f[cd][0-9a-f]{2}|fe[89ab][0-9a-f])"
            r"(?::[0-9a-f]{0,4}){1,7}(?![0-9a-f:])"
        )
        self.assertEqual(
            set(private_ipv6.findall("fd12:3456::99 fe80::abcd")),
            {"fd12:3456::99", "fe80::abcd"},
        )
        found_addresses = (
            set(private_ipv4.findall(text)) | set(private_ipv6.findall(text))
        ) - allowed_placeholders
        self.assertEqual(found_addresses, set())

        for host in re.findall(
            r"https?://([a-z0-9.-]+)", runtime_text, re.IGNORECASE
        ):
            self.assertTrue(
                host in allowed_placeholders or host.endswith(".local"),
                f"public host embedded in iOS source: {host}",
            )


if __name__ == "__main__":
    unittest.main()
