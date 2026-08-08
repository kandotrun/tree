from __future__ import annotations

import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "balcony_watering" / "public"
SYSTEMD = Path(__file__).resolve().parents[1] / "systemd"


def test_public_systemd_unit_uses_stdlib_wheel_layout() -> None:
    unit = (SYSTEMD / "tree-public-gateway.service").read_text(encoding="utf-8")

    assert "WorkingDirectory=%h/apps/balcony-watering/current/app" in unit
    assert "ExecStart=/usr/bin/python3 -m balcony_watering.public_main" in unit
    assert ".venv" not in unit
    assert "PrivateTmp" not in unit


def test_public_page_is_a_single_action_accessible_utility() -> None:
    html = (ASSETS / "index.html").read_text(encoding="utf-8")

    assert 'lang="ja"' in html
    assert 'id="water-button"' in html
    assert 'id="stop-button"' in html
    assert 'aria-live="polite"' in html
    assert 'type="number"' not in html
    assert "duration_sec" not in html
    assert "10秒だけ水をあげる" in html
    assert "登録不要" in html
    assert '<link rel="stylesheet" href="/app.css">' in html
    assert '<script src="/app.js" defer></script>' in html
    assert "<style" not in html
    assert "<script>" not in html


def test_public_javascript_never_forwards_client_selected_duration() -> None:
    javascript = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert 'fetch("/api/status"' in javascript
    assert '"/api/water"' in javascript
    assert '"/api/stop"' in javascript
    assert 'method: "POST"' in javascript
    assert "JSON.stringify({})" in javascript
    assert "document.hidden" in javascript
    assert "duration_sec" not in javascript
    assert "setInterval" in javascript


def test_public_javascript_keeps_stop_available_for_ambiguous_start() -> None:
    javascript = (ASSETS / "app.js").read_text(encoding="utf-8")

    assert "waterPending" in javascript
    assert "stopPending" in javascript
    assert "stopRecommended" in javascript
    assert "state.stopRecommended = true" in javascript
    assert "state.pending" not in javascript


def test_public_assets_have_no_login_or_ai_style_copy() -> None:
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(ASSETS.glob("*")) if path.is_file()
    ).lower()

    forbidden = (
        "bearer",
        "api_token",
        "authorization",
        "login",
        "ログイン",
        "認証",
        "seamless",
        "revolutionize",
        "\u2014",
        "\u2013",
    )
    assert [term for term in forbidden if term in combined] == []


def test_public_css_supports_dark_mode_reduced_motion_and_visible_focus() -> None:
    css = (ASSETS / "app.css").read_text(encoding="utf-8")

    assert "prefers-color-scheme: dark" in css
    assert "prefers-reduced-motion: reduce" in css
    assert ":focus-visible" in css
    assert "white-space: nowrap" in css
    assert "text-wrap: balance" in css
    assert re.search(r"min-height:\s*100dvh", css)
