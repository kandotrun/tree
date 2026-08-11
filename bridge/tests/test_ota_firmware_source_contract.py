from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "firmware" / "src" / "main.cpp"
CONFIG = ROOT / "firmware" / "include" / "config.example.h"
IDENTITY = ROOT / "firmware" / "include" / "firmware_identity.h"
PLATFORMIO = ROOT / "firmware" / "platformio.ini"


def _function(source: str, signature: str, next_signature: str) -> str:
    start = source.index(signature)
    end = source.index(next_signature, start)
    return source[start:end]


def test_identity_is_checked_in_and_example_is_generic_revision_zero() -> None:
    config = CONFIG.read_text(encoding="utf-8")
    identity = IDENTITY.read_text(encoding="utf-8")

    assert '#define TREE_FIRMWARE_VERSION "0.6.0"' in identity
    assert '#define TREE_FIRMWARE_TARGET "m5stack-atom"' in identity
    assert "FIRMWARE_VERSION" not in config
    assert "#define PROVISIONING_REVISION 0" in config
    assert "OTA_KEY" not in config
    assert "FIRMWARE_KEY" not in config


def test_runtime_configuration_is_persisted_with_revision_written_last() -> None:
    source = MAIN.read_text(encoding="utf-8")
    persistence = _function(
        source,
        "bool persist_compiled_runtime_config(",
        "ProvisioningLoadResult load_runtime_config()",
    )

    required_fields = (
        "kWifiSsidKey",
        "kWifiPasswordKey",
        "kWateringArmedKey",
        "kDoseMsKey",
        "kMaxRunMsKey",
        "kCooldownMsKey",
        "kBootGuardMsKey",
    )
    for field in required_fields:
        assert field in persistence
    revision_write = "preferences.putUInt(kProvisioningRevisionKey"
    assert revision_write in persistence
    assert all(
        persistence.index(field) < persistence.index(revision_write) for field in required_fields
    )
    assert "#ifndef PROVISIONING_REVISION" in source
    assert "#define PROVISIONING_REVISION 1U" in source


def test_wifi_controller_status_and_safety_timer_use_runtime_configuration() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert "WiFi.begin(runtime_config.wifi_ssid.c_str()," in source
    assert "runtime_config.wifi_password.c_str())" in source
    assert 'response["armed"] = runtime_config.watering_armed;' in source
    assert 'response["default_duration_sec"] = runtime_config.dose_ms / 1000U;' in source
    assert "runtime_config.max_run_ms" in source
    assert "runtime_config.boot_guard_ms" in source
    assert 'response["ota_supported"] = true;' in source


def test_firmware_routes_publish_contract_and_collect_exact_headers() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert 'server.on("/v1/firmware", HTTP_GET, handle_firmware_info);' in source
    assert 'server.on("/v1/firmware/pair", HTTP_POST, handle_firmware_pair);' in source
    assert 'server.on("/v1/firmware/challenge", HTTP_POST,' in source
    assert 'server.on("/v1/firmware/update", HTTP_POST,' in source
    for field in (
        'response["device_type"]',
        'response["api_version"]',
        'response["target"]',
        'response["current_version"]',
        'response["ota_supported"]',
        'response["paired"]',
        'response["pairing_window_open"]',
        'response["max_firmware_bytes"]',
    ):
        assert field in source
    for header in (
        "X-Tree-Firmware-Target",
        "X-Tree-Firmware-Version",
        "X-Tree-Firmware-Size",
        "X-Tree-Firmware-SHA256",
        "X-Tree-Firmware-Nonce",
        "X-Tree-Firmware-Signature",
    ):
        assert header in source
    assert "server.collectHeaders(kOtaHeaderNames" in source


def test_pairing_key_is_generated_only_after_safe_window_and_never_logged() -> None:
    source = MAIN.read_text(encoding="utf-8")
    pair = _function(
        source,
        "void handle_firmware_pair()",
        "void handle_firmware_challenge()",
    )

    assert "pairing_window_is_open" in pair
    assert "ota_safety_gate_is_open" in pair
    assert "esp_fill_random" in pair
    assert "preferences.putString(kOtaKeyKey" in pair
    assert 'response["ota_key"]' in pair
    assert "Serial" not in pair
    assert "esp_fill_random" not in CONFIG.read_text(encoding="utf-8")


def test_invalid_signature_is_checked_before_flash_and_gate_is_cut_before_begin() -> None:
    source = MAIN.read_text(encoding="utf-8")
    begin = _function(
        source,
        "bool begin_ota_upload(HTTPUpload& upload)",
        "void handle_firmware_upload()",
    )

    signature = "verify_ota_signature(metadata)"
    cutoff = "pump_safety_gate.cutoff();"
    physical_low = "digitalWrite(PUMP_PIN, LOW);"
    update_begin = "Update.begin(metadata.size, U_FLASH)"
    assert begin.index(signature) < begin.index(cutoff)
    assert begin.index(cutoff) < begin.index(physical_low) < begin.index(update_begin)
    assert "consume_ota_nonce();" in begin
    assert begin.index(signature) < begin.index("consume_ota_nonce();")


def test_stream_mismatch_aborts_before_update_end_and_reboot_is_delayed() -> None:
    source = MAIN.read_text(encoding="utf-8")
    upload = _function(
        source,
        "void handle_firmware_upload()",
        "void finalize_firmware_update()",
    )
    finalize = _function(
        source,
        "void finalize_firmware_update()",
        "void configure_http_server()",
    )

    assert "Update.write" in upload
    assert "mbedtls_sha256_update_ret" in upload
    assert "abort_ota_upload" in upload
    assert "Update.end(false)" not in upload
    assert "Update.end(false)" in finalize
    assert "write_pending_update_marker" in finalize
    assert finalize.index("write_pending_update_marker") < finalize.index("Update.end(false)")
    assert "clear_pending_update_marker" in finalize
    assert "send_json(202" in finalize
    assert "ESP.restart()" not in finalize
    assert "ota_restart_at" in source
    assert "ESP.restart();" in source


def test_pending_marker_keeps_boot_closed_and_rolls_back_unhealthy_first_boot() -> None:
    source = MAIN.read_text(encoding="utf-8")
    maintain = _function(
        source,
        "void maintain_ota_boot_validation(uint32_t now)",
        "void maintain_ota_restart(uint32_t now)",
    )

    assert "inspect_pending_update_marker" in source
    assert "ota_boot_validation_decision" in maintain
    assert "WiFi.status() == WL_CONNECTED" in maintain
    assert "watchdog_ready" in maintain
    assert "digitalRead(PUMP_PIN) == HIGH" in maintain
    assert "Update.canRollBack()" in maintain
    assert "Update.rollBack()" in maintain
    assert "clear_pending_update_marker" in maintain
    assert "kOtaHealthWindowMs" in source
    assert "ota_boot_validation_pending" in source
    assert "ota_boot_guard_ms" in source


def test_water_and_hold_are_blocked_during_active_or_pending_update_but_stop_remains() -> None:
    source = MAIN.read_text(encoding="utf-8")
    water = _function(source, "void handle_water()", "bool parse_hold_request_id(")
    hold_start = _function(source, "void handle_hold_start()", "void handle_hold_keepalive()")
    hold_keepalive = _function(source, "void handle_hold_keepalive()", "void handle_stop()")
    stop = _function(source, "void handle_stop()", "void handle_firmware_info()")

    assert "ota_actuation_blocked()" in water
    assert "ota_actuation_blocked()" in hold_start
    assert "ota_actuation_blocked()" in hold_keepalive
    assert "ota_actuation_blocked()" not in stop


def test_native_build_includes_pure_ota_and_runtime_policy_sources() -> None:
    platformio = PLATFORMIO.read_text(encoding="utf-8")

    assert "+<ota_policy.cpp>" in platformio
    assert "+<runtime_config.cpp>" in platformio
