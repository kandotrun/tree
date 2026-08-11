# iPhoneからのファームウェア更新

## 対象範囲

この機能は、iOSアプリから同じLAN内のATOM Liteへファームウェアを送るためのものです。

既存の0.5.x以前にはOTA受信機能がないため、最初の1回だけUSB接続で0.6.0以降を導入します。

USB導入後は、Wi-Fi設定と給水の安全設定をNVSに保持します。
公開releaseのgeneric firmwareには、実環境のWi-Fi情報や更新鍵を含めません。

OTAは給水設定を変更する経路ではありません。
`armed`、最大給水時間、dose、cooldownを変える場合は、別のcommissioning作業として扱います。

## 信頼境界

ATOMの通常の給水APIは、信頼済みLAN内でだけ使う設計です。
OTAだけはファームウェアを書き換えられるため、物理pairingとHMAC認証を追加します。
[M5Stack公式pin map](https://docs.m5stack.com/en/core/ATOM%20Lite)では、ATOM Liteの内蔵buttonはG39です。

更新アクセスのpairingは、次の条件をすべて満たす場合だけ受け付けます。

- controllerが`IDLE`である。
- pump GPIOが`LOW`である。
- ATOM Lite本体のbuttonを3秒間押し、60秒のpairing windowを開いている。
- iPhoneとATOMが信頼済みのWPA2またはWPA3 LANにいる。

pairing時にATOMが256 bitの更新鍵を生成し、以前の鍵を失効させます。
iOSアプリは鍵を端末名ごとにKeychainへ保存し、`WhenUnlockedThisDeviceOnly`で保護します。
鍵を`UserDefaults`、ログ、repository、release assetへ書きません。

pairing response自体はLAN内HTTPを通るため、共有Wi-Fi、guest network、直接Internetへ公開したATOMではpairingしません。
物理buttonは、この短いpairing windowを第三者が任意に開けないようにするための条件です。

## 更新手順

1. ポンプが停止し、吐出口と周辺に漏水リスクがないことを確認する。
2. ATOMをUSBなどの安定した電源へ接続する。
3. 未pairingの場合は、ATOM本体buttonを3秒間押してから、アプリで「更新アクセスをペアリング」を実行する。
4. アプリで「更新を確認」を実行する。
5. 現在版と更新先、電源、pump停止状態を確認し、破壊的操作の確認画面から更新を開始する。
6. 再起動後に、firmware version、`state`、`pump=false`、boot guardを確認する。

アプリはGitHubのfirmware releaseをHTTPSで取得します。
manifestのdevice type、target、strict SemVer、binary size、SHA-256を検証し、現在版より新しい場合だけ候補にします。

upload直前にATOMから一度限りのnonceを取得します。
アプリは端末名、target、現在版、更新版、size、SHA-256、nonceをHMAC-SHA256で署名します。
ATOMは署名とnonceを検証してから、inactive OTA partitionへの書き込みを始めます。

ATOMは受信中にもpump GPIOを`LOW`へ固定します。
受信したbyte数とSHA-256がmanifestに一致し、ESP32 image検証が成功した場合だけboot partitionを切り替えます。

## 失敗時の扱い

給水中、pump出力中、未pairing、期限切れnonce、署名不一致、同一版またはdowngrade、size超過、hash不一致は更新前に拒否します。

転送が中断した場合は新しいpartitionを採用せず、現在のfirmwareを維持します。

boot partition切り替え後にHTTP responseが失われた場合、アプリは結果を`UNKNOWN`として扱います。
この場合もbinaryを自動再送せず、再接続後のfirmware versionを読み取って結果を確定します。

更新後はboot guardが再び有効になります。
boot guard中に給水確認を進めません。

ATOMが再接続しない場合は、電源を切ってポンプと水源を安全な状態にし、USB recoveryへ戻ります。

## Release作成

firmware releaseは`firmware-vx.y.z` tagで作成します。
tag versionと`config.example.h`の`FIRMWARE_VERSION`が一致しない場合、workflowは停止します。

workflowは`config.example.h`を`config.h`へコピーし、次の安全値を検証してからbuildします。

```c
#define WIFI_SSID "CHANGE_ME"
#define WIFI_PASSWORD "CHANGE_ME"
#define WATERING_ARMED false
#define PROVISIONING_REVISION 0
```

release assetはgeneric firmware binaryと`firmware-manifest.json`だけです。
実環境の`config.h`からreleaseを作りません。

## 実機検証

OTA対応版をUSBで初回導入しただけでは、OTA更新そのものを検証したことにはなりません。
実機検証には、初回導入版より新しいpatch releaseを用意します。

吐出口を計量容器へ向けたまま、次を順に確認します。

- pairing window外のpairing拒否。
- 誤ったHMACと再利用nonceの拒否。
- 給水中の更新拒否。
- 転送中断後も旧版で起動し、pumpが`LOW`であること。
- 正常更新後のversion、pump停止、boot guard、Bonjour再接続。
- 10回の電源試験後も意図しないpump出力がないこと。

これらを完了するまで、OTA機能を物理検証済みとは記録しません。
