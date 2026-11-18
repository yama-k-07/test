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
- 以前の `http://192.168.4.1`（同じ Wi-Fi で見る公式サンプル）とは別のプログラム。このファームウェアでは ESP32 は自分の Wi-Fi を立てず、インターネットにつながる Wi-Fi に**つなぎに行く**

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
   - `[CAM] ready (PSRAM yes)` … カメラ OK
   - `[LOCAL] SSID=... http://192.168.4.1` … 近くで見る画面 OK（`ENABLE_LOCAL_VIEW 1` のとき）
   - `[POLL] 200 {...}` … サーバーとつながった

### CameraWebServer からの変更点
- 画像の形式を **RGB565（顔検出用、240×240）から JPEG（VGA 640×480）** に変えた。クラウドへ送るには JPEG が必要で、近くで見る画面も軽くなる
- 上下の向きの補正（ESP32-S3-EYE は `set_vflip`）は CameraWebServer と同じ
- 近くで見る画面と、クラウドへの送信は同じカメラを使う。両方を同時に見ると、それぞれのコマ数は少し落ちる

## 見る

ダッシュボードの「カメラ」欄にカメラが出る（10 秒以内）→「映像を見る」を押す → 最大 10 秒ほどで映る。
名前・入口からの距離・受け取る/受け取らないは、同じ欄の「カメラの設定」で変えられる。

## 回線と費用の目安

- 見ている間: VGA・画質 14 で 1 枚 20〜50KB × 1 秒ごと ≒ 1 時間に 70〜180MB（カメラの上り・Supabase Storage・閲覧者の下りそれぞれ）
- 見ていない間: 10 秒ごとの小さな問い合わせだけ
- 重いときは `config.h` の `FRAME_SIZE` を `FRAMESIZE_QVGA` に、`JPEG_QUALITY` を大きくする

## 注意

- `SERVER_ROOT_CA` を入れない間は TLS 証明書を検証しない（`setInsecure()`、試験用）
- 映像は最新の1枚だけを保存し、録画はしない
- 閲覧はダッシュボードにログインした人だけ（`/api/camera_frame/<id>` はログイン必須）
