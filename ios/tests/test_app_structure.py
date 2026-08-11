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

    def test_bonjour_contract_matches_firmware_and_info_plist(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")
        firmware = (IOS_ROOT.parent / "firmware/src/main.cpp").read_text(
            encoding="utf-8"
        )
        firmware_config = (
            IOS_ROOT.parent / "firmware/include/config.example.h"
        ).read_text(encoding="utf-8")
        workflow = (IOS_ROOT.parent / ".github/workflows/ios.yml").read_text(
            encoding="utf-8"
        )
        discovery_path = IOS_ROOT / "TreeWatering/Networking/BonjourDeviceDiscovery.swift"
        self.assertTrue(discovery_path.exists())
        discovery = discovery_path.read_text(encoding="utf-8")

        self.assertIn("NSBonjourServices", project)
        self.assertIn('"_tree-watering._tcp"', project)
        self.assertIn("#include <ESPmDNS.h>", firmware)
        self.assertIn("MDNS.begin(DEVICE_NAME)", firmware)
        self.assertIn("MDNS.setInstanceName(DEVICE_NAME)", firmware)
        self.assertIn('MDNS.addService("tree-watering", "tcp", kHttpPort)', firmware)
        for marker in [
            'response["device_type"] = "tree-watering"',
            'response["api_version"] = 1',
            'response["device_name"] = DEVICE_NAME',
        ]:
            self.assertIn(marker, firmware)
        self.assertIn('#define DEVICE_NAME "balcony-watering"', firmware_config)
        self.assertEqual(workflow.count('      - "firmware/src/main.cpp"'), 2)
        self.assertEqual(
            workflow.count('      - "firmware/include/config.example.h"'),
            2,
        )
        self.assertIn("NWBrowser", discovery)
        self.assertIn("BonjourDeviceCandidate.serviceType", discovery)

    def test_setup_scans_automatically_with_manual_fallback(self) -> None:
        setup = (IOS_ROOT / "TreeWatering/Features/SetupView.swift").read_text(
            encoding="utf-8"
        )
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn("端末を探しています", setup)
        self.assertIn("もう一度探す", setup)
        self.assertIn("手動で設定", setup)
        self.assertIn("func startDiscovery()", view_model)
        self.assertIn("guard api == nil", view_model)
        self.assertIn("startDiscovery()", view_model[view_model.index("func activate()") :])

    def test_setup_omits_redundant_explanation_but_keeps_live_status(self) -> None:
        setup = (IOS_ROOT / "TreeWatering/Features/SetupView.swift").read_text(
            encoding="utf-8"
        )

        self.assertNotIn("同じWi-Fiの端末を探し、", setup)
        self.assertNotIn("クラウドやアカウントは使いません", setup)
        self.assertNotIn("検索はローカルネットワーク内だけで行います", setup)
        self.assertIn("Text(model.discoveryMessage)", setup)

    def test_watering_countdown_keeps_seconds_and_adds_progress_ring(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        status = dashboard[
            dashboard.index("private struct StatusCard") : dashboard.index(
                "private struct MetricTile"
            )
        ]

        self.assertIn('Text("あと約 \\(max(1,', status)
        self.assertIn("WateringCountdownProgress.remainingFraction", status)
        self.assertIn(".trim(from: 0, to: remainingFraction)", status)
        self.assertIn(".rotationEffect(.degrees(-90))", status)

    def test_unarmed_idle_status_explains_why_watering_controls_are_disabled(
        self,
    ) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        theme = (IOS_ROOT / "TreeWatering/Design/Theme.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn("model.status?.wateringAvailability.japaneseTitle", dashboard)
        self.assertIn("model.status?.wateringAvailability.japaneseDetail", dashboard)
        self.assertNotIn("model.status?.state.japaneseTitle", dashboard)
        self.assertNotIn("model.status?.state.japaneseDetail", dashboard)
        self.assertIn("extension WateringAvailability", theme)
        self.assertIn('case .unarmed: "給水は無効です"', theme)
        self.assertIn('case .unarmed: "実機テスト後に端末を有効化してください"', theme)
        self.assertIn("model.status?.wateringAvailability == .unarmed", dashboard)
        self.assertIn('"端末が未アームです"', dashboard)

    def test_discovery_validates_read_only_status_before_saving(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("private func validateDiscoveredCandidate", view_model)
        discovery_flow = view_model[
            view_model.index("private func validateDiscoveredCandidate") : view_model.index(
                "private func applyEndpoint"
            )
        ]

        self.assertIn("client.fetchStatus()", discovery_flow)
        self.assertIn("isCompatibleDiscoveryTarget", discovery_flow)
        self.assertIn("applyEndpoint(candidate.endpoint)", discovery_flow)
        for actuator in ["startWatering", "startHold", "renewHold", ".stop("]:
            self.assertNotIn(actuator, discovery_flow)

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

    def test_app_targets_ios_26_and_ci_uses_macos_26(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")
        workflow = (IOS_ROOT.parent / ".github/workflows/ios.yml").read_text(
            encoding="utf-8"
        )
        readme = (IOS_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('deploymentTarget: "26.0"', project)
        self.assertIn("runs-on: macos-26", workflow)
        self.assertNotIn("UIRequiresFullScreen", project)
        self.assertIn("Xcode 26", readme)
        self.assertIn("iOS 26 or later", readme)

    def test_primary_surfaces_use_native_liquid_glass_apis(self) -> None:
        sources = "\n".join(
            (IOS_ROOT / relative_path).read_text(encoding="utf-8")
            for relative_path in [
                "TreeWatering/Design/Theme.swift",
                "TreeWatering/Features/SetupView.swift",
                "TreeWatering/Features/DashboardView.swift",
            ]
        )

        self.assertIn("GlassEffectContainer", sources)
        self.assertGreaterEqual(sources.count(".glassEffect("), 4)
        self.assertIn(".buttonStyle(.glass)", sources)
        self.assertIn(".buttonStyle(.glassProminent)", sources)

    def test_content_cards_avoid_glass_on_glass(self) -> None:
        theme = (IOS_ROOT / "TreeWatering/Design/Theme.swift").read_text(
            encoding="utf-8"
        )
        card = theme[
            theme.index("struct TreeCardModifier") : theme.index("extension View")
        ]

        self.assertNotIn(".glassEffect(", card)
        self.assertIn(".background(Color.white.opacity(0.72))", card)

    def test_settings_uses_system_toolbar_glass_without_nested_button_styles(self) -> None:
        settings = (IOS_ROOT / "TreeWatering/Features/SettingsView.swift").read_text(
            encoding="utf-8"
        )
        toolbar = settings[settings.index(".toolbar {") : settings.index(".alert(")]

        self.assertNotIn(".buttonStyle(.glass", toolbar)

    def test_hold_control_uses_interactive_glass_and_preserves_hold_gesture(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        hold = dashboard[
            dashboard.index("private struct HoldCard") : dashboard.index(
                "private struct StopCard"
            )
        ]

        self.assertIn(".glassEffect(", hold)
        self.assertIn(".interactive(acceptsTouch)", hold)
        self.assertIn("DragGesture(minimumDistance: 0)", hold)
        self.assertIn("model.holdGestureBegan()", hold)
        self.assertIn("model.holdGestureEnded()", hold)

    def test_emergency_stop_remains_opaque_immediate_and_retryable(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        stop = dashboard[
            dashboard.index("private struct StopCard") : dashboard.index(
                "private struct NoticeBanner"
            )
        ]

        self.assertIn(".background(Color.treeWarning)", stop)
        self.assertIn(".clipShape(", stop)
        self.assertIn("Text(\"今すぐ停止\")", stop)
        self.assertNotIn(".glassEffect(", stop)
        self.assertNotIn(".buttonStyle(.glass", stop)
        self.assertNotIn(".disabled(model.isStopping)", stop)
        self.assertNotIn(
            ".transition(.move(edge: .bottom).combined(with: .opacity))",
            dashboard,
        )
        self.assertNotIn(
            ".animation(.spring(response: 0.34, dampingFraction: 0.86), value: model.shouldShowStop)",
            dashboard,
        )

    def test_manual_stop_allows_retry_while_confirmation_is_pending(self) -> None:
        view_model = (
            IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift"
        ).read_text(encoding="utf-8")
        stop_now = view_model[
            view_model.index("func stopNow()") : view_model.index(
                "func holdGestureBegan()"
            )
        ]

        self.assertNotIn("guard !isStopping", stop_now)
        self.assertIn("activeStopRequests += 1", stop_now)
        self.assertIn("activeStopRequests -= 1", stop_now)
        self.assertIn("isStopping = activeStopRequests > 0", stop_now)

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
        self.assertIn(
            ".padding(.bottom, model.shouldShowStop ? 136 : 28)",
            dashboard,
        )

    def test_disabled_dose_action_uses_readable_dark_foreground(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )
        dose = dashboard[
            dashboard.index("private struct DoseCard") : dashboard.index(
                "private struct HoldCard"
            )
        ]

        self.assertIn(
            "model.canStartWatering ? Color.white : Color.treeInk",
            dose,
        )

    def test_manual_stop_invalidates_pending_hold_completion(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        self.assertIn("operationGeneration += 1", view_model)
        self.assertIn("let generationAtStart = operationGeneration", view_model)
        self.assertIn("operationGeneration != generationAtStart", view_model)
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

    def test_stop_remains_visible_during_every_actuation_request(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )
        should_show_stop = view_model[
            view_model.index("var shouldShowStop") : view_model.index(
                "var canAttemptEndpointChange"
            )
        ]
        for state in [
            "isActionInFlight",
            "isStopping",
            "holdStartInFlight",
            "holdEndInFlight",
            "holdActive",
        ]:
            self.assertIn(state, should_show_stop)

    def test_status_adoption_is_invalidated_across_every_actuation(self) -> None:
        view_model = (IOS_ROOT / "TreeWatering/App/DashboardViewModel.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn("StatusAdoptionGate()", view_model)
        self.assertEqual(view_model.count("statusAdoptionGate.beginOperation()"), 4)
        self.assertEqual(view_model.count("statusAdoptionGate.endOperation()"), 4)

        refresh = view_model[
            view_model.index("private func refresh()") : view_model.index(
                "private func performHoldEnd"
            )
        ]
        self.assertIn("statusAdoptionGate.beginStatusRequest()", refresh)
        self.assertIn(
            "let statusObservation = await coordinator.beginStatusObservation()",
            refresh,
        )
        self.assertIn("observation: statusObservation", refresh)
        self.assertGreaterEqual(
            refresh.count("statusAdoptionGate.canAdopt(statusToken)"),
            3,
        )
        self.assertIn("await syncSafetyState(statusToken: statusToken)", refresh)

        dose = view_model[
            view_model.index("    func startConfirmedDose()") : view_model.index(
                "    func stopNow()"
            )
        ]
        self.assertIn("operationGeneration += 1", dose)
        self.assertIn("operationGeneration: generationAtStart", dose)
        self.assertGreaterEqual(view_model.count("beginStatusObservation()"), 2)
        self.assertGreaterEqual(view_model.count("observation: statusObservation"), 2)

        sync_safety = view_model[
            view_model.index("private func syncSafetyState") : view_model.index(
                "private func endpointErrorMessage"
            )
        ]
        self.assertIn("statusToken: StatusAdoptionGate.Token? = nil", sync_safety)
        self.assertIn("statusAdoptionGate.canAdopt(statusToken)", sync_safety)
        self.assertIn("snapshot.revision > lastSafetySnapshotRevision", sync_safety)
        self.assertIn("lastSafetySnapshotRevision = snapshot.revision", sync_safety)

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
            "await coordinator.reconcile(\n"
            "                status: latest,\n"
            "                observation: statusObservation\n"
            "            )\n"
            "            guard endpointGeneration == generationAtStart,\n"
            "                  statusAdoptionGate.canAdopt(statusToken) else { return }\n"
            "            await syncSafetyState(statusToken: statusToken)",
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

    def test_endpoint_input_placeholders_include_required_scheme_and_contrast(self) -> None:
        placeholder = 'prompt: Text("例：http://<ATOMのLAN内IP>")'
        contrast = ".foregroundStyle(Color.treeInk.opacity(0.55))"
        for relative_path in [
            "TreeWatering/Features/SetupView.swift",
            "TreeWatering/Features/SettingsView.swift",
        ]:
            source = (IOS_ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn(placeholder, source)
            self.assertIn(contrast, source)

    def test_glass_backdrop_has_structured_water_and_leaf_shapes(self) -> None:
        theme = (IOS_ROOT / "TreeWatering/Design/Theme.swift").read_text(
            encoding="utf-8"
        )
        backdrop = theme[
            theme.index("struct TreeGlassBackdrop") : theme.index(
                "struct TreeCardModifier"
            )
        ]

        self.assertIn('Image(systemName: "drop.fill")', backdrop)
        self.assertIn('Image(systemName: "leaf.fill")', backdrop)

    def test_tertiary_labels_keep_readable_contrast(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn("Color.treeInk.opacity(0.58)", dashboard)
        self.assertIn("Color.treeInk.opacity(0.62)", dashboard)

    def test_hold_safety_copy_avoids_orphaned_ending(self) -> None:
        dashboard = (IOS_ROOT / "TreeWatering/Features/DashboardView.swift").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "通信が途切れても、端末側の安全機構が1.5秒以内に停止します",
            dashboard,
        )
        self.assertNotIn("通信が途切れた場合も、", dashboard)

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
