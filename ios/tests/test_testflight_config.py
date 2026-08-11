from __future__ import annotations

import plistlib
import unittest
from pathlib import Path
from typing import Final

IOS_ROOT: Final = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT: Final = IOS_ROOT.parent


class TestTestFlightConfig(unittest.TestCase):
    def test_project_uses_release_version_settings(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")

        self.assertIn('CFBundleShortVersionString: "$(MARKETING_VERSION)"', project)
        self.assertIn('CFBundleVersion: "$(CURRENT_PROJECT_VERSION)"', project)
        self.assertIn('MARKETING_VERSION: "1.0.0"', project)
        self.assertIn('CURRENT_PROJECT_VERSION: "2"', project)
        self.assertIn("DEVELOPMENT_TEAM: UGNVGWZMAU", project)

    def test_project_builds_app_store_resources(self) -> None:
        project = (IOS_ROOT / "project.yml").read_text(encoding="utf-8")

        self.assertIn("- path: TreeWatering/Resources/Assets.xcassets\n        buildPhase: resources", project)
        self.assertIn(
            "- path: TreeWatering/Resources/PrivacyInfo.xcprivacy\n        buildPhase: resources",
            project,
        )

    def test_privacy_manifest_declares_user_defaults_reason(self) -> None:
        with (IOS_ROOT / "TreeWatering/Resources/PrivacyInfo.xcprivacy").open("rb") as file:
            manifest = plistlib.load(file)

        self.assertEqual(manifest["NSPrivacyTracking"], False)
        self.assertEqual(manifest["NSPrivacyCollectedDataTypes"], [])
        self.assertEqual(
            manifest["NSPrivacyAccessedAPITypes"],
            [
                {
                    "NSPrivacyAccessedAPIType": "NSPrivacyAccessedAPICategoryUserDefaults",
                    "NSPrivacyAccessedAPITypeReasons": ["CA92.1"],
                }
            ],
        )

    def test_export_uploads_to_app_store_connect(self) -> None:
        with (IOS_ROOT / "ExportOptions.plist").open("rb") as file:
            options = plistlib.load(file)

        self.assertEqual(options["destination"], "upload")
        self.assertEqual(options["method"], "app-store-connect")
        self.assertEqual(options["signingStyle"], "automatic")
        self.assertEqual(options["teamID"], "UGNVGWZMAU")

    def test_reusable_workflow_archives_and_uploads_pinned_source(self) -> None:
        workflow = (REPOSITORY_ROOT / ".github/workflows/testflight.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("workflow_call:", workflow)
        self.assertIn("ref: ${{ inputs.source_ref }}", workflow)
        self.assertIn("CURRENT_PROJECT_VERSION=\"${{ steps.build.outputs.number }}\"", workflow)
        self.assertIn("xcodebuild archive", workflow)
        self.assertIn("xcodebuild -exportArchive", workflow)
        self.assertIn("if: always()", workflow)


if __name__ == "__main__":
    unittest.main()
