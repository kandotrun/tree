from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_STORE = ROOT / "ios" / "TreeWatering" / "Security" / "FirmwareUpdateKeyStore.swift"
SETTINGS = ROOT / "ios" / "TreeWatering" / "Features" / "SettingsView.swift"
VIEW_MODEL = ROOT / "ios" / "TreeWatering" / "App" / "DashboardViewModel.swift"


class FirmwareUpdateUIStructureTests(unittest.TestCase):
    @staticmethod
    def _function(source: str, name: str, next_name: str) -> str:
        start = source.index(f"func {name}")
        end = source.index(f"func {next_name}", start)
        return source[start:end]

    def test_ota_pairing_key_is_device_scoped_and_keychain_only(self) -> None:
        source = KEY_STORE.read_text(encoding="utf-8")

        self.assertIn("import Security", source)
        self.assertIn("kSecClassGenericPassword", source)
        self.assertIn("kSecAttrService", source)
        self.assertIn("kSecAttrAccount", source)
        self.assertIn("kSecAttrAccessibleWhenUnlockedThisDeviceOnly", source)
        self.assertIn("SecItemCopyMatching", source)
        self.assertIn("SecItemAdd", source)
        self.assertNotIn("UserDefaults", source)
        self.assertNotIn("print(", source)

    def test_settings_exposes_physical_pairing_and_explicit_destructive_confirmation(
        self,
    ) -> None:
        source = SETTINGS.read_text(encoding="utf-8")

        self.assertIn("ファームウェア更新", source)
        self.assertIn("ATOM本体のボタン", source)
        self.assertIn("更新アクセスをペアリング", source)
        self.assertIn("更新を確認", source)
        self.assertIn("安定した電源", source)
        self.assertIn("showFirmwareUpdateConfirmation", source)
        self.assertIn("role: .destructive", source)
        self.assertIn("model.currentFirmwareVersion", source)
        self.assertIn("model.availableFirmwareVersion", source)

    def test_firmware_update_gate_requires_idle_pump_off_and_no_control_operation(
        self,
    ) -> None:
        source = VIEW_MODEL.read_text(encoding="utf-8")
        start = source.index("var canManageFirmware: Bool")
        end = source.index("\n    }", start)
        gate = source[start:end]

        self.assertIn("isOnline", gate)
        self.assertIn("status?.state == .idle", gate)
        self.assertIn("status?.pump == false", gate)
        self.assertIn("!isActionInFlight", gate)
        self.assertIn("!isStopping", gate)
        self.assertIn("!holdActive", gate)
        self.assertIn("!isFirmwareUpdateInFlight", gate)

    def test_update_fetches_fresh_challenge_then_uploads_once_without_retry_loop(
        self,
    ) -> None:
        source = VIEW_MODEL.read_text(encoding="utf-8")
        install = self._function(
            source,
            "installConfirmedFirmware()",
            "refreshFirmwareCapability()",
        )

        challenge = "createFirmwareChallenge"
        upload = "installFirmware"
        self.assertLess(install.index(challenge), install.index(upload))
        self.assertEqual(install.count(upload), 1)
        self.assertNotIn("while ", install)
        self.assertNotIn("for ", install)
        self.assertNotIn("retry", install.lower())
        self.assertIn("再送せず", install)

    def test_activation_does_not_automatically_install_or_check_firmware(self) -> None:
        source = VIEW_MODEL.read_text(encoding="utf-8")
        activate = self._function(source, "activate()", "handleSceneInactive()")

        self.assertNotIn("installFirmware", activate)
        self.assertNotIn("checkForFirmwareUpdate", activate)
        self.assertNotIn("pairFirmwareUpdates", activate)


if __name__ == "__main__":
    unittest.main()
