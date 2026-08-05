from pathlib import Path


def test_daily_timer_does_not_catch_up_missed_watering_runs() -> None:
    timer_path = Path(__file__).parents[1] / "systemd" / "balcony-watering-daily.timer"
    timer = timer_path.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 07:30:00" in timer
    assert "Persistent=true" not in timer
