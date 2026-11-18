# まもっち ESP32 カメラ（外から見られるコマ送りカメラ）

ESP32 のカメラ映像を、**同じ Wi-Fi にいなくても**本番ダッシュボード（https://test-fawn-iota-73.vercel.app/）の「カメラ」欄で見られるようにするファームウェア。

## 仕組み

```
ESP32 カメラ ──(インターネットにつながる Wi-Fi)──> Vercel（api/app.py）──> Supabase Storage（最新の1枚だけ）
                                                        ↑
                    ダッシュボードで「映像を見る」を押した人のブラウザが 1 秒ごとに最新の1枚を取りに来る
```

- **誰かが見ている間だけ送る**: 画面が画像を取りに来ると、サーバーは「見ている」期限（20 秒）を延ばす。カメラは 10 秒ごとの問い合わせの返事で「送って」と言われたら、約 1 秒ごとに JPEG を送る。見る人がいなくなると自動で止まる
- 映像は **約 1 秒に 1 枚のコマ送り**（動画ではない）。見始めてから映るまで最大 10 秒ほど
- ESP32 はインターネットにつながる Wi-Fi に**つなぎに行く**。同時に自分の Wi-Fi（`LOCAL_AP_SSID`）も立て、これは「近くで `http://192.168.4.1` を見る画面」（`ENABLE_LOCAL_VIEW 1`）と「位置推定用の AP」（`ENABLE_AP_BEACON 1`）を兼ねる

## 位置推定用の AP を兼ねる（`ENABLE_AP_BEACON 1`、既定）

- `firmware/esp32s3_ap` と同じく、自分の Wi-Fi の BSSID を 30 秒ごとに `POST /api/ap_heartbeat` で知らせる。サーバー側の変更は無く、ダッシュボードの「**ESP32 AP**」表にカメラが出る（fw 欄は `cam-1.3.0` のように `cam-` 付き）
- 初回登録時の名前と距離は `CAMERA_LABEL` / `CAMERA_DISTANCE_M`（`AP_LABEL` / `AP_DISTANCE_M` で別にもできる）。**距離が空のままだと位置推定に使われない**ので、入口からの距離を入れる。カメラは生存通知に自分の AP の BSSID（`ap_mac`）を入れるので、「カメラの設定」と「ESP32 AP」表の**どちらで変えても同じ距離になる**（`supabase/cameras.sql` の `ap_mac` 列が必要）
- 送信出力は `AP_TX_POWER_DBM`（既定 8.5dBm、ESP32 AP と同じ）。ESP32 は1つの電波で両方をこなすため、**上り回線（テザリング）への電波も同じ出力になる**。映像が途切れるなら 11〜15 に上げる
- チャンネルは上り回線（テザリング）と同じになり、ESP32 AP のように 1/6/11 で分けられない（ESP32 の仕様）
- 自分の Wi-Fi の名前（`LOCAL_AP_SSID`）はカメラごとに変える

## 準備（1回だけ）

1. Supabase の SQL Editor で `supabase/cameras.sql` を実行する（`cameras` テーブルと画像置き場 `camera-frames` を作る）
2. Vercel の環境変数に `AP_SHARED_TOKEN`（長いランダム文字列）が入っていることを確かめる（ESP32 AP と共通）

## 書き込み

1. いま動いている **CameraWebServer** のフォルダ（`camerasample.ino` などがある所）から、次をこのフォルダにコピーする
   | ファイル | 用途 |
   |---|---|
   | `board_config.h` | カメラの機種（今は `CAMERA_MODEL_ESP32S3_EYE`）。そのまま使う |
   | `camera_pins.h` | ピン配置 |
   | `partitions.csv` | パーティション（アプリ領域 3.75MB） |
   | `app_httpd.cpp`, `camera_index.h` | `ENABLE_LOCAL_VIEW 1` のときだけ。近くで `http://192.168.4.1` を見るための画面 |
2. `config.example.h` を `config.h` にコピーして書き換える
   - `CAMERA_ID`: カメラごとに違う名前（英数字・`_`・`-`）
   - `WIFI_SSID` / `WIFI_PASSWORD`: **インターネットにつながる** 2.4GHz の Wi-Fi（現場の Wi-Fi、モバイルルーター、スマホのテザリング）
   - `AP_TOKEN`: Vercel の `AP_SHARED_TOKEN` と同じ値
   - `ENABLE_LOCAL_VIEW` / `LOCAL_AP_SSID` / `LOCAL_AP_PASSWORD`: 近くでも見るなら 1 と、自分の Wi-Fi の名前・パスワード（今の CameraWebServer で使っているものでよい）
3. Arduino IDE のボード設定（CameraWebServer の `ci.yml` の esp32s3 と同じ）
   - ボード: **ESP32S3 Dev Module**
   - PSRAM: **OPI PSRAM**（ESP32-S3-EYE は 8MB の OPI PSRAM）
   - Partition Scheme: **Custom**（コピーした `partitions.csv` が使われる）
   - Flash Mode: **QIO**、USB Mode: そのまま
4. 書き込んでシリアルモニタ（115200bps）を開く
   - `[CAM] sensor PID 0x..., format JPEG` または `format RGB565 -> JPEG` … どちらの撮り方になったか（下の「JPEG で撮れないカメラ」）
   - `[CAM] ready (PSRAM yes)` … カメラ OK
   - `[AP] SSID=...  BSSID=...` … 位置推定用の AP OK（`ENABLE_AP_BEACON 1` のとき）
   - `[LOCAL] SSID=... http://192.168.4.1` … 近くで見る画面 OK（`ENABLE_LOCAL_VIEW 1` のとき）
   - `[POLL] 200 {...}` … サーバーとつながった
   - `[HB] 200 {"message":"ok","registered":true}` … ESP32 AP 表に登録された（2回目以降は `false`）
   - ボードに USB-C が2つある場合、ログが出るのは ESP32-S3 本体の USB 側（`USB CDC On Boot: Enabled` のため）。UART 側（CH343 など）からも書き込みはできるが、ログは出ない

### CameraWebServer からの変更点
- まず **JPEG（VGA 640×480）** で撮ろうとする。クラウドへ送るには JPEG が必要
- **JPEG で撮れないカメラ**（`esp_camera_init` が `0x106` = ESP_ERR_NOT_SUPPORTED を返すセンサー）は、自動で **RGB565 で撮って本体で JPEG に変換**して送る（`frame2jpg`）。大きさは `RGB_FRAME_SIZE`（既定 QVGA 320×240）、画質は `RGB_JPEG_QUALITY`（既定 60）。実機の ESP32-S3-EYE（センサー PID 0x9b）はこちらで動いている。CameraWebServer のサンプルが RGB565・240×240 だったのはこのため
- 上下の向きの補正（ESP32-S3-EYE は `set_vflip`）は CameraWebServer と同じ
- 近くで見る画面と、クラウドへの送信は同じカメラを使う。両方を同時に見ると、それぞれのコマ数は少し落ちる

## 見る

ダッシュボードの「カメラ」欄にカメラが出る（10 秒以内）→「映像を見る」を押す → 最大 10 秒ほどで映る。
名前・入口からの距離・受け取る/受け取らないは、同じ欄の「カメラの設定」で変えられる。

## 回線と費用の目安

- 見ている間: VGA・画質 14 で 1 枚 20〜50KB × 1 秒ごと ≒ 1 時間に 70〜180MB（カメラの上り・Supabase Storage・閲覧者の下りそれぞれ）
- 見ていない間: 10 秒ごとの小さな問い合わせだけ
- 重いときは `config.h` の `FRAME_SIZE` を `FRAMESIZE_QVGA` に、`JPEG_QUALITY` を大きくする（JPEG で撮れないカメラでは `RGB_FRAME_SIZE` を小さく、`RGB_JPEG_QUALITY` を小さく）

## 注意

- `SERVER_ROOT_CA` を入れない間は TLS 証明書を検証しない（`setInsecure()`、試験用）
- 映像は最新の1枚だけを保存し、録画はしない
- 閲覧はダッシュボードにログインした人だけ（`/api/camera_frame/<id>` はログイン必須）
