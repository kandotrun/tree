from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "firmware" / "web" / "index.html"
GENERATOR = ROOT / "firmware" / "scripts" / "generate_dashboard_header.py"


def dashboard_source() -> str:
    return DASHBOARD.read_text(encoding="utf-8")


def test_dashboard_is_mobile_first_and_has_substantive_device_controls() -> None:
    source = dashboard_source()

    assert 'name="viewport"' in source
    assert 'id="moisture-adc"' in source
    assert 'id="moisture-chart"' in source
    assert 'id="device-state"' in source
    assert 'id="duration-sec"' in source
    assert 'min="1"' in source
    assert 'max="180"' in source
    assert 'id="water-button"' in source
    assert 'id="stop-button"' in source
    assert 'id="water-dialog"' in source
    assert '<div class="presets" role="group" aria-label="給水時間プリセット">' in source


def test_dashboard_has_no_auth_gate_or_credential_storage() -> None:
    source = dashboard_source()

    assert 'id="dashboard-main"' in source
    assert 'id="dashboard-main" inert' not in source
    assert "localStorage.setItem(CALIBRATION_KEY" in source
    assert "localStorage.getItem(CALIBRATION_KEY" in source
    for forbidden in (
        "API_TOKEN",
        "TOKEN_KEY",
        "api-token",
        "auth-gate",
        "auth-locked",
        "sessionStorage",
        "Authorization",
        "Bearer",
    ):
        assert forbidden not in source


def test_dashboard_uses_bounded_non_retrying_api_requests() -> None:
    source = dashboard_source()

    assert "async function apiRequest(path" in source
    assert "return parseResponse(await fetch(path, options));" in source
    assert source.count("await fetch(") == 1
    assert 'apiRequest("/v1/status"' in source
    assert 'apiRequest("/v1/water"' in source
    assert 'apiRequest("/v1/stop"' in source
    assert "payload: { request_id: requestId, duration_sec: duration }" in source
    assert "function createRequestId()" in source
    assert "crypto.getRandomValues" in source
    assert "crypto.randomUUID()" not in source
    assert "結果未確定" in source
    assert "自動再試行しません" in source
    assert "setInterval(refreshStatus" in source


def test_dashboard_treats_a_malformed_acceptance_as_ambiguous() -> None:
    source = dashboard_source()

    assert "payload.accepted !== true" in source
    assert "payload.request_id !== requestId" in source
    assert "payload.scheduled_ms !== duration * 1000" in source
    assert "error.ambiguous = true" in source


def test_dashboard_only_labels_dryness_after_two_point_calibration() -> None:
    source = dashboard_source()

    assert 'id="calibrate-dry"' in source
    assert 'id="calibrate-wet"' in source
    assert "calibration.dryAdc" in source
    assert "calibration.wetAdc" in source
    assert "未校正" in source
    assert "自動給水には使用しません" in source

    dry_start = source.find('$("calibrate-dry").addEventListener')
    wet_start = source.find('$("calibrate-wet").addEventListener')
    reset_start = source.find('$("reset-calibration").addEventListener')
    assert 0 <= dry_start < wet_start < reset_start
    dry_handler = source[dry_start:wet_start]
    wet_handler = source[wet_start:reset_start]
    assert "state.adc === calibration.wetAdc" in dry_handler
    assert "state.adc === calibration.dryAdc" in wet_handler
    assert "renderMoisture();" in dry_handler
    assert "renderMoisture();" in wet_handler


def test_dashboard_has_no_external_runtime_dependency() -> None:
    source = dashboard_source()

    assert "<script src=" not in source
    assert "<link rel=" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_moisture_display_uses_a_flat_bounded_progress_bar() -> None:
    source = dashboard_source()

    assert 'id="moisture-fill"' in source
    assert '$("moisture-fill").style.width = `${dryness}%`' in source
    assert "Math.max(0, Math.min(" in source
    assert "--gauge-angle" not in source


def test_safety_controls_have_explicit_cross_browser_visual_states() -> None:
    source = dashboard_source()

    assert "accent-color: var(--green)" in source
    assert "#duration-sec::-webkit-slider-thumb" in source
    assert "#duration-sec::-moz-range-thumb" in source
    assert ".stop-button:disabled { opacity: .58" in source
    assert ".hold-button:focus-visible" in source
    assert "outline-offset:" in source


def test_emergency_stop_stays_available_when_status_refresh_fails() -> None:
    source = dashboard_source()

    assert '$("water-button").disabled = true' in source
    assert '$("stop-button").disabled = false' in source
    assert "holdButton.disabled = !isHoldEngaged()" in source
    assert 'setConnection("error", "応答なし", false)' in source
    assert '$("armed-state").textContent = "状態不明"' in source
    assert '$("offline-banner").classList.remove("show")' in source


def test_status_refresh_rejects_non_object_json_before_state_update() -> None:
    source = dashboard_source()
    accept_start = source.find("function acceptStatus(payload)")
    error_handler_start = source.find("function handleStatusError(error)")
    assert 0 <= accept_start < error_handler_start
    accept_status = source[accept_start:error_handler_start]

    assert 'if (!payload || typeof payload !== "object")' in accept_status
    assert 'throw new Error("invalid_status_payload")' in accept_status
    assert accept_status.index("invalid_status_payload") < accept_status.index(
        "state.status = payload"
    )


def test_empty_status_history_clears_stale_event_content() -> None:
    source = dashboard_source()
    event_start = source.find("function renderLastEvent")
    reconcile_start = source.find("function reconcileHoldWithStatus")
    assert 0 <= event_start < reconcile_start
    render_last_event = source[event_start:reconcile_start]

    assert "if (!status.last_request_id)" in render_last_event
    assert '$("last-event-title").textContent = "給水履歴はありません"' in render_last_event
    assert '$("last-event-detail").textContent = "request id / runtime / stop reason"' in (
        render_last_event
    )


def test_emergency_stop_requires_an_explicit_stop_acknowledgement() -> None:
    source = dashboard_source()

    assert "payload.stopped !== true" in source
    assert "invalid_stop_acknowledgement" in source


def test_dashboard_has_a_bounded_deadman_hold_control() -> None:
    source = dashboard_source()

    assert 'id="hold-button"' in source
    assert 'aria-pressed="false"' in source
    assert "touch-action: none" in source
    assert "const HOLD_HEARTBEAT_MS = 500;" in source
    assert "const HOLD_LEASE_MS = 1500;" in source
    assert "const HOLD_MAX_RUN_MS = 600000;" in source
    assert 'apiRequest("/v1/hold/start"' in source
    assert 'apiRequest("/v1/hold/keepalive"' in source
    assert 'payload.watering_mode !== "HOLD"' in source
    assert "payload.lease_ms !== HOLD_LEASE_MS" in source
    assert "payload.max_run_ms !== HOLD_MAX_RUN_MS" in source
    assert "payload.renewed !== true" in source
    assert "payload.request_id !== hold.requestId" in source


def test_hold_release_paths_stop_and_never_overlap_heartbeats() -> None:
    source = dashboard_source()

    assert "hold.keepaliveInFlight" in source
    assert "setTimeout(sendHoldHeartbeat, HOLD_HEARTBEAT_MS)" in source
    assert 'holdButton.addEventListener("pointerup"' in source
    assert 'holdButton.addEventListener("pointercancel"' in source
    assert 'holdButton.addEventListener("lostpointercapture"' in source
    assert 'holdButton.addEventListener("blur"' in source
    assert 'window.addEventListener("blur"' in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert 'window.addEventListener("pagehide"' in source
    assert "if (!hold.pressed) {" in source
    assert "await releaseHold({ force: true });" in source
    assert "payload: {}," in source
    assert 'apiRequest("/v1/stop", {' in source
    assert "stopWatering({ silent = false, keepalive = false" in source
    assert 'window.addEventListener("pagehide", () => { void releaseHold(); })' in source
    assert "stopWatering({ silent, keepalive" in source
    assert "releaseHold({ keepalive: false, force: true, silent: false })" in source


def test_hold_control_preserves_the_one_shot_180_second_limit() -> None:
    source = dashboard_source()

    assert 'id="duration-sec" type="range" min="1" max="180"' in source
    assert "Math.min(180, payload.max_duration_sec)" in source
    assert "最大180秒" in source
    assert "最長10分" in source


def test_stale_status_response_cannot_cancel_an_active_hold() -> None:
    source = dashboard_source()

    assert "if (hold.active && status.pump !== true)" not in source
    assert "status.last_request_id === hold.requestId" in source
    assert "status.pump !== true" in source
    assert "void releaseHold({ force: true });" in source
    assert '$("stop-button").disabled = status.pump !== true && !holdEngaged' in source
    assert "const requestSequence = ++statusRequestSequence;" in source
    assert "if (requestSequence !== statusRequestSequence) return;" in source


def test_dashboard_uses_a_flat_task_first_visual_system() -> None:
    source = dashboard_source()

    assert 'id="status-strip"' in source
    assert 'id="control-panel"' in source
    assert 'id="sensor-panel"' in source
    assert source.index('id="control-panel"') < source.index('id="sensor-panel"')
    assert "linear-gradient(" not in source
    assert "radial-gradient(" not in source
    assert "conic-gradient(" not in source
    assert "backdrop-filter" not in source
    assert 'class="brand-mark"' not in source
    assert 'class="pill"' not in source


def test_dashboard_tucks_occasional_calibration_behind_details() -> None:
    source = dashboard_source()

    assert '<details class="calibration-panel" id="calibration-panel">' in source
    assert "<summary>センサー校正</summary>" in source
    assert 'id="calibrate-dry"' in source
    assert 'id="calibrate-wet"' in source
    assert 'id="reset-calibration"' in source


def test_dashboard_starts_status_polling_without_credentials() -> None:
    source = dashboard_source()

    assert "if (!state.token) return" not in source
    assert "if (!state.token || holdButton.disabled" not in source
    assert "setDuration(10);\n    refreshStatus();\n    setInterval(refreshStatus, 2000);" in source
    assert 'durationNumber.addEventListener("input"' in source
    assert "state.maxDurationSec !== boundedMaxDuration" in source


def test_dashboard_hides_a_non_informative_chart() -> None:
    source = dashboard_source()

    assert 'id="chart-wrap" hidden' in source
    assert "new Set(values).size < 2" in source
    assert '$("chart-wrap").hidden = true' in source
    assert '$("chart-wrap").hidden = false' in source


def test_embedded_dashboard_header_is_deterministic_and_current() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
