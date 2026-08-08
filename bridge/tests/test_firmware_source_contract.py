from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "firmware" / "src" / "main.cpp"


def test_independent_pump_timer_uses_the_accepted_request_duration() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert "bool arm_pump_safety_timer(uint32_t cutoff_ms)" in source
    assert "static_cast<uint64_t>(cutoff_ms) * 1000ULL" in source
    assert "arm_pump_safety_timer(controller->scheduled_ms())" in source
    assert "if (!arm_pump_safety_timer())" not in source


def test_gpio_write_rechecks_the_safety_gate_after_a_timer_race() -> None:
    source = MAIN.read_text(encoding="utf-8")

    write_high_or_low = "digitalWrite(PUMP_PIN, should_run ? HIGH : LOW);"
    recheck = """if (should_run &&
      !pump_safety_gate.allows_output(controller_requests_output)) {
    digitalWrite(PUMP_PIN, LOW);
  }"""
    assert source.index(write_high_or_low) < source.index(recheck)


def test_hold_routes_use_a_short_independent_safety_lease() -> None:
    source = MAIN.read_text(encoding="utf-8")

    assert 'server.on("/v1/hold/start", HTTP_POST, handle_hold_start);' in source
    assert 'server.on("/v1/hold/keepalive", HTTP_POST, handle_hold_keepalive);' in source
    assert "arm_pump_safety_timer(watering::kHoldLeaseMs)" in source
    assert "renew_pump_safety_timer(watering::kHoldLeaseMs)" in source


def test_hold_keepalive_cannot_reopen_a_fired_safety_gate() -> None:
    source = MAIN.read_text(encoding="utf-8")
    start = source.index("bool renew_pump_safety_timer(uint32_t cutoff_ms)")
    end = source.index("bool pump_output_should_run()", start)
    renewal = source[start:end]

    assert "pump_safety_gate.arm()" not in renewal
    assert "pump_safety_gate.cutoff()" in renewal
    assert "esp_timer_stop(pump_safety_timer)" in renewal
    assert "esp_timer_start_once(pump_safety_timer" in renewal


def test_hold_start_persists_before_timer_and_physical_output() -> None:
    source = MAIN.read_text(encoding="utf-8")
    start = source.index("void handle_hold_start()")
    end = source.index("void handle_hold_keepalive()", start)
    handler = source[start:end]

    persistence = "preferences.putString(kLastRequestKey, request_id)"
    timer = "arm_pump_safety_timer(watering::kHoldLeaseMs)"
    output = "apply_pump_output();"
    assert handler.index(persistence) < handler.index(timer) < handler.rindex(output)


def test_hold_keepalive_has_no_persistence_or_start_path() -> None:
    source = MAIN.read_text(encoding="utf-8")
    start = source.index("void handle_hold_keepalive()")
    end = source.index("void handle_stop()", start)
    handler = source[start:end]

    assert "controller->renew_hold" in handler
    assert "preferences.putString" not in handler
    assert "controller->start_hold" not in handler
    assert "pump_safety_gate.arm()" not in handler
