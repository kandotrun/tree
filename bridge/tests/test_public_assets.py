from __future__ import annotations

import re
import subprocess
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "balcony_watering" / "public"
SYSTEMD = Path(__file__).resolve().parents[1] / "systemd"
ROOT = ASSETS.parents[2]


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
    assert "setInterval" not in javascript
    assert "setTimeout" in javascript
    assert "AbortController" in javascript
    assert "statusRequestTimeoutMs" in javascript
    assert "pollRerunRequested" in javascript


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
  setTimeout() { return 1; },
  clearTimeout() {},
  AbortController: class {
    constructor() { this.signal = {}; }
    abort() {}
  },
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


def test_public_javascript_schedules_next_poll_only_after_completion() -> None:
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");
const source = fs.readFileSync(process.argv[1], "utf8");
const pending = [];
const scheduled = [];
const intervals = [];
let nextTimerId = 1;
let visibilityHandler = null;
class FakeAbortController {
  constructor() {
    this.signal = {
      aborted: false,
      listeners: [],
      addEventListener(type, callback) {
        if (type === "abort") this.listeners.push(callback);
      },
    };
  }
  abort() {
    if (this.signal.aborted) return;
    this.signal.aborted = true;
    for (const callback of this.signal.listeners.splice(0)) callback();
  }
}
const element = () => ({
  textContent: "",
  hidden: false,
  disabled: false,
  addEventListener() {},
});
const document = {
  body: { dataset: {} },
  hidden: false,
  querySelector: element,
  addEventListener(type, callback) {
    if (type === "visibilitychange") visibilityHandler = callback;
  },
};
const context = vm.createContext({
  document,
  AbortController: FakeAbortController,
  setInterval(callback, delay) { intervals.push({ callback, delay }); },
  setTimeout(callback, delay) {
    const id = nextTimerId++;
    scheduled.push({ id, callback, delay });
    return id;
  },
  clearTimeout(id) {
    const index = scheduled.findIndex((timer) => timer.id === id);
    if (index !== -1) scheduled.splice(index, 1);
  },
  fetch(_url, options = {}) {
    return new Promise((resolve, reject) => {
      pending.push({ resolve, reject });
      if (options.signal) {
        options.signal.addEventListener("abort", () => reject(new Error("aborted")));
      }
    });
  },
});
const response = {
  ok: true,
  status: 200,
  async json() {
    return {
      state: "IDLE",
      pump: false,
      armed: true,
      remaining_sec: 0,
      hourly_used: 0,
      hourly_limit: 6,
      daily_used: 0,
      daily_limit: 24,
      retry_after_sec: 0,
    };
  },
};

(async () => {
  const flush = async () => {
    await new Promise((resolve) => setImmediate(resolve));
    await new Promise((resolve) => setImmediate(resolve));
  };
  const fire = (timer) => {
    const index = scheduled.findIndex((candidate) => candidate.id === timer.id);
    if (index !== -1) scheduled.splice(index, 1);
    timer.callback();
  };

  vm.runInContext(source, context);
  if (pending.length !== 1) throw new Error("initial poll did not start");
  if (intervals.length !== 0) throw new Error("fixed interval can overlap slow polls");
  const deadline = scheduled.find((timer) => timer.delay === 10000);
  if (!deadline) throw new Error("status request has no deadline");
  if (scheduled.some((timer) => timer.delay === 3000)) {
    throw new Error("next poll scheduled before completion");
  }

  document.hidden = true;
  visibilityHandler();
  document.hidden = false;
  visibilityHandler();
  pending[0].resolve(response);
  await flush();
  if (pending.length !== 2) throw new Error("tab resume did not queue an immediate poll");
  if (document.body.dataset.state !== undefined) {
    throw new Error("pre-resume response rendered after the tab became visible");
  }
  if (scheduled.some((timer) => timer.delay === 3000)) {
    throw new Error("tab resume waited for the regular polling interval");
  }
  const resumedDeadline = scheduled.find((timer) => timer.delay === 10000);
  if (!resumedDeadline) throw new Error("resumed poll has no request deadline");

  fire(resumedDeadline);
  await flush();
  const recoveryPoll = scheduled.find((timer) => timer.delay === 3000);
  if (!recoveryPoll) throw new Error("timed-out poll did not schedule recovery");

  fire(recoveryPoll);
  await flush();
  if (pending.length !== 3) throw new Error("recovery poll did not start");
  if (!scheduled.some((timer) => timer.delay === 10000)) {
    throw new Error("recovery poll has no request deadline");
  }
  if (scheduled.some((timer) => timer.delay === 3000)) {
    throw new Error("recovery poll overlapped before completion");
  }

  pending[2].resolve(response);
  await flush();
  if (scheduled.some((timer) => timer.delay === 10000)) {
    throw new Error("completed request deadline was not cleared");
  }
  if (scheduled.filter((timer) => timer.delay === 3000).length !== 1) {
    throw new Error("next poll was not scheduled after completion");
  }
  if (document.body.dataset.state !== "ready") {
    throw new Error("recovery poll did not restore ready state");
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


def test_nas_deployment_runbooks_fail_closed_and_restart_services() -> None:
    public = (ROOT / "docs" / "public-gateway.md").read_text(encoding="utf-8")
    telemetry = (ROOT / "docs" / "moisture-telemetry.md").read_text(encoding="utf-8")

    assert "set -euo pipefail" in public
    assert "shopt -s nullglob" in public
    assert "set -- bridge/dist/*.whl" not in public
    assert "systemctl --user enable tree-public-gateway.service" in public
    assert "systemctl --user restart tree-public-gateway.service" in public
    assert "systemctl --user enable --now tree-public-gateway.service" not in public
    assert public.count("set -euo pipefail") >= 3
    assert "複数processやworkerを同時起動しません" in public
    public_env_check = 'test -f "$base/shared/public.env"'
    public_symlink_swap = 'ln -sfn "$release"'
    assert public_env_check in public
    assert public_symlink_swap in public
    assert public.index(public_env_check) < public.index(public_symlink_swap)

    assert "set -euo pipefail" in telemetry
    telemetry_env_check = 'test -f "$base/shared/telemetry.env"'
    telemetry_wheel_extract = 'python3 -m zipfile -e "$wheel"'
    assert telemetry_env_check in telemetry
    assert telemetry_wheel_extract in telemetry
    assert telemetry.index(telemetry_env_check) < telemetry.index(telemetry_wheel_extract)
    assert "systemctl --user enable tree-moisture-logger.service" in telemetry
    assert "systemctl --user restart tree-moisture-logger.service" in telemetry
    assert "systemctl --user enable --now tree-moisture-logger.service" not in telemetry
    assert telemetry.count("set -euo pipefail") >= 2


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
