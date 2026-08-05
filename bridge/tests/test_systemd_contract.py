from pathlib import Path


def test_daily_timer_does_not_catch_up_missed_watering_runs() -> None:
    timer_path = Path(__file__).parents[1] / "systemd" / "balcony-watering-daily.timer"
    timer = timer_path.read_text(encoding="utf-8")

    assert "OnCalendar=*-*-* 07:30:00" in timer
    assert "Persistent=true" not in timer


def test_development_guide_does_not_reenable_timer_catch_up() -> None:
    guide_path = Path(__file__).parents[2] / "docs" / "development-guide.md"
    guide = guide_path.read_text(encoding="utf-8")

    assert "Persistent=true" not in guide
    assert "再起動後に遅れて給水せず翌日の判定まで待つ" in guide
