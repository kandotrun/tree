from __future__ import annotations

import re
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "balcony_watering" / "public"
SYSTEMD = Path(__file__).resolve().parents[1] / "systemd"


def test_example_database_paths_match_shared_runtime_layout() -> None:
    bridge = ASSETS.parents[1]
    public_env = (bridge / "public.example.env").read_text(encoding="utf-8")
    telemetry_env = (bridge / "telemetry.example.env").read_text(encoding="utf-8")

    assert "PUBLIC_DATABASE_PATH=~/apps/balcony-watering/shared/public.db" in public_env
    assert "MOISTURE_DATABASE_PATH=~/apps/balcony-watering/shared/moisture.db" in telemetry_env


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


def test_public_javascript_ignores_stale_status_responses() -> None:
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const pending = [];
const elements = new Map();
const element = (id) => {
  if (!elements.has(id)) {
    elements.set(id, {
      textContent: "",
      hidden: false,
      disabled: false,
      addEventListener() {},
    });
  }
  return elements.get(id);
};
const document = {
  body: { dataset: {} },
  hidden: false,
  getElementById: element,
  querySelector(selector) { return element(selector.slice(1)); },
  addEventListener() {},
};
const context = vm.createContext({
  document,
  window: { addEventListener() {} },
  setInterval() {},
  fetch() {
    return new Promise((resolve) => pending.push(resolve));
  },
});
const response = (body) => ({
  ok: true,
  status: 200,
  headers: { get() { return null; } },
  async json() { return body; },
});
const status = (state) => ({
  online: true,
  state,
  pump: state === "WATERING",
  armed: true,
  remaining_sec: state === "WATERING" ? 7 : 0,
  public_duration_sec: 10,
  hourly_used: 1,
  hourly_limit: 6,
  daily_used: 1,
  daily_limit: 24,
  retry_after_sec: 0,
});

(async () => {
  vm.runInContext(source, context);
  if (pending.length !== 1) throw new Error("initial refresh did not start");
  const newerRefresh = vm.runInContext("refresh()", context);
  if (pending.length !== 2) throw new Error("newer refresh did not start");
  pending[1](response(status("WATERING")));
  await newerRefresh;
  pending[0](response(status("IDLE")));
  await new Promise((resolve) => setImmediate(resolve));

  if (document.body.dataset.state !== "watering") {
    throw new Error(`stale response changed state to ${document.body.dataset.state}`);
  }
  if (element("status-title").textContent !== "水やり中") {
    throw new Error("stale response replaced the watering title");
  }
  if (element("stop-button").hidden) {
    throw new Error("stale response hid the stop button");
  }
  console.log("PASS");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", script, str(ASSETS / "app.js")],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "PASS"


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
    assert "white-space: nowrap" not in css
    assert "text-wrap: balance" in css
    assert re.search(r"min-height:\s*100dvh", css)
