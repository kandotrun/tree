from __future__ import annotations

import re
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


def test_dashboard_keeps_token_session_only_and_calibration_nonsecret() -> None:
    source = dashboard_source()

    assert 'type="password"' in source
    assert "sessionStorage.setItem(TOKEN_KEY" in source
    assert "sessionStorage.getItem(TOKEN_KEY" in source
    assert "localStorage.setItem(CALIBRATION_KEY" in source
    assert "localStorage.getItem(CALIBRATION_KEY" in source
    assert not re.search(r"API_TOKEN|CHANGE_ME_TO_AT_LEAST", source)


def test_auth_gate_locks_background_scrolling_until_authorized() -> None:
    source = dashboard_source()

    assert '<body class="auth-locked">' in source
    assert 'id="dashboard-main" inert' in source
    assert 'document.body.classList.remove("auth-locked")' in source
    assert 'document.body.classList.add("auth-locked")' in source
    assert '$("dashboard-main").inert = false' in source
    assert '$("dashboard-main").inert = true' in source
    assert 'placeholder="32文字以上のAPIトークン"' in source


def test_dashboard_uses_bounded_non_retrying_api_requests() -> None:
    source = dashboard_source()

    assert 'fetch("/v1/status"' in source
    assert 'fetch("/v1/water"' in source
    assert 'fetch("/v1/stop"' in source
    assert "duration_sec: duration" in source
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


def test_dashboard_has_no_external_runtime_dependency() -> None:
    source = dashboard_source()

    assert "<script src=" not in source
    assert "<link rel=" not in source
    assert "http://" not in source
    assert "https://" not in source


def test_moisture_gauge_uses_browser_compatible_precomputed_angle() -> None:
    source = dashboard_source()

    assert "--gauge-angle" in source
    assert "--gauge-progress" in source
    assert "calc(var(--dryness) *" not in source


def test_safety_controls_have_explicit_cross_browser_visual_states() -> None:
    source = dashboard_source()

    assert "--range-progress" in source
    assert "#duration-sec::-webkit-slider-thumb" in source
    assert "#duration-sec::-moz-range-thumb" in source
    assert ".stop-button:disabled { opacity: .62" in source


def test_emergency_stop_stays_available_when_status_refresh_fails() -> None:
    source = dashboard_source()

    assert '$("water-button").disabled = true' in source
    assert '$("stop-button").disabled = !state.token' in source
    assert "holdButton.disabled = !(hold.pressed || hold.startInFlight || hold.active)" in source


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
    assert 'fetch("/v1/hold/start"' in source
    assert 'fetch("/v1/hold/keepalive"' in source
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
    assert 'window.addEventListener("blur"' in source
    assert 'document.addEventListener("visibilitychange"' in source
    assert 'window.addEventListener("pagehide"' in source
    assert "if (!hold.pressed) await releaseHold" in source
    assert 'body: "{}", keepalive' in source
    assert 'releaseHold("pagehide", true)' in source


def test_hold_control_preserves_the_one_shot_180_second_limit() -> None:
    source = dashboard_source()

    assert 'id="duration-sec" type="range" min="1" max="180"' in source
    assert "Math.min(180, payload.max_duration_sec)" in source
    assert "最大180秒" in source
    assert "最長10分" in source


def test_stale_status_response_cannot_cancel_an_active_hold() -> None:
    source = dashboard_source()

    assert "if (hold.active && status.pump !== true)" not in source
    assert "status.last_request_id === hold.requestId &&" in source
    assert 'releaseHold("device-reported-stopped", true, true)' in source
    assert '$("stop-button").disabled = status.pump !== true && !holdEngaged' in source
    assert "const requestSequence = ++statusRequestSequence;" in source
    assert "if (requestSequence !== statusRequestSequence) return;" in source


def test_embedded_dashboard_header_is_deterministic_and_current() -> None:
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
