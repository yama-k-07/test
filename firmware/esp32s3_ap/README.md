# まもっち ESP32-S3 ビーコン（旧 ESP32-S3 AP）

トンネル内に並べて「位置の目印」にするファームウェア。2.0.0 から **BLE ビーコン**になった（従来の Wi-Fi softAP は `ENABLE_WIFI_AP 1` で残せる）。
ウォッチはこのビーコンに**接続しない**。スキャンして電波の強い順に2つのアドレス（`mac01` / `mac02`）をサーバーへ送り、
サーバーがそのアドレスの設置距離から位置を推定する（仕組みは `SPEC.md` §6.3、ファームウェアの仕様は §8）。
現場の Wi-Fi AP（既設6台）と併用する。ウォッチ側の決まりは [`docs/WATCH_SCAN_REPORTS.md`](../../docs/WATCH_SCAN_REPORTS.md)。

## 何をするか

| 機能 | 内容 |
|---|---|
| BLE ビーコン | 名前 `MAMOTCHI-<AP_LABEL>` で 100ms ごとに広告。接続は受けない。アドレスは ESP32 固有（変わらない） |
| 送信出力 | `BLE_TX_POWER`（既定 `ESP_PWR_LVL_P3` = +3dBm）。全台で揃える |
| heartbeat | 上り回線（現場 Wi-Fi）があれば 30 秒ごとに `POST /api/ap_heartbeat`。**BLE アドレス**で `ap_nodes` に自動登録（fw 欄は `ble-2.0.0`） |
| 上り回線なし | ビーコンとしてだけ動く。起動時にシリアルへ出る `address=…` を管理画面の「AP位置設定」に手で登録する |
| Wi-Fi softAP（任意） | `ENABLE_WIFI_AP 1` のときだけ。SSID `MAMOTCHI-<AP_LABEL>`。位置の目印としては登録しない |

Wi-Fi（上り回線）と BLE を同時に使うときは、ESP32 の決まりで Wi-Fi の省電力を切れない（`WiFi.setSleep(true)`）。

## 準備（1回だけ）

1. Supabase の SQL Editor で `supabase/ap_nodes.sql` を実行する
2. Vercel の環境変数に `AP_SHARED_TOKEN`（長いランダム文字列）を追加して再デプロイする
3. Arduino IDE で「ボードマネージャ」から **esp32 by Espressif Systems** を入れる
4. ウォッチを `docs/WATCH_SCAN_REPORTS.md` の決まりに対応させる

## 1台ごとの書き込み

1. `config.example.h` を `config.h` にコピーする（`config.h` は Git に入らない）
2. `config.h` を書き換える
   - `AP_LABEL`: 表示名（英数字 17 文字まで）。距離が分かる名前がおすすめ（例 `A050` = 50m 地点）
   - `AP_DISTANCE_M`: 入口からの距離[m]。初回登録時の初期値（以後は管理画面で変える）
   - `BLE_TX_POWER`: 全台同じにする
   - `UPLINK_SSID` / `UPLINK_PASSWORD` / `AP_TOKEN`: heartbeat を使う場合だけ
3. ボードは **ESP32S3 Dev Module**（またはお使いの S3 ボードの定義）を選び、USB でつないで書き込む
   - BLE と Wi-Fi を両方入れるため、標準のパーティションだとフラッシュの 93% を使う（2026-11-18、Arduino-ESP32 3.3.13 で確認）。機能を足すなら Partition Scheme を **Huge APP (3MB No OTA/1MB SPIFFS)** にする
4. シリアルモニタ（115200bps）に出る `[BLE] name=… address=…` を控える

## 設置後の確認

1. ダッシュボードの「ESP32 AP」に行が出て「稼働中」になる（heartbeat ありの場合）
2. 「入口からの距離 [m]」を確認して「保存」→ トンネルマップの下端にビーコンが並ぶ
3. ウォッチを持って各ビーコンの前に立ち、マップの位置が合うか確かめる
4. 隣より 2 台以上先のビーコンがよく `mac01` に入るなら、`BLE_TX_POWER` を下げて書き込み直す

## 1.x（Wi-Fi AP）から入れ替えるとき

- 登録されるアドレスが Wi-Fi の BSSID から BLE のアドレスに変わるので、「ESP32 AP」表に**新しい行**ができる
- 新しい行に距離を入れ、古い行（fw が `1.0.0`）は「削除」する

## 間隔の目安（Wi-Fi AP でのシミュレーション、送信 5 秒・電波ノイズ 6dB）

| 間隔 | 0〜500m の台数 | 平均誤差 | 誤差の大きい側（90%点） |
|---|---|---|---|
| 100m | 6 | 19m | 39m |
| 50m | 11 | 11m | 23m |
| 25m | 21 | 8m | 15m |

BLE は Wi-Fi より届く距離が短いので、同じ間隔なら順位がはっきりしやすい。実測はまだ。

## 注意

- `SERVER_ROOT_CA` を入れない間は TLS 証明書を検証しない（`setInsecure()`）。試験用。本番は CA を入れる
- 電源が落ちたビーコンはマップで灰色＋×になる（heartbeat が 90 秒途絶）。位置推定からは自動では外さないので、撤去したら管理画面で「使わない」にする
