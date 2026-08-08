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
