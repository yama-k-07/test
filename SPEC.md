# まもっち（MAMOTCHI）仕様書


| | |
|---|---|
| 本番 | https://test-fawn-iota-73.vercel.app/ |
| リポジトリ | https://github.com/yama-k-07/test |
| 構成 | Python Flask（`api/app.py` 1ファイル）／ Supabase（Postgres・Auth・Realtime）／ 素の JS ＋ Bulma ＋ Canvas（`api/static/admin.js`）／ ESP32-S3 ファームウェア（Arduino-ESP32） |
| 関連文書 | [AGENTS.md](./AGENTS.md)（開発ガイド）、[docs/AI_WORKFLOW.md](./docs/AI_WORKFLOW.md)（生成 AI との開発手順）、[firmware/esp32s3_ap/README.md](./firmware/esp32s3_ap/README.md)（ESP32 の書き込み手順） |

**目次**: 1 概要 ／ 2 デプロイと運用 ／ 3 ファイル構成 ／ 4 データモデル ／ 5 HTTP API ／ 6 サーバーの処理 ／ 7 ダッシュボード ／ 8 ESP32-S3 AP ／ 9 ウォッチとの約束 ／ 10 精度 ／ 11 開発支援 ／ 12 使われていないコード ／ 13 既知の問題 ／ 14 変更履歴

---

## 1. 概要

### 1.1 目的
トンネル内の作業者の位置を、身に着けた **Galaxy Watch が拾う Wi-Fi AP の BSSID** から推定し、管理者がダッシュボードで次のことを行う。

| 機能 | 中身 | 節 |
|---|---|---|
| 位置の表示 | トンネルマップ（Canvas）と、エリアごとのカード | §6.3, §7.3 |
| エリアへの指示 | エリアごとに「待機／出口へ避難／風上へ避難／警戒」と火災フラグ | §7.5 |
| 個人への指示 | マップの作業者アイコンから「待て／奥へ／手前へ」 | §7.4 |
| 火災位置の通知 | マップ上で火災の位置を指定 → 各ウォッチに「奥 約320m」などを通知 | §6.7, §7.4 |
| 入退場管理 | AP 圏内に入った・出た時刻の記録と一覧 | §6.8, §7.6 |
| AP の管理 | 既設6台の位置設定と、ESP32-S3 で自作した AP の自動登録・死活監視 | §6.2, §7.7, §8 |
| カメラ映像 | ESP32 カメラのコマ送り映像を、同じ Wi-Fi にいなくてもダッシュボードで見る（見ている間だけ送信） | §5.4b, §8.5 |

### 1.2 全体の流れ

```
 [Galaxy Watch]  ※コードはこのリポジトリに無い
   │ ① Wi-Fi をスキャンし、電波の強い順に2つの BSSID を mac01 / mac02 として書き込む（通報時は report=true）
   ▼
 [Supabase] wifi_reports ──(DB 側で)──> latest_wifi_reports ──Realtime──┐
   │                                                                      │
   │ ② ダッシュボードが 5 秒ごと（＋Realtime 通知時）に /api/wifi_map 等を呼ぶ
   ▼                                                                      ▼
 [Flask api/app.py]  位置推定（§6.3）・入退場判定（§6.8）・火災の方向計算（§6.7）   [ブラウザ admin.js]
   │                                                                      │
   │ ③ 書き込み: device_instructions（個人指示）、area_status_v2（エリア指示・火災フラグ）、
   │            device_fire_alerts（火災の方向）、entry_current / entry_log（入退場）
   ▼
 [Galaxy Watch] 自分宛ての指示・火災通知を読んで表示（読み方はこのリポジトリ外）

 [ESP32-S3 AP] softAP を立てて位置の目印になる。上り回線があれば 30 秒ごとに
               /api/ap_heartbeat → ap_nodes（自動登録・死活）
```

- **ウォッチ側の実装はこのリポジトリに無い。** ウォッチが読み書きするテーブル・API の形は「約束」として扱い、変える前に確認する（§9）。
- 位置推定・入退場判定・火災通知の更新は、**誰かがダッシュボードを開いている間だけ**走る（API が呼ばれたときに計算するため。§13）。

---

## 2. デプロイと運用

### 2.1 Vercel
- プロジェクトのルートは `api/`。`api/vercel.json` が `@vercel/python` で `app.py` をビルドし、**全パス `/(.*)` を `app.py` に渡す**（静的ファイルも Flask が配信）。
- `main` に入ると本番に自動デプロイ。ブランチ／PR ごとにプレビューが作られる（プレビューは Vercel のログインが必要な保護付き）。
- `GET /test-deploy` が `DEPLOYED-V3-POST-OK` を返せば Flask が動いている。

### 2.2 環境変数

| 変数 | 用途 |
|---|---|
| `SUPABASE_URL` | Supabase の URL（サーバーとブラウザの両方で使用） |
| `SUPABASE_SERVICE_ROLE_KEY` | サーバー用の全権キー（**RLS を無視して読み書きできる**） |
| `SUPABASE_ANON_KEY` | ブラウザの Realtime 購読用。`index.html` に埋め込まれて配信される |
| `AP_SHARED_TOKEN` | ESP32 AP の heartbeat の共有トークン（firmware の `AP_TOKEN` と同じ値）。未設定なら heartbeat は 503 |






---

## 3. ファイル構成

| パス | 行数 | 状態 | 内容 |
|---|---|---|---|
| `api/app.py` | 約1280 | **本体** | 全 API・位置推定・入退場・火災通知・ESP32 AP 受付 |
| `api/templates/index.html` | 約230 | **使用中** | ダッシュボード（`/index`） |
| `api/templates/login.html` | 約200 | **使用中** | ログイン（`/`）。JS はインライン |
| `api/static/admin.js` | 約1730 | **使用中** | ダッシュボードの動き（API 呼び出し・表・トンネルマップ） |
| `api/static/style.css` | 約960 | **使用中** | ドット調テーマ（DotGothic16 + Bulma 上書き）。末尾に「見やすさ調整」ブロック |
| `api/static/banner.png` | | 使用中 | ロゴ |
| `api/vercel.json` | | 使用中 | Vercel の設定（§2.1） |
| `requirements.txt` | | 使用中 | `flask, supabase, requests, python-dotenv`（**バージョン未固定**） |
| `supabase/fire_location.sql` | | 使用中 | `fire_location` / `device_fire_alerts` の定義 |
| `supabase/ap_nodes.sql` | | 使用中 | `ap_nodes` の定義 |
| `firmware/esp32s3_ap/` | 約130（.ino） | 使用中 | ESP32-S3 AP のファームウェア・設定例・README（§8） |
| `firmware/esp32cam_uplink/` | 約280（.ino） | 使用中 | ESP32 カメラのファームウェア・設定例・README（§8.5） |
| `supabase/cameras.sql` | | 使用中 | `cameras` テーブルと Storage バケット `camera-frames` の定義 |
| `AGENTS.md` / `CLAUDE.md` | | 説明書 | 開発ガイド（AI・人間共通）。`CLAUDE.md` は AGENTS.md を読み込むだけ |
| `docs/AI_WORKFLOW.md` | | 説明書 | 共同開発者が生成 AI と開発する手順 |
| `scripts/make_ai_context.py` | | 道具 | チャット AI 用のまとめファイル `dist/ai_context.md` を作る |
| `scripts/build_spec_qa.py`, `scripts/spec_qa/template.html` | | 道具 | 仕様Q&A ページ `dist/spec_qa.html` を作る（§11） |
| `README.md` | | 説明書 | 入口（AGENTS.md・手順書・この仕様書へのリンク） |
| `.gitignore` | | | `.vercel`, `.env`, `.claude/settings.local.json`, `firmware/**/config.h`, `dist/` |
| `api/templates/wifi.html` | | 壊れている | `/chkwifi` 用。データ形式が合わず 500 になる（§13） |
| `api/templates/sql_test.html`, `*_deprecated.html` | | 未使用 | 旧画面 |
| `api/public/templates/index.html` | | 未使用 | 旧ダッシュボードの残骸 |
| `api/static/script.js`, `style_deprecated.css` | | 未使用 | 最初期のプロトタイプ |
| `api/ANALYSIS.md` | | 古い | 2026-08 時点の解析。**この仕様書が正** |
| `api/properioai/` | | 不要 | コミットされた Python の venv（1300 ファイル超） |

ブラウザが読む外部ライブラリ（CDN）: Bulma 0.9.4、`@supabase/supabase-js@2`（UMD）、Google Fonts DotGothic16。

---

## 4. データモデル（Supabase）

`supabase/*.sql` があるのは2026-10 以降に足したテーブルだけ。それ以前のテーブルの定義はリポジトリに無く、下の列はコードと本番の応答から読み取ったもの。★はウォッチとの約束（§9）。

| 定数（app.py） | テーブル | 主キー | 列 | 書く | 読む |
|---|---|---|---|---|---|
| `TABLE_WIFI_LOG` | ★`wifi_reports` | `id`（連番） | `device_id`, `mac01`（最強 AP の BSSID）, `mac02`（2番目）, `report`（通報 bool）, `created_at` | ウォッチ | Flask |
| `TABLE_WIFI_REPORTS` | ★`latest_wifi_reports` | `device_id`（推定） | 各デバイスの最新1行（推定） | ウォッチ or DB | ブラウザ（Realtime）、デバッグ API |
| `TABLE_AREA_STATUS` | ★`area_status_v2` | `area_id` | `area_id`, `bssid`, `instruction`, `fire`, `area_order` | Flask | Flask（ウォッチも読む可能性） |
| `TABLE_USER` | `user` | `device_id` | `device_id`, `username` | Flask | Flask |
| `TABLE_AP_POSITIONS` | `ap_positions` | `mac` | `mac`, `position`（0〜5） | Flask | Flask |
| `TABLE_AP_PRESETS` | `ap_position_presets` | `name` | `name`, `positions`（`[{mac, position}]`）, `updated_at` | Flask | Flask |
| `TABLE_DEVICE_INSTRUCTIONS` | ★`device_instructions` | `device_id` | `device_id`, `instruction`（`none/wait/inward/outward`）, `report`, `updated_at` | Flask | Flask、ウォッチ |
| `TABLE_ENTRY_CURRENT` | `entry_current` | `device_id` | `device_id`, `username`, `status`（`in/out`）, `entry_time`, `exit_time`, `updated_at` | Flask | Flask |
| `TABLE_ENTRY_LOG` | `entry_log` | 自動 | `device_id`, `username`, `event_type`（`enter/exit`）, `event_time` | Flask | Flask |
| `TABLE_FIRE_LOCATION` | `fire_location` | `id`（常に 1） | `active`, `distance_m`（入口からの m）, `updated_at` | Flask | Flask |
| `TABLE_DEVICE_FIRE_ALERTS` | ★`device_fire_alerts` | `device_id` | `fire_active`, `direction`, `distance_m`, `message`, `approx`, `updated_at` | Flask | ウォッチ |
| `TABLE_AP_NODES` | `ap_nodes` | `mac`（大文字） | `label`, `distance_m`, `enabled`, `fw`, `uptime_s`, `sta_count`, `tx_power_dbm`, `channel`, `uplink_rssi`, `last_seen`, `created_at` | ESP32 ＋ Flask | Flask |
| `TABLE_WIFI_SCAN` | `wifi_reports_v2` | `id` | `device_id`, `scanned_at`（スキャンした時刻）, `created_at`, `mac01`/`rssi01`〜`mac03`/`rssi03`（RSSI 上位3つ） | ウォッチ | Flask（位置推定） |
| `TABLE_BLE_SCAN` | `ble_reports` | `id` | 同上（`MAMOTCHI-` の BLE ビーコンだけ） | ウォッチ | Flask（位置推定） |
| `TABLE_POSITION_SETTINGS` | `position_settings` | `id`（=1） | `method`（`top2_basic` / `top2_series` / `rssi_basic` / `rssi_series`）, `updated_at` | Flask | Flask |
| `TABLE_POSITION_EVAL` | `position_eval` | `id` | `device_id`, `true_distance_m`, `method_selected`, `sources`, `top2_basic`, `top2_series`, `rssi_basic`, `rssi_series`, `note`, `created_at` | Flask | Flask |
| `TABLE_SEGMENT_INSTRUCTIONS` | `segment_instructions` | `segment_key`（例 `0-100`） | `start_m`, `end_m`, `instruction`（`none/wait/inward/outward`）, `updated_at` | Flask | Flask |
| `TABLE_DEVICE_SEGMENT_STATE` | `device_segment_state` | `device_id` | `segment_key`（最後にいた区間）, `segment_updated_at`（送った区間の指示の時刻）, `updated_at` | Flask | Flask |
| `TABLE_CAMERAS` | `cameras` | `camera_id` | `label`, `distance_m`, `enabled`, `ap_mac`（兼ねている AP の BSSID）, `fw`, `wifi_rssi`, `width`, `height`, `frame_bytes`, `last_seen`, `last_frame_at`, `watch_until`, `created_at` | ESP32 カメラ ＋ Flask | Flask |

- `area_status_v2` は「エリアと BSSID の対応」「エリアの指示・火災フラグ」「並び順」の3役を1テーブルで兼ね、3つの API（`/api/area`、`/api/area_status`、`/api/area_order`）がそれぞれ別の列を部分 upsert する。
- `device_fire_alerts` は Realtime の配信対象（`supabase/fire_location.sql` で `supabase_realtime` に追加）。ウォッチが anon key で読むなら同 SQL 末尾の RLS ポリシーを有効にする。

---

## 5. HTTP API（`api/app.py`）

🔒 = ログイン必須（`login_required`。未ログインは `/` へ 302）。「トークン」= `X-AP-Token` ヘッダーで認証。**無印は誰でも呼べる（書き込みを含む）。** ★はウォッチとの約束の可能性があるもの。

### 5.1 画面

| メソッド パス | 認証 | 動作 |
|---|---|---|
| `GET /` | | ログイン済みなら `/index` へ、そうでなければ `login.html` |
| `POST /` | | `{email, password, mode}`。`mode:"signup"` → `supabase.auth.sign_up`、それ以外 → `sign_in_with_password`。成功で `session.logged_in=True` と `{status:"success", redirect:"/index"}`、失敗は 401 と例外メッセージ |
| `GET /index` | 🔒 | ダッシュボード。`SUPABASE_URL` と `SUPABASE_ANON_KEY` を `window.SUPABASE_CONFIG` として埋め込む |
| `GET /logout` | | `session.logged_in` を消して `/` へ |
| `GET,POST /chkwifi` | 🔒 | 旧ユーザー登録画面（壊れている） |
| `GET /test-deploy` | | `DEPLOYED-V3-POST-OK` |

### 5.2 エリア・ユーザー（ログイン不要）

| メソッド パス | リクエスト | 動作 |
|---|---|---|
| ★`GET /api/area_status` | | `[{area_id, instruction, fire}]` |
| ★`POST /api/area_status` | `[{area_id, instruction?, fire?}]`（配列。各要素に `area_id` 必須） | upsert。値は検証しない |
| `GET /api/area` | | `[{bssid, area_id}]` |
| `POST /api/area` | `{area_id, bssid}`（両方必須） | upsert |
| `DELETE /api/area` | `{area_id}` | 行ごと削除（指示・火災・並び順も消える） |
| `GET /api/area_order` | | `area_order` 昇順の `area_id` の配列（並び順が無ければ全件） |
| `POST /api/area_order` | `["A", "B", ...]` | 各要素に `{area_id, area_order: 添字}` を upsert |
| `GET /api/user` | | `[{device_id, username}]` |
| `POST /api/user` | `{username, device_id}`（両方必須） | upsert |
| `DELETE /api/user` | `{device_id}` | 削除して残りの一覧を返す |
| ★`GET /api/entry_status` | | `[{area_id, username, device_id}]`。`area_id` は §6.3 と同じ推定 |

### 5.3 管理（ログイン必須）

| メソッド パス | リクエスト | 動作 |
|---|---|---|
| `GET/POST/DELETE /api/ap_positions` | POST `{mac, position}` / DELETE `{mac}` | 既設 AP の位置番号。GET は `position` 昇順 |
| `GET/POST/DELETE /api/ap_presets` | POST `{name, positions:[{mac, position}]}` / DELETE `{name}` | AP 位置設定のプリセット。GET は名前順 |
| `GET /api/device_instructions` | | 全行 |
| `POST /api/device_instructions` | `{device_id, instruction, report?}` | `instruction ∈ {none, wait, inward, outward}` を検証して upsert |
| `GET /api/wifi_map` | | マップ用の全データ（下）。**呼ぶたびに DB に書き込む**（§6.10） |
| `GET /api/entry_management` | | `{status: 今日(JST)の entry_current}`。**呼ぶたびに入退場判定を書き込む**（§6.8） |
| `GET /api/entry_log?limit=N` | | 今日(JST)の `entry_log` を新しい順に N 件（既定 50、最大 200） |
| `GET /api/fire_location` | | `{active, distance_m, updated_at}` |
| `POST /api/fire_location` | `{ratio}`（マップ横軸 0〜1）か `{distance_m}` | 火災位置を保存し、すぐに `device_fire_alerts` を更新 |
| `DELETE /api/fire_location` | | 火災位置を解除し、全デバイスを `fire_active=false` に |
| `GET /api/ap_nodes` | | `ap_nodes` 全行＋`online`（heartbeat が 90 秒以内）。距離順 |
| `POST /api/ap_nodes` | `{mac, label?, distance_m?, enabled?}` | ESP32 AP の設定変更 |
| `DELETE /api/ap_nodes` | `{mac}` | 削除（動いていれば次の heartbeat で再登録） |
| `GET /api/debug/wifi_map` | | 生のテーブルと読み込み結果（`load_ap_map` を含む） |

`GET /api/wifi_map` の応答:
```json
{
  "workers": [{"device_id", "username", "report", "ratio", "distance_m", "area_id", "approx", "online", "fire_message"}],
  "ap_count": 6, "ap_labels": ["1","3","4","5","6","11"],
  "ap_markers": [{"label": "AP3", "distance_m": 100, "ratio": 0.2, "status": "online|offline|manual"}],
  "ap_spacing_m": 100,
  "area_order": ["A", "B"], "area_layout": [{"area_id": "A", "start": 0, "end": 0.5}],
  "online_device_ids": ["..."],
  "fire": {"active": true, "distance_m": 320, "ratio": 0.64}
}
```
`workers` に入るのは位置が推定できたデバイスだけ（§6.3）。

### 5.4 ESP32 AP

| メソッド パス | 認証 | 動作 |
|---|---|---|
| `POST /api/ap_heartbeat` | トークン | 本文 `{mac, label, distance_m, fw, uptime_s, sta_count, tx_power_dbm, channel, uplink_rssi}` → `{message, registered}`。`mac` は `AA:BB:CC:DD:EE:FF` 形式。初回は行を作り `label` / `distance_m` / `enabled=true` を入れる。2回目以降は稼働情報と `last_seen` だけ更新（管理画面で直した値は上書きしない）。トークン未設定 503、不一致 401 |

### 5.4b ESP32 カメラ

| メソッド パス | 認証 | 動作 |
|---|---|---|
| `POST /api/camera_poll` | トークン | 本文 `{camera_id, label, distance_m, fw, rssi, ap_mac?}` → `{send, interval_ms, poll_sec}`。初回は `cameras` に行を作る（`label` / `distance_m` は初期値）。以後は `last_seen`・`ap_mac` 等だけ更新（`ap_mac` 列が無い DB では `ap_mac` を外して保存） |
| `POST /api/camera_frame?camera_id=…` | トークン | 本文は JPEG そのもの（600KB まで、`X-Frame-Width` / `X-Frame-Height` 任意）。誰かが見ている間だけ Storage `camera-frames/<id>/latest.jpg` に上書き保存。返事は poll と同じ |
| `GET /api/cameras` | 🔒 | 全カメラ＋`online`（60 秒以内に連絡）＋`watching`。`ap_mac` が `ap_nodes` にあるカメラは `distance_m` を **ap_nodes の距離で返し**、`distance_source: 'ap'`・`ap_label` を付ける |
| `POST /api/cameras` | 🔒 | `{camera_id, label?, distance_m?, enabled?}`。AP を兼ねるカメラの `distance_m` は `ap_nodes` にも書く（距離は1つに揃う） |
| `DELETE /api/cameras` | 🔒 | `{camera_id}` |
| `GET /api/segment_instructions` | 🔒 | AP の区間 `[{key, start_m, end_m, start, end, instruction, device_ids}]` |
| `POST /api/segment_instructions` | 🔒 | `{segment_key, instruction}`。区間に指示を出し、今その区間にいるウォッチ全員に `device_instructions` で送る。応答に `sent_device_ids` |
| `GET /api/position_settings` | 🔒 | `{method, methods: [{key, label}], path_loss_n, source_weight}` |
| `POST /api/position_settings` | 🔒 | `{method}`（①〜④ のどれか）。マップ・エリア・火災通知に使う方式を変える |
| `GET /api/position_eval` | 🔒 | 方式ごとの誤差のまとめ `summary: [{key, label, count, mean_abs_m, p90_abs_m}]` と直近 20 件 `recent` |
| `POST /api/position_eval` | 🔒 | `{device_id, true_distance_m, note?}`。その時点の ①〜④ の推定を正しい位置と一緒に保存 |
| `DELETE /api/position_eval` | 🔒 | 記録をすべて削除 |
| `GET /api/camera_frame/<camera_id>` | 🔒 | 最新の JPEG（`X-Frame-At` に撮影時刻）。画像がまだ無ければ 204（`X-Camera-Status: waking`）。**呼ぶたびに「見ている」期限 `watch_until` を延ばす**（残り半分を切ったときだけ書く） |

### 5.5 エラーの形
基本は `{"error": "..."}` と 400/500。ログインだけ `{"status":"error","message":...}`。古い API は例外の中身をそのまま返す。2026-10 以降の API は画面には固定文を返し、詳細はサーバーログに出す。

---

## 6. サーバーの処理（`api/app.py`）

### 6.1 最新レポート `load_wifi_reports()`
`wifi_reports` を `id` の降順で取得し、`device_id` ごとに最初の1行（＝最新）だけ残す。全履歴を読むので、PostgREST の既定上限（通常 1000 行）を超えると古いデバイスが消える（§13）。

### 6.2 AP の台帳 `load_ap_map()` → `ApMap`
位置推定に使う「BSSID → 入口からの距離」を、次の2つから作る。同じ BSSID が両方にあれば ESP32 AP を優先する。

| 出どころ | 距離の決め方 | 表示名 | 死活 |
|---|---|---|---|
| AP位置設定（`ap_positions`） | 位置番号 0〜5 → `AP_DISTANCES_M = [0, 100, 200, 300, 400, 500]` | `AP` + `AP_LABELS`（`1,3,4,5,6,11`。**AP の名前で距離ではない**） | 分からない（`manual`） |
| ESP32 AP（`ap_nodes`） | 行ごとの `distance_m`。`enabled=false` と距離未設定は使わない | `label`（無ければ MAC の末尾） | `last_seen` が `AP_NODE_ONLINE_SEC`（90秒）以内なら稼働中 |

- MAC は `norm_mac()`（前後の空白を除いて大文字）で揃えて比べる。Android の BSSID は小文字、ESP32 は大文字で報告するため。
- `ApMap` が持つもの:
  - トンネルの両端：最も手前の AP と最も奥の AP
  - `spacing`：隣り合う AP の間隔の**中央値**
  - 距離とマップ横軸の比率の相互変換：`to_ratio` / `from_ratio`
  - マップの AP マーカー：`markers()`。同じ距離の AP は1つにまとめる
- 外れ値の閾値は `OUTLIER_SPACINGS`（1.5）× 間隔、火災の「すぐ近く」は `FIRE_NEAR_SPACINGS`（0.5）× 間隔。AP を増やして間隔を詰めれば、閾値も自動で細かくなる。

### 6.3 位置推定 `estimate_positions()`
トンネルマップ・入退場のエリア・火災通知は**同じ関数**の結果を使う。

**方式は4つ**（2026-11-19〜）。全部を同時に計算し（`estimate_methods`）、画面・エリア・火災通知に使うのは「位置推定の方式」欄で選んだ1つ（`position_settings.method`、既定 `top2_basic` ＝ 今までと同じ）。作業者ポップアップの「推定の比較」で4つとも見られる。

| 方式 | 1回のスキャン → 距離 | 時間でならす |
|---|---|---|
| ① `top2_basic` | `scan_top2_m`: 上位2つの既知 AP を 0.8 : 0.2 | `smooth_distance_m`（下の手順、30 秒・8 回） |
| ② `top2_series` | `scan_top2_m` | `series_distance_m`: 1次元カルマンフィルタ（60 秒・60 回まで） |
| ③ `rssi_basic` | `scan_rssi_m`: RSSI の差で強い2つの AP の間に置く | `smooth_distance_m` |
| ④ `rssi_series` | `scan_rssi_m` | `series_distance_m` |
| ⑤ `wifi3_series` | `scan_wifi3_m`: **Wi-Fi だけ**、上位3つの RSSI に距離減衰の式を当てはめる | `series_distance_m` |
| ⑥ `fusion_series` | `scan_fusion_m`: **Wi-Fi と BLE の両方**。BLE は ③、Wi-Fi は ⑤ で1回分を出す | `series_distance_m`（両方を1本に。BLE の方がばらつきが小さい＝重い） |

- **使うスキャン**（`load_recent_scans`）: 新しい表 `wifi_reports_v2` / `ble_reports`（RSSI 上位3つ）に行がある装置はそれだけを使い、無い装置は旧 `wifi_reports`（RSSI なし。① = ③、② = ④ になる）。装置の一覧は旧 `wifi_reports` の最新行のまま（移行中はウォッチが両方に送る。`docs/WATCH_SCAN_REPORTS.md`）。
- **③ の計算**: 強い AP を a、次の AP を b とし、距離減衰 `RSSI = P0 − 10·n·log10(r)` から `RSSI_a − RSSI_b = 10·n·log10(r_b / r_a)`、`r_a + r_b = |d_a − d_b|` を解いて `d_a` から `r_a` だけ b 側に置く。`PATH_LOSS_N = 2.0`（仮置き、現地の記録で決める）。差を使うので機種ごとの出力の違いは打ち消し合う。例: 100m が -60dBm・200m が -70dBm → 約 124m。RSSI が無いスキャンは ① と同じ
- **⑤ の計算**（2026-11-20〜）: Wi-Fi のスキャンだけを使う（BLE のスキャンでは値を出さない）。**いちばん強い AP の前後1区間**の地点 x を 1m 刻みで動かし（トンネル全体を探すと、遠い AP の電波のぶれで離れた所を選ぶことがある）、AP i までの距離 `r_i = √((x − d_i)² + 3²)`（高さの差 `WIFI3_AP_HEIGHT_M = 3`）から予想 RSSI `A − 10·n·log10(r_i)` を作って、実際の RSSI との差の二乗和が最小の x を選ぶ。A（機種の出力）は x ごとに最小二乗で決めるので要らない。③ が「強い2つの AP の間に置く」のに対し、⑤ は3つの AP すべてに合う1点を探すので、2つの AP の外側にいる場合や、1つの AP の RSSI がずれた場合にも対応できる。RSSI が2つ未満なら ① と同じ。雑音のない RSSI では 30m・130m・260m を ±1m で当てることをテストで確認
- **Wi-Fi と BLE の両方を使う方式**: ①〜④ は、両方の表に行があれば両方のスキャンを1本の時系列に混ぜる（同じ計算で）。⑥ はスキャンの種類ごとに向いた計算（BLE は ③、Wi-Fi は ⑤）を使ってから混ぜる。⑤ は Wi-Fi だけ
- **② ④ ⑤ ⑥ の計算**: 位置のゆらぎ `SERIES_WALK_MPS = 3.0` m/s（人の速さより大きめにして遅れを減らす。1.5 だとシミュレーションで遅れが目立った）、測定のばらつき = `SOURCE_SIGMA_SPACINGS`（Wi-Fi 0.35・BLE 0.25）× AP 間隔。予測から 3σ を超え、かつ `SERIES_MAX_SPEED_MPS = 3` m/s でも届かない飛びは捨てる。3 回続けて外れたら本当に動いたとみなし、新しい値から始め直す
- **Wi-Fi と BLE の比重**: basic は `SOURCE_WEIGHT`（今はどちらも 1.0）を重みに掛け、series は上のばらつきで自然に重み付けされる。値は `position_eval` の記録で決める
- **古い位置を出さない**: 新しい表の装置は、最後に AP が分かったスキャンが最新のスキャンより `SCAN_STALE_SEC`（16 秒）以上古ければ位置を出さない。旧形式の装置は今まで通り（最新レポートで AP が分からなければ出さない）
- **現地での比較**: ポップアップで正しい位置を入れて「記録」→ `position_eval` に ①〜④ と一緒に保存。「位置推定の方式」欄に方式ごとの平均誤差・90% 点が出る

以下は ① の手順（旧形式のデータでは変更前とまったく同じ結果になることを、200 通りの乱数データで確認済み）。

| 定数 | 値 | 意味 |
|---|---|---|
| `MAC01_WEIGHT` | 0.8 | mac01（最強 AP）の重み。mac02 は 0.2 |
| `SMOOTHING_WINDOW_SEC` | 30 | 最新レポートから何秒前までを使うか |
| `SMOOTHING_HALF_LIFE_SEC` | 8 | 古いレポートの重みが半分になる秒数 |
| `SMOOTHING_MAX_SAMPLES` | 8 | 使う件数の上限 |
| `OUTLIER_SPACINGS` | 1.5 | 外れ値の閾値（AP 間隔の倍数。100m 間隔なら 150m） |

デバイスごとの手順:
1. **1回分の距離**（`report_distance_m`）＝ `0.8 × 距離(mac01) + 0.2 × 距離(mac02)`。片方しか台帳に無ければその AP の距離。例: AP4(200m) と AP5(300m) → 220m
2. **履歴を集める**: 直近 60 秒の `wifi_reports` を1回だけ取得し（`load_recent_wifi_reports`）、そのデバイスの最新から 30 秒以内・最大 8 件
3. **平滑化**（`smooth_distance_m`）: 重み `0.5^(経過秒/8)` で重み付き中央値を出し、そこから外れ値の閾値以上離れたもの（電波のブレ）を捨てて重み付き平均 → `distance_m`
4. **マップ横軸** `ratio` = `ApMap.to_ratio(distance_m)`（0 = 最も手前の AP、1 = 最も奥の AP）
5. **エリア**（§6.4）
6. 最新レポートの AP がどちらも台帳に無いときは古い位置を使わない。ただしエリアの BSSID と一致すれば、そのエリアの中央に `approx: true`（エリアだけ判明）で置く。それも無ければ `workers` に入れない

例（100m 間隔）:

| 時刻 | 1回分の距離 | 重み | |
|---|---|---|---|
| 今 | 220m | 1.00 | |
| 5秒前 | 200m | 0.65 | |
| 10秒前 | 500m | 0.42 | 中央値 220m から 150m 以上離れているので捨てる |
| 15秒前 | 180m | 0.27 | |

→ 推定位置 約 208m

**分解能の限界**: ウォッチが送るのは「強い AP の名前2つ」だけなので、1回分で出せる位置は AP の位置か、その間の 2割・8割の地点くらいに限られる。それより細かい位置は時間方向の平均で出ている。精度は §10。

### 6.4 エリアの決め方
`area_order`（`area_status_v2` の並び順）にあるエリアを、上の条件から順に試す。
1. **全エリアの BSSID の距離が台帳で分かる** → 推定距離に**最も近いエリア**。マップの区切りは、隣り合うエリアの中心の中点（`build_area_layout`）
2. **最新レポートの mac01 / mac02 がエリアの BSSID と一致** → そのエリア
3. **どちらでもない** → トンネル（両端の AP の間）を `area_order` の数で等分した区間

`area_layout`（各エリアの横軸の範囲）は `/api/wifi_map` で画面に渡し、マップのエリア区切りの描画に使う。

### 6.5 オンライン判定
- ウォッチ: 最新レポートの `created_at` が `ONLINE_THRESHOLD_SEC`（60秒）以内なら `online`。マップでは 60 秒以上来ていない人を薄く描く（最後に見えた位置）。
- ESP32 AP: `last_seen` が 90 秒以内なら稼働中。
- 時刻の解析は `parse_ts()` が行う。Python 3.10 の `fromisoformat` は小数秒の桁が6桁でないと失敗するので、6桁に揃えてから読む。

### 6.6 通報フラグの同期 `sync_device_reports_from_wifi()`
ウォッチは通報（`report`）を `wifi_reports` に書く。これを `device_instructions.report` に写す。書き込み先をウォッチ側で移すまでの橋渡しとして残している処理。値が変わったデバイスだけ upsert する。マップでは通報中の作業者を赤く光らせる。

### 6.7 火災の方向計算
- 火災位置は `fire_location`（id=1 の1行）に、入口からの距離として保存する。両端の AP の範囲に収め、1m 単位。
- 各デバイスについて `差 = 火災の距離 − 自分の距離` を計算する（`fire_relation`）。

| 条件 | `direction` | `message` の例 |
|---|---|---|
| \|差\| ≤ AP 間隔 × 0.5（100m 間隔なら 50m） | `near` | 火災: すぐ近く（約30m） |
| 差 > 0 | `inward`（奥側） | 火災: 奥 約320m |
| 差 < 0 | `outward`（入口側） | 火災: 手前 約150m |
| 位置が推定できない | `unknown` | 火災発生: 位置不明。管理者の指示に従ってください |

- 距離は `FIRE_DISTANCE_STEP_M`（10m）単位に丸める（推定誤差より細かい数字を見せないため）。
- 対象は、最新レポートのあるデバイスと `user` に登録されたデバイスすべて。
- `device_fire_alerts` には**値が変わった行だけ** upsert する（`sync_device_fire_alerts`）。
- 更新されるタイミングは、火災位置の保存・解除の直後と、`/api/wifi_map` が呼ばれるたび（＝ダッシュボードを開いている間は 5 秒ごと）。
- エリアカードの火災フラグ（`area_status_v2.fire`）とは**別の機能**で、連動しない。

### 6.8 入退場判定 `do_entry_status_update()`（`/api/entry_management` から）
- 入場中の条件：最新レポートの mac01 か mac02 が AP の台帳（§6.2）にあること。台帳が空なら全員「外」。
- 状態が「外 → 入場中」に変わったら、`entry_current` を `in`（`entry_time=今`）にして、`entry_log` に `enter` を追加する。
- 状態が「入場中 → 外」に変わったら、`entry_current` を `out`（`exit_time=今`）にして、`entry_log` に `exit` を追加する。
- 返すのは `updated_at` が今日（日本時間 0:00〜24:00）の `entry_current` だけ。
- 判定はこの API が呼ばれたときだけ走る。レポートの新しさは見ない（§13）。

### 6.9 認証
- Supabase Auth のメールとパスワードで認証する。ログインできたら、Flask の署名付き cookie セッションに `logged_in` / `user_email` を入れる。ロールや許可リストは無い。
- サインアップは誰でもでき、`sign_up` が user を返した時点でログイン扱いになる（メール確認を待たない）。
- ログイン不要の API があるのは、ウォッチが使っている可能性があるため（§9）。

### 6.10 `GET /api/wifi_map` 1回で起きること
画面を開いている間、5秒ごとに次が順に走る（Supabase への問い合わせは約 10 回）。
1. `wifi_reports` 全件 → デバイスごとの最新（§6.1）
2. `ap_positions` と `ap_nodes` → `ApMap`（§6.2）
3. `area_status_v2` の並び順と BSSID
4. 直近 60 秒の `wifi_reports` → 位置推定（§6.3・§6.4）
5. `user` → 名前
6. `device_instructions` → 通報の同期（変化があれば upsert）（§6.6）
7. `fire_location` → 火災位置
8. `user` と `device_fire_alerts` → 火災の方向（変化があれば upsert）（§6.7）

---

## 7. ダッシュボード（`index.html` + `admin.js` + `style.css`）

### 7.1 画面構成（上から）

| セクション | 主な DOM | 描画・操作の関数 | 使う API |
|---|---|---|---|
| 位置推定の方式（マップの真上） | `#positionMethodSelect`, `#positionEvalHead`, `#positionEvalBody` | `loadPositionSettings` / `savePositionMethod` / `loadPositionEval`（方式を横に並べた3行の表）/ `clearPositionEval`。作業者ポップアップの「推定の比較」は `positionMethodsHtml` / `recordPositionEval` | `/api/position_settings`, `/api/position_eval` |
| トンネルマップ（個別指示・区間の指示・火災も） | `canvas#tunnelMap`, `#workerPopup`, `#fireModeBtn`, `#fireClearBtn`, `#fireStatus`, 凡例 | `loadTunnelMap` / `renderTunnelMap` / `openWorkerPopup` / `openSegmentPopup` / `toggleFireMode` ほか | `/api/wifi_map`, `/api/device_instructions`, `/api/segment_instructions`, `/api/fire_location` |
| 入場管理 | `#entryCurrentBody`, `#entryLogBody` | `loadEntryManagement` / `renderEntryCurrentTable` / `renderEntryLogTable` | `/api/entry_management`, `/api/entry_log?limit=30` |
| ― 設定 ― | | | |
| AP位置設定 | `#apPositionsTableBody`, `#apPresetSelect`, `#apPresetNameInput` | `loadApPositionsTable` / `saveApPositionsTable` / `loadApPreset` / `saveApPreset` / `deleteApPreset` | `/api/ap_positions`, `/api/ap_presets` |
| エリア割当設定 | `#areaTableBody` | `loadAreaMapTable` / `saveAreaMapTable` / `removeAreaRow` | `/api/area` |
| ユーザー設定 | `#userTableBody` | `loadUserTable` / `saveUserTable` / `removeRow` | `/api/user` |
| ESP32 AP（設定の下） | `#apNodesTableBody` | `loadApNodesTable` / `saveApNode` / `deleteApNode` | `/api/ap_nodes` |
| カメラ（トンネルマップの下。表では順番を後ろに書いている） | `#cameraGrid`, `#cameraSettingsBody` | `loadCameras` / `startCameraView` / `stopCameraView` / `fetchCameraFrame` / `saveCamera` / `deleteCamera` | `/api/cameras`, `/api/camera_frame/<id>` |
| フッター | LOGOUT ボタン | | `/logout` |

### 7.2 更新の仕組み
- **読み込み時**（`DOMContentLoaded`）に全セクションを1回読む。トンネルマップのクリック操作と Realtime 購読もここで始める。
- 「エリアごとの状態」のカード（`loadAreaBoard` / `createAreaCard`、SortableJS の並べ替え）は 2026-11-20 に削除し、AP の区間ごとの指示（§7.4）に置き換えた。`/api/area_status` などのログイン不要 API はウォッチのために残している。
- **5 秒ごと**（`setInterval`）に `loadAreaMapTable`、`loadUserTable`、`loadEntryManagement`、`loadApNodesTable`、`loadCameras`、`loadPositionSettings`、`loadPositionEval`、`loadTunnelMap` を呼ぶ。AP位置設定とプリセット一覧は読み込み時だけ。
- **Realtime**：anon key で `latest_wifi_reports` の変更を購読し、変更が来たら `loadTunnelMap()`。Supabase 側で Realtime が有効でないと何も起きない（エラーにもならない）。
- **ちらつき防止**：表やカードは、前回の応答（`JSON.stringify`）を `last*Sig` に覚えておき、同じなら描き直さない。マップは毎回描き直す。
- **入力中は止める**：`input` / `select` にフォーカスがある間は `isEditing=true` になり、定期更新を丸ごと止める。
- **エラー時**：API エラーや想定外の形のときは描画しない（表が消えないように）。

### 7.3 トンネルマップの描画（`renderTunnelMap`）
- 大きさ：高さ 260px（`H`。CSS の `#tunnelMap` の高さと同じ値にすること）、幅は親要素いっぱい。余白は左右 44px・上下 36px。左端に「外」、右端に「奥」。
- 文字：エリア名などは 16px、AP 名と作業者名は 12px（DotGothic16）。
- **AP の区間**：隣り合う AP の境目に点線を引き、上辺に「0〜100m」と区間の指示（例「100〜200m 待て」）を出す。指示が出ている区間は薄い黄色、ポップアップを開いている区間は薄い青。位置はサーバーの `segments`（`ap_segments`）。描画のたびに区間の位置を `tunnelSegments` に保存する（クリック判定用）。
- **AP**：下辺の丸を実際の距離の位置に置く。
  - 稼働中・既設は青。停止中の ESP32 AP は灰色＋赤い ×。
  - ラベルは「AP3 100m」。重なる幅では「AP3」だけにし、それでも重なるなら数台おきに出す。
- **火災位置**：赤い帯＋ドット絵の炎＋「火災 約320m」。指定モード中はカーソル位置に半透明のプレビューを出す。
- **作業者**：半径 20px の円。
  - 横位置は `ratio`。近い人とは上下に最大3段までずらす。
  - 名前は円に収まる長さまで切り詰める。
  - 色と線：通常は緑、通報中は赤くパルス発光（`startReportGlowLoop` で通報者がいる間だけ描き直す）、オフラインは透明度 0.4、エリアだけ判明（`approx`）は点線の円。
  - 「なし」以外の個別指示が出ていれば、右上に青い指示バッジ。ポップアップを開いている人は青い外枠。
- 作業者が1人もいなければ「作業者データなし（AP位置設定を確認してください）」と出す。
- 描画のたびに円の位置を `tunnelMapHitboxes` に保存し（クリック判定用）、トンネルの寸法を `tunnelGeom` に保存する（火災位置の変換用）。ウィンドウの大きさが変わったら描き直す。

### 7.4 マップの操作
**個別指示**
- 作業者の円をクリックすると、横にポップアップが出る（`findWorkerAt` → `openWorkerPopup`）。
  - 中身：名前、オンラインかどうか、現在の指示、ウォッチに出ている火災の文、指示ボタン4つ（なし／待て／奥へ／手前へ。今の指示は青）。
  - ボタンを押すと `POST /api/device_instructions` で送り、成功したら閉じる。失敗したら `alert` を出してボタンを戻す。
- 閉じ方：×、外側のクリック、何もない所のクリック、Esc。5秒ごとの更新では閉じない。
- マップに出ていない人（位置が推定できない人）には指示を送れない。

**AP の区間ごとの指示**（2026-11-20〜。エリアカードの代わり）
- 作業者の円以外の所（トンネルの中か上のラベル）をクリックすると、その区間のポップアップが出る（`findSegmentAt` → `openSegmentPopup`）。中身：区間（例「100〜200m」）、今の区間の指示、いる人、指示ボタン4つ（なし／待て／奥へ／手前へ）。
- ボタンを押すと `POST /api/segment_instructions {segment_key, instruction}`（`saveSegmentInstruction`）。サーバーは区間の指示を `segment_instructions` に保存し、**その区間に今いる人全員**に個別指示（`device_instructions`）として送る（「なし」も送る）。
- **あとから区間に入った人**には、`GET /api/wifi_map` のたびに `apply_segment_instructions` が、その区間の指示（「なし」以外）を1回だけ送る。送ったことは `device_segment_state` に覚える。「なし」の区間に入ったときは、今の指示を消さない。
- 区間の指示のあとにポップアップで個別に出した指示は、その人が別の区間に移るか区間の指示が変わるまで残る。
- ウォッチは今までどおり `device_instructions` を読むだけなので、ウォッチ側の変更は要らない。区間は AP の配置から決まる（AP を足す・距離を変えると区間も変わり、古い区間の指示は使われなくなる）。

**火災位置**
- 「火災位置を指定」を押すと指定モードになる（マップに赤い点線枠、ボタンは「指定をやめる」）。
- マップをクリック → 確認ダイアログ → `POST /api/fire_location {ratio}`。Esc でもモードを抜ける。
- 「火災位置を解除」→ 確認 → `DELETE /api/fire_location`。
- ボタンの横に状態を出す（「火災位置: 入口から約320m（ウォッチに通知中）」／「未設定」）。

### 7.5 エリアカード（削除済み）
2026-11-20 に削除した。代わりは §7.4 の AP の区間ごとの指示。`area_status_v2` のエリア指示・火災フラグを画面から変える手段は無くなった（値は DB に残る）。

### 7.6 入場管理
- 「現在の入場状況」：入場中を上にして、名前・状態・入場時刻・退場時刻を出す。
- 「入場ログ（直近）」：最新 30 件。
- 時刻はブラウザのローカル時間で `MM/DD HH:MM:SS` と表示する（`formatEntryTime`）。

### 7.7 設定画面
- **AP位置設定**：行ごとに MAC と位置（「AP3（100m）」のようなプルダウン。`AP_LABELS` / `AP_POSITION_DISTANCES_M`）。
  - 「保存」で1行ずつ POST する。行の削除は即 DELETE。
  - プリセット：選んで「読み込み」を押すと表に広げるだけで、反映するには「保存」が要る。ほかに「プリセットとして保存」と「削除」。
- **エリア割当設定**：エリア ID と BSSID の対応。「保存」で1行ずつ POST、行の削除は即 DELETE。
- **ユーザー設定**：ユーザー名とデバイス ID。
  - 「保存」では、デバイス ID を変えた行の古い ID を DELETE してから全行を POST する。行の削除は即 DELETE。
  - 定期更新のとき、まだ保存していない入力は残す。
- **ESP32 AP**：状態（稼働中／停止）、表示名、BSSID、入口からの距離、位置推定に使うか（プルダウン）、最終通信、保存・削除。
  - 保存は `POST /api/ap_nodes`。保存後はマップも描き直す。
  - 「使う・使わない」をチェックボックスにしないのは、全体の仕組み（§7.8）で行が赤く点滅してしまうため。

### 7.8 見た目（`style.css`）
- 方針：
  - ドット調（DotGothic16、角の無いピクセル枠、ずらした影）。ロゴ `banner.png` は変えない。
  - 末尾の「見やすさ調整」ブロック（2026-10）が後から上書きする。
  - 状態を上に置く（マップ → エリア → 入場 → 設定）。赤は火災と通報だけに使う。色だけでなく文字でも示す。文字のコントラストは 4.5:1 以上、本文 16px。
- 色の変数：基本は `--pixel-blue #207ce5` / `--pixel-green #2d9610` / `--pixel-red #ff4b2b` / `--pixel-dark-solid #194c22`。状態色は `--state-*`（待機 `#8a5300`、避難 `#1a5fb4`、警戒 `#a34700`、火災 `#c62828`）。マップの色は `admin.js` の `C_*` に別に書いてある。
- チェックボックスにチェックが入ると、一番近い `.box` か `tr` に `.is-alerting`（赤い点滅）が付く（`admin.js` 末尾のイベント委譲）。すべてのチェックボックスに効く。
- 画面幅への対応：1200px 以下ではエリアカードが横スクロール、1400px 以下では設定3列が縦に並ぶ。スマホ幅では余白を詰める。

### 7.9 ログイン画面（`login.html`）
- ラベル付きのメール・パスワード欄（16px）と「SYSTEM START」ボタン。Enter でも送信できる。
- 「アカウントを作成する」で新規登録モードに切り替わる。
- 送信は `fetch('/', POST {email, password, mode})`。失敗・未入力・通信エラーはフォーム内の赤い帯に出す。
- ロゴは上下に跳ねる（`prefers-reduced-motion` の環境では止める）。

---

## 8. ESP32-S3 ビーコン（`firmware/esp32s3_ap/`、旧 ESP32-S3 AP）

### 8.1 役割
トンネルに並べる**位置の目印**。2.0.0 から **BLE ビーコン**（1.x は Wi-Fi softAP）。現場の Wi-Fi AP（既設6台）と併用する。ウォッチは接続せず、スキャンしてアドレスを拾うだけ。ウォッチは BLE のスキャンを RSSI 上位3つで `ble_reports` に送り、移行中の `wifi_reports` には「`MAMOTCHI-` の BLE が見えれば BLE の上位2つ、見えなければ Wi-Fi の上位2つ」を入れる（`docs/WATCH_SCAN_REPORTS.md`、位置の計算は §6.3）。

### 8.2 動作（`esp32s3_ap.ino`）

| 処理 | 内容 |
|---|---|
| BLE | `BLEDevice::init("MAMOTCHI-<AP_LABEL>")` → `BLEDevice::setPower(BLE_TX_POWER)`（既定 +3dBm）→ 広告間隔 `BLE_INTERVAL_MS`（既定 100ms）で `BLEDevice::startAdvertising()`。アドレスは `BLEDevice::getAddress()`（ESP32 固有、大文字にして送る）。Arduino-ESP32 3.3.13 の S3 は NimBLE |
| 起動 | 上り回線の設定があれば `WIFI_STA`（`ENABLE_WIFI_AP 1` なら `WIFI_AP_STA`）。Wi-Fi と BLE を同時に使うため省電力はオン（`WiFi.setSleep(true)`、ESP32 の共存の決まり） |
| Wi-Fi softAP（任意） | `ENABLE_WIFI_AP 1` のときだけ従来どおり `MAMOTCHI-<AP_LABEL>` を立てる。位置の目印としては登録しない |
| 上り回線 | `WiFi.begin(UPLINK_SSID, UPLINK_PASSWORD)`、切れたら 15 秒ごとに再接続 |
| heartbeat | 上り回線がつながっていれば 30 秒ごとに `POST {SERVER_BASE_URL}/api/ap_heartbeat`（`X-AP-Token`）。`mac` は **BLE アドレス**、ほかに表示名・距離・FW 版（`ble-2.0.0`）・稼働秒・BLE 出力[dBm]・チャンネル・上り回線の RSSI |
| TLS | `SERVER_ROOT_CA` を設定すればその証明書で検証、無ければ検証しない（`setInsecure()`、試験用） |

### 8.3 1台ごとの設定（`config.h`。`config.example.h` をコピーして作る。Git 管理外）
`AP_LABEL`（例 `A050`、英数字 17 文字まで）、`AP_DISTANCE_M`（初回登録の初期値）、`BLE_TX_POWER`（全台で揃える）、`BLE_INTERVAL_MS`、`ENABLE_WIFI_AP`（既定 0。1 のとき `AP_CHANNEL` / `AP_PASSWORD` / `TX_POWER_DBM`）、`UPLINK_SSID` / `UPLINK_PASSWORD`、`SERVER_BASE_URL`、`AP_TOKEN`、任意で `SERVER_ROOT_CA`。

### 8.4 導入手順
1. `supabase/ap_nodes.sql` を実行し、Vercel に `AP_SHARED_TOKEN` を設定する。
2. Arduino IDE に「esp32 by Espressif Systems」を入れ、ボードは ESP32S3 Dev Module を選ぶ。
3. `config.h` を作って書き込む。
4. 電源を入れると「ESP32 AP」表に出るので、距離を確認して保存する。
5. 上り回線が無い場合は、シリアル（115200bps）に出る BLE の `address` を「AP位置設定」に手で登録する。1.x（Wi-Fi）から入れ替えると「ESP32 AP」表に BLE アドレスの新しい行ができるので、距離を入れて古い行を削除する。この場合は6か所・100m 間隔の位置番号しか選べない。

使っている Arduino-ESP32 の API は、公式ドキュメントと `WiFiGeneric.h` / `WiFiType.h` / `WiFiScan.h` で存在を確認済み。2026-11-18 に Arduino-ESP32 3.3.13（ESP32S3 Dev Module、標準パーティション）で**コンパイル成功**（フラッシュ 75%・RAM 14%。機能を足すならパーティションを広げる）。実機での動作はまだ確認していない。

---

### 8.5 ESP32 カメラ（`firmware/esp32cam_uplink/`、外から見られるコマ送りカメラ）
- **目的**: 同じ Wi-Fi にいなくても、ダッシュボードの「カメラ」欄で映像を見る。公式サンプル CameraWebServer（`http://192.168.4.1` で同じ Wi-Fi から見る）とは別のファームウェア
- **仕組み**: カメラはインターネットにつながる Wi-Fi（現場 Wi-Fi・モバイルルーター・テザリング）に**つなぎに行く**（STA）。10 秒ごとに `/api/camera_poll`。画面で「映像を見る」が押されると、画面が `/api/camera_frame/<id>` を 1 秒ごとに取りに来て `watch_until`（20 秒）を延ばし、次の poll の返事が `send: true` になる。カメラは約 1 秒ごとに JPEG を `/api/camera_frame` へ送り、返事が `send: false` になったら止まる
- **保存**: Supabase Storage の非公開バケット `camera-frames` に `<camera_id>/latest.jpg` として最新 1 枚だけ（録画しない）。閲覧はログイン必須
- **画面**: カメラごとにタイル（名前・距離・稼働中/停止・映像・撮影時刻と遅れ）。「映像を見る」を押したタイルだけ取得し、タブが隠れている間は取りに行かない。10 分で自動停止。設定（名前・距離・受け取る/受け取らない・削除）は欄の下の「カメラの設定」
- **定数**（`app.py`）: `CAMERA_WATCH_SEC=20`、`CAMERA_IDLE_POLL_SEC=10`、`CAMERA_FRAME_INTERVAL_MS=1000`、`CAMERA_ONLINE_SEC=60`、`CAMERA_MAX_FRAME_BYTES=600KB`
- **近くで見る（任意）**: `ENABLE_LOCAL_VIEW 1` で自分の Wi-Fi も立て（AP+STA）、CameraWebServer の `app_httpd.cpp` の画面を `http://192.168.4.1` で同時に出す。同じカメラを使うので両方見るとコマ数は落ちる
- **firmware**: 実機は ESP32-S3-EYE（`CAMERA_MODEL_ESP32S3_EYE`、上下反転を補正）。CameraWebServer の `board_config.h` / `camera_pins.h` / `partitions.csv`（と、近くで見るなら `app_httpd.cpp` / `camera_index.h`）をコピーして使う（Git には入れない）。**位置推定用の BLE ビーコンを兼ねる**（`ENABLE_AP_BEACON 1`、既定、FW 1.4.0）：名前 `MAMOTCHI-<CAMERA_ID>` で広告し、BLE アドレスを 30 秒ごとに `/api/ap_heartbeat` へ送り（§8.2 と同じ項目、fw は `ble-cam-1.4.0`）、`ap_nodes` に登録される。生存通知に `ap_mac`（BLE アドレス）を入れるので、カメラ欄の距離と「ESP32 AP」表の距離は連動する（正は `ap_nodes.distance_m`。どちらの表で変えても同じ値になる）。BLE の出力は `BLE_TX_POWER`（既定 +3dBm）。Wi-Fi の出力は下げない。自分の Wi-Fi（`LOCAL_AP_SSID`）は近くで見る画面専用。画像はまず JPEG・VGA で撮り、センサーが JPEG 非対応（`esp_camera_init` が `0x106`）なら RGB565（`RGB_FRAME_SIZE` 既定 QVGA）で撮り直して `frame2jpg`（`RGB_JPEG_QUALITY` 既定 60）で JPEG に変換して送る（FW 1.2.0）。ボード設定は ESP32S3 Dev Module・OPI PSRAM・Custom パーティション。`config.h` に `CAMERA_ID`、Wi-Fi、`AP_TOKEN`、画像サイズ（既定 VGA）と画質（既定 14）。`esp_camera_*` と HTTPClient の API は公式ソースで確認済み。2026-11-18 に Arduino-ESP32 3.3.13（ESP32S3 Dev Module・OPI PSRAM・Custom パーティション）で、近くで見る画面あり（約 1.15MB）・なし（約 1.08MB）の両方とも**コンパイル成功**。同日、実機（ESP32-S3-EYE、センサー PID 0x9b＝JPEG 非対応のため RGB565→JPEG 変換で動作）をテザリング経由でつなぎ、本番ダッシュボードで**映像が見えることを確認**
- **回線の目安**: 見ている間 1 時間に 70〜180MB、見ていない間は 10 秒ごとの小さな問い合わせだけ
- **導入**: `supabase/cameras.sql` を実行 → Vercel に `AP_SHARED_TOKEN` → firmware を書き込む（`firmware/esp32cam_uplink/README.md`）
- サーバー側は Supabase を偽物に差し替えたテスト（20 項目）で、登録・送信の開始と停止・保存・閲覧・認証を確認済み

## 9. ウォッチとの約束（まとめ）

ウォッチ（Galaxy Watch）のコードはこのリポジトリに無い。次の形を変えるとウォッチが動かなくなる可能性があるので、変える前に確認する。

| 方向 | 対象 | 内容 |
|---|---|---|
| ウォッチ → | `wifi_reports` | `device_id`, `mac01`（**最も強い AP／ビーコン**）, `mac02`（2番目）, `report`, `created_at`。位置推定の重み 0.8 はこの順番が前提。`MAMOTCHI-` の BLE ビーコンが見えれば BLE の上位2つ、見えなければ Wi-Fi の上位2つ（1回の報告に混ぜない。`docs/WATCH_SCAN_REPORTS.md`） |
| ウォッチ → | `wifi_reports_v2` / `ble_reports` | `device_id`, `scanned_at`, `mac01`/`rssi01`〜`mac03`/`rssi03`。Wi-Fi のスキャンと `MAMOTCHI-` の BLE のスキャンを別の表に 1 回 1 行（`docs/WATCH_SCAN_REPORTS.md`、`supabase/scan_reports.sql`） |
| → ウォッチ | `device_instructions` | `instruction ∈ {none, wait, inward, outward}`（個別指示） |
| → ウォッチ | `device_fire_alerts` | 自分の `device_id` の行。`direction ∈ {inward, outward, near, unknown}`、`message` はそのまま表示できる文（§6.7） |
| → ウォッチ（可能性） | `area_status_v2` / ログイン不要の API | `/api/area_status`、`/api/user`、`/api/area`、`/api/area_order`、`/api/entry_status`。ウォッチが使っているかはコードから確定できない |

ウォッチ側へのお願い（任意だが精度に効く）:
- SSID が `MAMOTCHI-` で始まる AP だけを mac01 / mac02 にする（関係ない AP を除くため）。
- スキャン結果の時刻を確かめる。Android / Wear OS のスキャン回数制限で、中身が古いままになりやすい。

---

## 10. 精度（シミュレーション）

いずれも計算機上のシミュレーションで、実機では計っていない。条件は次のとおり。
- 0〜500m のトンネルを 1m/秒で往復する作業者（奥で 60 秒止まる）
- 距離減衰（係数 2）と電波ノイズを入れて、ウォッチが「強い順に2つの AP」を送る
- 30 回の試行の平均

**AP 100m 間隔での新旧比較**（旧 = 最新1件の mac01・mac02 の中点）:

| 電波ノイズ / 送信間隔 | 平均誤差 | 90%点誤差 | エリア正答率（100m ごと） | 1回ごとの跳び |
|---|---|---|---|---|
| 4dB / 5秒 | 39m → 14m | 80m → 28m | 77% → 86% | 37m → 9m |
| 6dB / 5秒 | 52m → 18m | 100m → 38m | 65% → 81% | 57m → 12m |
| 8dB / 5秒 | 63m → 25m | 130m → 51m | 57% → 75% | 72m → 18m |
| 6dB / 10秒 | 50m → 23m | 100m → 46m | 66% → 77% | 57m → 24m |

**AP 間隔ごと**（今の方式、電波ノイズ 6dB）:

| AP 間隔 | 台数 | 送信 5 秒：平均 / 90%点 | 送信 30 秒：平均 / 90%点 |
|---|---|---|---|
| 100m | 6 | 19m / 39m | 30m / 60m |
| 50m | 11 | 11m / 23m | 17m / 35m |
| 25m | 21 | 8m / 15m | 9m / 20m |

- 精度を一番上げるのは、AP を増やして間隔を詰めること（ESP32 AP で安く増やせる）。
- 電波の強さ（RSSI）を送らせる方法は、平均誤差で約 20%（18m → 15m）しか改善しなかった。
- 平滑化の時間をウォッチの送信間隔に合わせて伸ばす案は、50m 間隔だと表示が遅れて逆に悪化したので採用していない。
- 平滑化のぶん、歩いている人の表示は数秒遅れる。トンネル内は電波が遠くまで届きやすい（導波管効果）ので、実際の誤差はこれより大きい可能性がある。

---

## 11. 開発支援

| ファイル | 中身 |
|---|---|
| `AGENTS.md` | AI・人間共通の開発ガイド。「やりたいこと → 編集するファイルと関数」の対応表、守るルール、確認方法、AI が答えるときの形式 |
| `CLAUDE.md` | `@AGENTS.md` を読み込むだけ（Claude Code 用） |
| `docs/AI_WORKFLOW.md` | 共同開発者向けの手順。リポジトリを読める AI とチャット AI での使い分け、指示文の例、書き換えたあとの流れ |
| `scripts/make_ai_context.py` | AGENTS.md・この仕様書・主要ソース（14 ファイル、約 220KB）を `dist/ai_context.md` にまとめる。`--no-css` で style.css を除く。`.env` と `config.h` は入れず、`app.py` の `secret_key` の値は伏せる |
| `scripts/demo_watch.py` | **デモ用**。ウォッチの代わりに、トンネルを歩く作業者（`demo-01`〜）のスキャン結果を `wifi_reports`・`wifi_reports_v2`・`ble_reports` に入れ続ける。AP の配置は `app.py` の関数で DB から読み、RSSI は距離減衰の式＋ばらつきで作る。`--auto-eval` で本当の位置と ①〜⑥ を `position_eval` に記録、`--cleanup` で `demo-` の行を全部消す。`api/.env` の Supabase（ふつうは本番）に書く |
| `scripts/flash_camera.py` | ESP32 カメラをカメラごとの設定ファイルで書き込む（`firmware/esp32cam_uplink/README.md`） |
| `scripts/build_spec_qa.py` | **仕様Q&A ページ**（`dist/spec_qa.html`、約 710KB）を作る。テンプレートは `scripts/spec_qa/template.html`。仕様書・開発ガイド・ソース 15 ファイルを埋め込み、ページから Claude に質問できる（Artifact の `sample` 機能）。毎回 AGENTS.md と SPEC.md の全文を渡し、ソースは Claude が「検索」「行範囲を読む」の道具で必要な所だけ読む。秘密の値は伏せる。公開先: https://claude.ai/artifact/NhhfAQbG1vPLCMjxxLzQC9（仕様やコードを変えたら作り直して同じ URL に公開し直す） |

---

## 12. 使われていないコード

- `admin.js`：`saveInstruction`、`loadAreaTable`、`saveAreaTable`（エリア状態の旧版）、`loadEntryTable`（`#entryTableBody` は存在しない）
- `app.py`：`update_or_append`、`entry_status_table`、`last_seen_dict`、`threading` / `json` / `time` の import、`/chkwifi`。`TABLE_WIFI_REPORTS` はデバッグ API でだけ使う

---

## 13. 既知の問題

### 運用
1. **本番デプロイが失敗中**（§2.4）。PR #26 の変更は本番に出ていない。
2. **実際に動かしていないコードがある**：PR #26 の `app.py`（ESP32 AP 受付、`ApMap`。構文チェックのみ通過）、ESP32 ファームウェア（コンパイルは成功、実機での動作は未確認）。
3. `requirements.txt` のバージョンが未固定。venv（`api/properioai/`）がコミットされている。
4. 2026-10 以前のテーブルの定義（SQL）がリポジトリに無い。

### セキュリティ
5. **書き込み系 API の多くがログイン不要**：`/api/area_status`、`/api/area`、`/api/area_order`、`/api/user` の POST/DELETE は誰でも呼べ、サーバーは全権キーで書く。ウォッチが使っている可能性があるので、塞ぐ前にウォッチ側を確認すること。
6. 誰でもサインアップでき、メール確認の前にログイン扱いになる。実質だれでも管理画面に入れる。
7. `secret_key` がハードコードされている（cookie を偽造できる）。
8. 古い API は例外メッセージをそのまま返す。
9. ESP32 は `SERVER_ROOT_CA` を設定しないと TLS 証明書を検証しない。
10. （解決済み）画面への文字列の埋め込みは、使われているコードではすべて `escapeHtml()` を通している。

### 正しさ
11. 入退場判定・火災通知の更新・通報の同期は、**ダッシュボードを誰かが開いている間しか走らない**。
12. 入退場判定はレポートの新しさを見ないので、ウォッチの電源が切れても「入場中」のまま。
13. `load_wifi_reports` が全履歴を読む。1000 行を超えると、しばらく送っていないデバイスが消え、遅くもなる。
14. `GET /api/wifi_map` と `GET /api/entry_management` が DB に書き込む（GET なのに副作用がある）。
15. エリア指示の値をサーバーで検証しない。
16. エリア割当設定でエリア ID を書き換えて保存すると、新しい行ができて古い行が残る（古い ID を消さない）。`DELETE /api/area` は行ごと消すので、指示・火災・並び順も消える。
17. `/chkwifi` は壊れている（`wifi.html` が辞書を前提にしているのに、渡すのはリスト）。
18. `/logout` は `logged_in` しか消さず、Supabase 側のサインアウトもしない。
19. 位置が推定できない作業者はマップに出ないので、個別指示を送れない。
20. エリアカードの火災フラグと火災位置の通知は連動しない。

---

## 14. 変更履歴（主なもの）

| 時期 | PR / コミット | 内容 |
|---|---|---|
| 2026-06〜07 | `feature/5`〜`feature/12`、`kosen_map` | SSID 管理から AP 位置ベースの推定へ。トンネルマップ、入退場、AP プリセット、デバイス指示 |
| 2026-09〜10 | #17（`feature/16-404-問題`） | ファイル整理、`index.py` → `api/app.py`、Vercel のルーティング修正。パフォーマンス修正（`738626b`）は差し戻し |
| 2026-10-11 | #25 | マップから個別指示、位置推定の一本化と平滑化、UI 改善、火災位置の通知、ログイン画面、仕様書・CodeQL 指摘の修正 |
| 2026-11-11 | #26 | AP を 100m 間隔に修正、`ApMap`、ESP32-S3 AP（heartbeat・管理画面・ファームウェア）、AGENTS.md ほか開発支援。**本番デプロイは失敗中** |
| 2026-11-18 | #28〜#30 | ESP32 カメラ（外から見るコマ送り、RGB565→JPEG 変換）、カメラが位置の目印を兼ね距離を ESP32 AP 表と連動 |
| 2026-11-20 | — | 位置推定の欄をマップの真上、ESP32 AP 欄を設定の下へ。位置推定 ⑥（Wi-Fi と BLE を合わせる）、⑤ の探す範囲を前後1区間に、`SERIES_WALK_MPS` 3.0。デモ用 `scripts/demo_watch.py` |
| 2026-11-20 | — | エリアカードを削除し、AP の区間ごとの指示（個別指示として送る）に。マップの点線を AP の区間に。ESP32 AP 欄をマップの真上に（1366×768 でスクロールせずに両方見える）。位置推定 ⑤（Wi-Fi だけ・上位3つの当てはめ） |
| 2026-11-19 | — | ウォッチのスキャンを RSSI 上位3つで `wifi_reports_v2` / `ble_reports` に。位置推定を ①〜④ の4方式にし、画面で切り替え・現地で比較記録 |
| 2026-11-18 | — | ESP32 の位置の目印を BLE ビーコンに（`esp32s3_ap` 2.0.0、カメラ 1.4.0）。ウォッチは BLE 優先・無ければ Wi-Fi（`docs/WATCH_SCAN_REPORTS.md`） |

旧ブランチ: `feature/5-位置の推定`、`feature/6-コードのネーミング見直し`、`feature/7-コードの整合性1`（`tests/test_index.py` あり）、`feature/9-エリアカードの表記`、`feature/10-エリアカードの並び`、`feature/12-テーブルの統合`、`kosen_map`、`kosen_map_b`、`dev/Ryo`、`#34`。
