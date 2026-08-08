"use strict";

const state = {
  waterPending: false,
  stopPending: false,
  stopRecommended: false,
};
let refreshGeneration = 0;

const elements = {
  body: document.body,
  connection: document.querySelector("#connection-label"),
  title: document.querySelector("#status-title"),
  detail: document.querySelector("#status-detail"),
  water: document.querySelector("#water-button"),
  stop: document.querySelector("#stop-button"),
  message: document.querySelector("#action-message"),
  quota: document.querySelector("#quota-label"),
};

async function readJson(response) {
  const payload = await response.json();
  if (!response.ok) {
    const error = new Error(payload.error || "request_failed");
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

async function fetchStatus() {
  return readJson(await fetch("/api/status", {
    headers: { Accept: "application/json" },
    cache: "no-store",
  }));
}

function formatWait(seconds) {
  if (seconds < 60) {
    return `${seconds}秒後にもう一度押せます`;
  }
  const minutes = Math.ceil(seconds / 60);
  return `${minutes}分後にもう一度押せます`;
}

function renderStatus(data) {
  const watering = data.state === "WATERING" || data.pump === true;
  const ready = data.state === "IDLE"
    && data.pump === false
    && data.armed === true
    && data.retry_after_sec === 0;

  if (watering) {
    state.stopRecommended = true;
  } else if (data.state === "IDLE" && !state.waterPending && !state.stopPending) {
    state.stopRecommended = false;
  }

  elements.body.dataset.state = watering ? "watering" : ready ? "ready" : "waiting";
  elements.connection.textContent = "オンライン";
  elements.water.disabled = state.waterPending || state.stopPending || !ready;
  elements.stop.hidden = !(watering || state.stopRecommended);
  elements.stop.disabled = state.stopPending;

  if (watering) {
    elements.title.textContent = "水やり中";
    elements.detail.textContent = data.remaining_sec > 0
      ? `あと約${data.remaining_sec}秒で止まります`
      : "安全タイマーで自動停止します";
  } else if (data.retry_after_sec > 0) {
    elements.title.textContent = "ただいま休憩中";
    elements.detail.textContent = formatWait(data.retry_after_sec);
  } else if (data.state === "BOOT_GUARD") {
    elements.title.textContent = "起動を確認中";
    elements.detail.textContent = "ポンプを止めたまま安全確認しています";
  } else if (ready) {
    elements.title.textContent = "水やりできます";
    elements.detail.textContent = "ボタンを押すと10秒で自動停止します";
  } else {
    elements.title.textContent = "いまは水やりできません";
    elements.detail.textContent = "木の状態を確認しています";
  }

  elements.quota.textContent = `この1時間は${data.hourly_used}/${data.hourly_limit}回、24時間では${data.daily_used}/${data.daily_limit}回使われました。`;
}

function renderOffline() {
  elements.body.dataset.state = "offline";
  elements.connection.textContent = "オフライン";
  elements.title.textContent = "木と通信できません";
  elements.detail.textContent = "電源かWi-Fiが戻るまで待ってください";
  elements.water.disabled = true;
  elements.stop.hidden = !state.stopRecommended;
  elements.stop.disabled = state.stopPending;
}

async function refresh() {
  const generation = ++refreshGeneration;
  try {
    const status = await fetchStatus();
    if (generation === refreshGeneration) renderStatus(status);
  } catch {
    if (generation === refreshGeneration) renderOffline();
  }
}

async function sendAction(path) {
  const response = await fetch(path, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({}),
  });
  return readJson(response);
}

elements.water.addEventListener("click", async () => {
  if (state.waterPending || state.stopPending) return;
  state.waterPending = true;
  state.stopRecommended = true;
  elements.water.disabled = true;
  elements.stop.hidden = false;
  elements.stop.disabled = false;
  elements.message.textContent = "水やりを始めています";
  try {
    const result = await sendAction("/api/water");
    elements.message.textContent = result.state === "UNKNOWN"
      ? "開始結果を確認中です。水を止める操作はいつでも使えます。"
      : "水やりを始めました";
  } catch (error) {
    const definitive = [400, 403, 404, 409, 413, 415, 429].includes(error.status);
    if (definitive) state.stopRecommended = false;
    elements.message.textContent = error.status === 429
      ? formatWait(error.payload.retry_after_sec || 60)
      : definitive
        ? "水やりを始められませんでした"
        : "開始結果を確認できません。水を止める操作を使えます。";
  } finally {
    state.waterPending = false;
    await refresh();
  }
});

elements.stop.addEventListener("click", async () => {
  if (state.stopPending) return;
  state.stopPending = true;
  elements.stop.disabled = true;
  elements.message.textContent = "停止しています";
  try {
    await sendAction("/api/stop");
    state.stopRecommended = false;
    elements.message.textContent = "水を止めました";
  } catch {
    state.stopRecommended = true;
    elements.message.textContent = "停止結果を確認できません。もう一度押せます。";
  } finally {
    state.stopPending = false;
    elements.stop.disabled = false;
    await refresh();
  }
});

void refresh();
setInterval(() => {
  if (!document.hidden) void refresh();
}, 3000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) void refresh();
});
