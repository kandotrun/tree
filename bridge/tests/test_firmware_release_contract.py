from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCRIPT = ROOT / "firmware" / "scripts" / "build_ota_manifest.py"
RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "firmware-release.yml"
CONFIG_EXAMPLE = ROOT / "firmware" / "include" / "config.example.h"
PARTITIONS = ROOT / "firmware" / "partitions.csv"
PLATFORMIO = ROOT / "firmware" / "platformio.ini"


def _run_manifest(
    tmp_path: Path,
    *,
    version: str = "0.6.0",
    size: int = 64,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    binary = tmp_path / "firmware.bin"
    binary.write_bytes(bytes(index % 256 for index in range(size)))
    output = tmp_path / "firmware-manifest.json"
    result = subprocess.run(
        [
            sys.executable,
            str(MANIFEST_SCRIPT),
            "--binary",
            str(binary),
            "--version",
            version,
            "--source-sha",
            "a" * 40,
            "--output",
            str(output),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result, output


def test_manifest_records_exact_generic_firmware_identity(tmp_path: Path) -> None:
    result, output = _run_manifest(tmp_path)

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == {
        "schema_version": 1,
        "device_type": "tree-watering",
        "target": "m5stack-atom",
        "firmware_version": "0.6.0",
        "firmware_asset": "TreeWatering-m5stack-atom-0.6.0.bin",
        "sha256": hashlib.sha256(bytes(range(64))).hexdigest(),
        "size": 64,
        "source_sha": "a" * 40,
    }


def test_manifest_rejects_noncanonical_version(tmp_path: Path) -> None:
    result, output = _run_manifest(tmp_path, version="v0.6")

    assert result.returncode != 0
    assert not output.exists()
    assert "x.y.z" in result.stderr


def test_manifest_rejects_version_component_larger_than_uint32(tmp_path: Path) -> None:
    result, output = _run_manifest(tmp_path, version="4294967296.0.0")

    assert result.returncode != 0
    assert not output.exists()
    assert "32-bit" in result.stderr


def test_manifest_rejects_image_that_cannot_fit_an_ota_partition(tmp_path: Path) -> None:
    result, output = _run_manifest(tmp_path, size=0x140000 + 1)

    assert result.returncode != 0
    assert not output.exists()
    assert "OTA partition" in result.stderr


def test_release_workflow_builds_only_with_safe_generic_config() -> None:
    workflow = RELEASE_WORKFLOW.read_text(encoding="utf-8")
    config = CONFIG_EXAMPLE.read_text(encoding="utf-8")

    assert '"firmware-v*"' in workflow
    assert "contents: write" in workflow
    assert "cp firmware/include/config.example.h firmware/include/config.h" in workflow
    assert "firmware/include/firmware_identity.h" in workflow
    assert 'git merge-base --is-ancestor "${GITHUB_SHA}" origin/main' in workflow
    assert "PROVISIONING_REVISION" in workflow
    assert "build_ota_manifest.py" in workflow
    assert "gh release create" in workflow
    assert "firmware-manifest.json" in workflow
    assert "TreeWatering-m5stack-atom-" in workflow
    assert "#define PROVISIONING_REVISION 0" in config
    assert 'WIFI_PASSWORD "CHANGE_ME"' in config
    assert "secrets." not in workflow


def test_partition_table_keeps_nvs_and_two_equal_ota_slots() -> None:
    platformio = PLATFORMIO.read_text(encoding="utf-8")
    rows = {
        row[0].strip(): tuple(cell.strip() for cell in row[1:5])
        for row in csv.reader(PARTITIONS.read_text(encoding="utf-8").splitlines())
        if row and not row[0].lstrip().startswith("#")
    }

    assert "board_build.partitions = partitions.csv" in platformio
    assert rows["nvs"] == ("data", "nvs", "0x9000", "0x5000")
    assert rows["otadata"] == ("data", "ota", "0xe000", "0x2000")
    assert rows["app0"] == ("app", "ota_0", "0x10000", "0x140000")
    assert rows["app1"] == ("app", "ota_1", "0x150000", "0x140000")
