# iPhoneからのファームウェア更新

## 対象範囲

この機能は、iOSアプリから同じLAN内のATOM Liteへファームウェアを送るためのものです。

既存の0.5.x以前にはOTA受信機能がないため、最初の1回だけUSB接続で0.6.0以降を導入します。

USB導入後は、Wi-Fi設定と給水の安全設定をNVSに保持します。
公開releaseのgeneric firmwareには、実環境のWi-Fi情報や更新鍵を含めません。

初回導入とpairingが完了した後、通常のfirmware更新にMacやUSBデータ接続は不要です。
更新時に必要なのは安定した電源であり、検証済みのsolar/battery、USB充電器、power bankを使えます。

Mac接続を1回で終える場合、その接続は次をすべて完了するまで維持します。

1. `WATERING_ARMED=false`、`PROVISIONING_REVISION=1`でOTA対応版をUSB導入する。
2. 未アーム拒否と10回の電源試験で、意図しないpump出力がないことを確認する。
3. 吐出口を計量容器へ固定してから`WATERING_ARMED=true`、`PROVISIONING_REVISION=2`で候補版をUSB導入する。
4. 10秒×3回の流量、漏水、排水、siphonを実機確認する。失敗時は停止し、接続中にrevisionを上げて`WATERING_ARMED=false`へ戻す。
5. 合格時だけstatusの`armed=true`、`pump=false`、保存済みfirmware versionをread-backする。
6. ATOM buttonを3秒押し、iPhoneとOTA pairingして鍵をKeychainへ保存する。

手順5より前にMacから外すと、安全設定を確定するために再接続が必要です。
配管を木へ設置してから確認する場合は、最終確認が終わるまでMacとのUSBデータ接続を残します。

OTAは給水設定を変更する経路ではありません。
`armed`、最大給水時間、dose、cooldownを変える場合は、別のcommissioning作業として扱います。

## 信頼境界

ATOMの通常の給水APIは、信頼済みLAN内でだけ使う設計です。
OTAだけはファームウェアを書き換えられるため、物理pairingとHMAC認証を追加します。
[M5Stack公式pin map](https://docs.m5stack.com/en/core/ATOM%20Lite)では、ATOM Liteの内蔵buttonはG39です。
firmwareは`INPUT_PULLUP`のactive-lowとして扱いますが、3秒長押し検出は実機でまだ確認していません。

更新アクセスのpairingは、次の条件をすべて満たす場合だけ受け付けます。

- controllerが`IDLE`である。
- pump GPIOが`LOW`である。
- ATOM Lite本体のbuttonを3秒間押し、60秒のpairing windowを開いている。
- iPhoneとATOMが信頼済みのWPA2またはWPA3 LANにいる。

pairing時にATOMが256 bitの更新鍵を生成し、以前の鍵を失効させます。
iOSアプリは鍵を端末名ごとにKeychainへ保存し、`WhenUnlockedThisDeviceOnly`で保護します。
鍵を`UserDefaults`、ログ、repository、release assetへ書きません。

pairing response自体はLAN内HTTPを通るため、共有Wi-Fi、guest network、直接Internetへ公開したATOMではpairingしません。
この初期key transferにはTLSやPAKEがなく、同一L2 networkでpacket captureまたはARP spoofingできる第三者は更新鍵を取得できます。
その脅威を許容できないnetworkではpairing/OTAを使わず、USB recovery/provisioningを使います。
物理buttonは、この短いpairing windowを第三者が任意に開けないようにするための条件です。

## 更新手順

1. ポンプが停止し、吐出口と周辺に漏水リスクがないことを確認する。
2. ATOMを検証済みのsolar/battery、USB充電器、power bankなどの安定した電源へ接続する。Macへの接続は不要。
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

更新後はWi-Fi、watchdog、controller、pump GPIOを検査します。
15秒のhealth window後も不健康な場合は、pumpを`LOW`へ固定して旧partitionへ自動rollbackし、再起動します。

新旧両partitionが起動できない、またはrollback自体に失敗した場合だけ、ポンプと水源を安全な状態にしてUSB recoveryへ戻ります。

## Release作成

firmware releaseは`firmware-vx.y.z` tagで作成します。
tag versionと`firmware/include/firmware_identity.h`の`TREE_FIRMWARE_VERSION`が一致しない場合、workflowは停止します。

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
