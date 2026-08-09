from pathlib import Path
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
