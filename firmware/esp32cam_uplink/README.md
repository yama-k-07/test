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
- ESP32 はインターネットにつながる Wi-Fi に**つなぎに行く**。`ENABLE_LOCAL_VIEW 1` なら自分の Wi-Fi（`LOCAL_AP_SSID`）も立て、近くで `http://192.168.4.1` を見られる。位置の目印は BLE ビーコン（下）

## 位置推定用の BLE ビーコンを兼ねる（`ENABLE_AP_BEACON 1`、既定）

- 名前 `MAMOTCHI-<CAMERA_ID>` で BLE の広告を 100ms ごとに出す（`firmware/esp32s3_ap` 2.0.0 と同じ）。その **BLE アドレス**を 30 秒ごとに `POST /api/ap_heartbeat` で知らせるので、ダッシュボードの「**ESP32 AP**」表にカメラが出る（fw 欄は `ble-cam-1.5.0` など）
- ウォッチは `MAMOTCHI-` の BLE を RSSI 上位3つで `ble_reports` に送る（[`docs/WATCH_SCAN_REPORTS.md`](../../docs/WATCH_SCAN_REPORTS.md)）。現場の Wi-Fi AP とも併用できる
- 初回登録時の名前と距離は `CAMERA_LABEL` / `CAMERA_DISTANCE_M`（`AP_LABEL` / `AP_DISTANCE_M` で別にもできる）。**距離が空のままだと位置推定に使われない**ので、入口からの距離を入れる。カメラは生存通知に BLE アドレス（`ap_mac`）を入れるので、「カメラの設定」と「ESP32 AP」表の**どちらで変えても同じ距離になる**（`supabase/cameras.sql` の `ap_mac` 列が必要）
- 送信出力は `BLE_TX_POWER`（既定 `ESP_PWR_LVL_P3` = +3dBm、全ビーコンで揃える）。Wi-Fi の出力は下げないので、上り回線は弱くならない
- Wi-Fi と BLE を同時に使うため、Wi-Fi の省電力はオンになる（ESP32 の決まり）
- 1.3.0（Wi-Fi の BSSID を登録）から入れ替えると、ESP32 AP 表に BLE アドレスの**新しい行**ができる。新しい行に距離を入れ、古い行（fw `cam-1.3.0`）は削除する

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
2. 設定ファイルを作る（**複数台なら「カメラごとの設定ファイル」を使う**。下の節）。1台だけなら `config.example.h` を `config.h` にコピーして書き換えてもよい
   - `CAMERA_ID`: カメラごとに違う名前（英数字・`_`・`-` で 17 文字まで。BLE の名前 `MAMOTCHI-<ID>` が 26 文字に収まるように）
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
   - `[BLE] name=MAMOTCHI-...  address=...` … 位置推定用の BLE ビーコン OK（`ENABLE_AP_BEACON 1` のとき）
   - `[LOCAL] SSID=... http://192.168.4.1` … 近くで見る画面 OK（`ENABLE_LOCAL_VIEW 1` のとき）
   - `[POLL] 200 {...}` … サーバーとつながった
   - `[HB] 200 {"message":"ok","registered":true}` … ESP32 AP 表に登録された（2回目以降は `false`）
   - ボードに USB-C が2つある場合、ログが出るのは ESP32-S3 本体の USB 側（`USB CDC On Boot: Enabled` のため）。UART 側（CH343 など）からも書き込みはできるが、ログは出ない

## カメラごとの設定ファイル（複数台）

1台ごとに違うのは `CAMERA_ID`・`CAMERA_LABEL`・`CAMERA_DISTANCE_M`・`LOCAL_AP_SSID` だけなので、そこだけをカメラごとのファイルに分ける。どれも Git には入らない（ひな形の `*.example.h` だけ入る）。

| ファイル | 中身 |
|---|---|
| `configs/common.h` | 全カメラ共通（Wi-Fi・サーバー・トークン・画質・近くで見る Wi-Fi のパスワード）。`configs/common.example.h` をコピーして作る |
| `configs/<カメラID>.h` | 1台ごとの4項目と `#include "common.h"`。`configs/camera.example.h` をコピーし、**ファイル名を CAMERA_ID と同じ**にする（例 `cam-03.h`） |

書き込みはリポジトリのいちばん上で:

```bash
python scripts/flash_camera.py --list
python scripts/flash_camera.py cam-03 COM9
```

- `--list` で設定ファイルの一覧と、つながっている ESP32 のポートが出る。`--compile-only` で書き込まずにコンパイルだけ
- スクリプトはスケッチ一式を作業用フォルダにコピーして、そこでだけ `config.h` を「`#include "<カメラID>.h"`」にする。元のフォルダの `config.h` は使わない・書き換えない
- `CAMERA_ID` とファイル名が違う、`CAMERA_ID` や `LOCAL_AP_SSID` が他のカメラと同じ、のときは書き込む前に止まる
- ボード設定（下の 3.）はスクリプトに入っている。arduino-cli は PATH、環境変数 `ARDUINO_CLI`、Arduino IDE 2 の同梱版の順に探す
- Arduino IDE で書き込むときは `configs/` を使わず、そのカメラの値を `config.h` に直接書く（スクリプトの組み立て方は IDE では再現できないため）

### CameraWebServer からの変更点
- まず **JPEG（VGA 640×480）** で撮ろうとする。クラウドへ送るには JPEG が必要
- **JPEG で撮れないカメラ**（`esp_camera_init` が `0x106` = ESP_ERR_NOT_SUPPORTED を返すセンサー）は、自動で **RGB565 で撮って本体で JPEG に変換**して送る（`frame2jpg`）。大きさは `RGB_FRAME_SIZE`（既定 QVGA 320×240）、画質は `RGB_JPEG_QUALITY`（既定 60）。実機の ESP32-S3-EYE（センサー PID 0x9b）はこちらで動いている。CameraWebServer のサンプルが RGB565・240×240 だったのはこのため
- 上下の向きの補正（ESP32-S3-EYE は `set_vflip`）は CameraWebServer と同じ
- 近くで見る画面と、クラウドへの送信は同じカメラを使う。両方を同時に見ると、それぞれのコマ数は少し落ちる

## 見る

ダッシュボードの「カメラ」欄にカメラが出る（10 秒以内）→「映像を見る」を押す → 最大 10 秒ほどで映る。
名前・入口からの距離・受け取る/受け取らないは、同じ欄の「カメラの設定」で変えられる。

## 付いたり消えたりするとき（診断、fw 1.5.0〜）

「カメラの設定」の「診断」欄で、原因の見当をつける（`supabase/camera_diagnostics.sql` を実行しておく。実行しなくても動くが、診断は保存されない）。

| 診断に出るもの | 意味 | 見るところ |
|---|---|---|
| 再起動 n回（理由 `brownout`） | 電源の電圧が足りずに再起動した | USB の電源（給電の弱いポート・長いケーブル・モバイルバッテリーの省電力）。カメラ・Wi-Fi・BLE を同時に使うと電流が増える |
| 再起動 n回（理由 `panic` / `task_wdt` / `int_wdt`） | プログラムが止まって再起動した | シリアルモニタのログ（本体側の USB 口）を送ってください。`空きメモリ 最小` が小さい（数十KB）ならメモリ不足 |
| 途切れ n回・Wi-Fi つながり直し n回 | 再起動はしていないが、Wi-Fi が切れていた | 電波（-75dBm より弱いと途切れやすい）。カメラを Wi-Fi のアクセスポイントに近づける・向きを変える |
| 送信の失敗 n回 | Wi-Fi にはつながっているが、サーバーへの送信に失敗した | インターネット側の回線（テザリングの上限・電波） |

- 「再起動」と「途切れ」はサーバーが数える（起動してからの秒数が減った＝再起動、60 秒より長く連絡が無かった＝途切れ）。「途切れ」は古い firmware でも数えられる
- シリアルモニタには起動時に `[BOOT] reset reason: ...`、Wi-Fi が切れる・つながると `[WIFI] disconnected` / `[WIFI] connected (#回数)` が出る

## 回線と費用の目安

- 見ている間: VGA・画質 14 で 1 枚 20〜50KB × 1 秒ごと ≒ 1 時間に 70〜180MB（カメラの上り・Supabase Storage・閲覧者の下りそれぞれ）
- 見ていない間: 10 秒ごとの小さな問い合わせだけ
- 重いときは `config.h` の `FRAME_SIZE` を `FRAMESIZE_QVGA` に、`JPEG_QUALITY` を大きくする（JPEG で撮れないカメラでは `RGB_FRAME_SIZE` を小さく、`RGB_JPEG_QUALITY` を小さく）

## 注意

- `SERVER_ROOT_CA` を入れない間は TLS 証明書を検証しない（`setInsecure()`、試験用）
- 映像は最新の1枚だけを保存し、録画はしない
- 閲覧はダッシュボードにログインした人だけ（`/api/camera_frame/<id>` はログイン必須）
