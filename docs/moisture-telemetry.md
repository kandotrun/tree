# Moisture telemetry logger

`tree-moisture-logger`は、LAN内のATOM Liteから状態を定期取得し、NAS上のSQLiteへ保存するread-only serviceです。給水、停止、hold、schedule APIは呼びません。ADC値は校正データとして記録するだけで、自動給水条件には使用しません。

## 保存内容

既定では10秒ごとに次の情報を`moisture_samples`へ保存します。

- 観測時刻
- online/offline
- moisture ADC
- state、pump、armed
- uptime、Wi-Fi RSSI
- 最終request ID、runtime、stop reason
- firmware versionまたは通信error種別

DBは既定90日保持です。起動時と、その後24時間ごとに期限切れsampleを削除します。runtime DBと実ログはGitへcommitしません。

## NAS配置

公開gatewayと同じstdlib-only wheelを使えます。開発機またはCIでbuildした信頼済みwheelをNASへ転送し、次のlayoutへ展開します。

```text
~/apps/balcony-watering/
├── telemetry/
│   └── app/                 wheel展開先
└── shared/
    ├── telemetry.env        mode 600
    └── moisture.db          runtime、Git管理外
```

NAS上で実行します。

```bash
set -euo pipefail
base="$HOME/apps/balcony-watering"
wheel=/secure/path/balcony_watering_bridge-VERSION-py3-none-any.whl
install -d -m 700 "$base/telemetry/app" "$base/shared"
test -f "$wheel"
# 初回だけplaceholderを配置し、既存の本番設定は保持する。
test -f "$base/shared/telemetry.env" ||
  install -m 600 bridge/telemetry.example.env "$base/shared/telemetry.env"
python3 -m zipfile -e "$wheel" "$base/telemetry/app"
```

`telemetry.env`の`ATOM_URL`をprivate/local HTTP originへ変更します。interval、retention、timeoutは安全な範囲だけ受け付けます。

```bash
set -euo pipefail
install -d ~/.config/systemd/user
install -m 644 bridge/systemd/tree-moisture-logger.service \
  ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable tree-moisture-logger.service
systemctl --user restart tree-moisture-logger.service
```

長期運用にはuser lingeringが必要です。

```bash
loginctl show-user "$USER" -p Linger
```

## 検証

serviceが再起動を繰り返していないことと、sampleが増えていることを確認します。

```bash
systemctl --user show tree-moisture-logger.service \
  -p ActiveState -p SubState -p NRestarts -p ExecMainStatus
python3 - <<'PY'
import sqlite3
from pathlib import Path

path = Path.home() / "apps/balcony-watering/shared/moisture.db"
with sqlite3.connect(path) as connection:
    count, latest = connection.execute(
        "SELECT COUNT(*), MAX(observed_at_ms) FROM moisture_samples"
    ).fetchone()
print({"samples": count, "latest_observed_at_ms": latest})
PY
```

online sampleが増えずoffline recordだけが続く場合は、給水操作をせず、ATOMの電源、Wi-Fi、LAN到達性を確認します。

## 停止と削除

収集を止めてもポンプ制御には影響しません。

```bash
systemctl --user disable --now tree-moisture-logger.service
```

履歴を残す場合は`moisture.db`を削除しません。削除する場合はservice停止後にDB本体と`-wal`、`-shm`を一組として扱います。
