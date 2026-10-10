# まもっち（MAMOTCHI）現状仕様書

> 2026-10-10 時点の `main`（`fd5c71f`）を全ファイル読んで書いた**現状の仕様**です。
> 「こうあるべき」ではなく「今こう動く」を書いています。既知の問題は §9 にまとめました。
> コードを変えたらこのファイルも直してください。

- 本番: https://test-fawn-iota-73.vercel.app/ （Vercel / `api/` をルートにデプロイ）
- リポジトリ: https://github.com/yama-k-07/test
- 構成: Python Flask（1ファイル `api/app.py`）＋ Supabase（Postgres / Auth / Realtime）＋ 素の JS（`api/static/admin.js`）

---

## 1. システム概要

トンネル（または建屋）内の作業者の位置を、**作業者が身に着けたデバイス（Galaxy Watch 等）が接続している Wi-Fi AP の MAC アドレス**から推定し、管理者がダッシュボードで

1. 作業者の位置（エリア・トンネルマップ）を見る
2. エリアごとに避難指示・火災フラグを出す
3. デバイスごとに個別指示（待て／奥へ／手前へ）を出す
4. 入退場の状態とログを見る

ためのシステム。

```
[デバイス (Galaxy Watch)]
   │  ① 接続中APのMAC(mac01, mac02)・通報フラグ(report) を書き込む
   ▼
[Supabase] wifi_reports / latest_wifi_reports            ← このリポジトリにデバイス側コードは無い
   ▲   │  ② Flask が読み出して位置推定・入退場判定
   │   ▼
[Flask api/app.py] ── JSON API ──> [ブラウザ admin.js]（5秒ポーリング＋Realtime）
   │
   └─ ③ 指示を書き込む: area_status_v2.instruction/fire, device_instructions.instruction
        → デバイスがこれを読んで表示する（読み方はこのリポジトリ外）
```

**デバイス側の実装はこのリポジトリに無い。** デバイスが Supabase に直接書く／読むのか、Flask API（認証なしの `/api/area_status` 等）を叩くのかはコードからは確定できない。デバイスとの契約になりうるテーブル・API（§4, §5 の ★印）は形を変える前に確認すること。

---

## 2. ファイル構成

| パス | 状態 | 内容 |
|---|---|---|
| `api/app.py` | **本体** | Flask アプリ。全ルート・全ロジック（約730行） |
| `api/vercel.json` | 使用中 | `@vercel/python` で `app.py` をビルド、全パス `/(.*)` を `app.py` へ |
| `api/templates/index.html` | **使用中** | ダッシュボード（`/index`） |
| `api/templates/login.html` | **使用中** | ログイン／サインアップ（`/`）。JS はインライン |
| `api/templates/wifi.html` | 壊れている | `/chkwifi` 用。現データ形式と不一致（§9） |
| `api/templates/sql_test.html` | 未使用 | どのルートからも参照されない |
| `api/templates/*_deprecated.html` | 未使用 | 旧画面 |
| `api/public/templates/index.html` | 未使用 | 旧ダッシュボードの残骸（先頭に `//もどれ` という文字列混入） |
| `api/static/admin.js` | **使用中** | ダッシュボードのロジック全部（約1300行） |
| `api/static/style.css` | **使用中** | ドット絵風テーマ（DotGothic16 + Bulma 上書き） |
| `api/static/banner.png` | 使用中 | ロゴ |
| `api/static/script.js` | 未使用 | 最初期のプロトタイプ（`a_deprecated.html` 用、`prompt()` でエリア数を聞く） |
| `api/static/style_deprecated.css` | 未使用 | 旧CSS |
| `api/ANALYSIS.md` | 古い | 2026-08 時点の解析。存在しないファイル（`index.py`, `M5emu.py` 等）に言及。**このSPEC.mdが正** |
| `api/properioai/` | 不要 | Python venv がコミットされている（1300ファイル超）。アプリコードではない |
| `requirements.txt` | 使用中 | `flask, supabase, requests, python-dotenv`（バージョン未固定） |
| `.gitignore` | | `.vercel`, `.env` のみ |

外部ライブラリ（CDN）: Bulma 0.9.4、SortableJS 1.15.0、`@supabase/supabase-js@2`（UMD）、Google Fonts DotGothic16。

---

## 3. 環境変数・起動

| 変数 | 用途 |
|---|---|
| `SUPABASE_URL` | Supabase プロジェクトURL（サーバー・ブラウザ両方で使用） |
| `SUPABASE_SERVICE_ROLE_KEY` | サーバー側の Supabase クライアント。**RLS をバイパスする全権キー** |
| `SUPABASE_ANON_KEY` | ブラウザの Realtime 購読用。`index.html` に埋め込まれて配信される |

- `app.secret_key` はハードコード（`'mamotchi_secret_key_pixel'`）。
- ローカル起動: `api/.env` に上記を書いて
  ```bash
  pip install -r requirements.txt
  cd api && python app.py   # http://localhost:5000
  ```
  ※ `.env` が無いと `create_client(None, None)` で起動時に落ちる。
- テストコードは `main` に無い（`feature/7-コードの整合性1` に `tests/test_index.py` がある）。

---

## 4. データモデル（Supabase テーブル）

スキーマ定義（SQL）はリポジトリに無い。以下はコードの読み書きと本番 API の応答から推定した列。

| 定数 | テーブル | 主キー（推定） | 列 | 書く人 | 読む人 |
|---|---|---|---|---|---|
| `TABLE_WIFI_LOG` | ★`wifi_reports` | `id`（連番） | `device_id`, `mac01`, `mac02`, `report`(bool, 通報), `created_at` | デバイス | Flask（位置推定・入退場・同期） |
| `TABLE_WIFI_REPORTS` | ★`latest_wifi_reports` | `device_id`? | wifi_reports と同形で各デバイス最新1行（と推定） | デバイス or DBトリガ | ブラウザ Realtime 購読、`/api/debug/wifi_map` |
| `TABLE_AREA_STATUS` | ★`area_status_v2` | `area_id` | `area_id`, `bssid`, `instruction`, `fire`(bool), `area_order`(int) | Flask | Flask、（デバイス?） |
| `TABLE_USER` | `user` | `device_id`（upsert競合キー） | `device_id`, `username`（旧: `area_id`） | Flask | Flask |
| `TABLE_AP_POSITIONS` | `ap_positions` | `mac` | `mac`, `position`(0〜5) | Flask | Flask |
| `TABLE_AP_PRESETS` | `ap_position_presets` | `name` | `name`, `positions`(JSON配列 `[{mac,position}]`), `updated_at` | Flask | Flask |
| `TABLE_DEVICE_INSTRUCTIONS` | ★`device_instructions` | `device_id` | `device_id`, `instruction`(`none/wait/inward/outward`), `report`(bool), `updated_at` | Flask | Flask、デバイス（推定） |
| `TABLE_ENTRY_CURRENT` | `entry_current` | `device_id` | `device_id`, `username`, `status`(`in/out`), `entry_time`, `exit_time`, `updated_at` | Flask | Flask |
| `TABLE_ENTRY_LOG` | `entry_log` | 自動 | `device_id`, `username`, `event_type`(`enter/exit`), `event_time` | Flask | Flask |

| `TABLE_FIRE_LOCATION` | `fire_location` | `id`（常に1） | `active`, `distance_m`, `updated_at` | Flask | Flask |
| `TABLE_DEVICE_FIRE_ALERTS` | ★`device_fire_alerts` | `device_id` | `fire_active`, `direction`, `distance_m`, `message`, `approx`, `updated_at` | Flask | ウォッチ（§7.7） |

★ = デバイスとの境界になっている（と思われる）テーブル。`fire_location` / `device_fire_alerts` は 2026-10-10 追加（`supabase/fire_location.sql`）。

`area_status_v2` は「エリアマスタ（area_id↔bssid）」「エリア状態（instruction/fire）」「並び順（area_order）」の3役を1テーブルで兼ねている。3つの API（`/api/area`, `/api/area_status`, `/api/area_order`）がそれぞれ別の列を部分 upsert する。

本番データ例（2026-10-10 取得）:
```json
// GET /api/area
[{"area_id":"akiko_lab","bssid":"00:90:C7:0E:29:12"},{"area_id":"kuriyma_lab","bssid":"00"}, ...]
// GET /api/user
[{"device_id":"8f477d9d10107273","username":"tama"},{"device_id":"b0ec4b994cdc208b","username":"watch1"}]
```
（現在は研究室名がエリアとして登録されている＝トンネルではなく校舎でのテスト運用中）

---

## 5. HTTP API（`api/app.py`）

認証列: 🔒 = `login_required`（未ログインは `/` に302）。**無印は誰でも呼べる（書き込み含む）。**

### 5.1 画面

| メソッド パス | 🔒 | 動作 |
|---|---|---|
| `GET /` | | ログイン済みなら `/index` へリダイレクト、それ以外は `login.html` |
| `POST /` | | JSON `{email, password, mode}`。`mode:"signup"` → `supabase.auth.sign_up`、それ以外 → `sign_in_with_password`。成功で `session.logged_in=True` と `{"status":"success","redirect":"/index"}`。失敗は 401 と例外メッセージ |
| `GET /index` | 🔒 | `index.html`（`SUPABASE_URL` と `SUPABASE_ANON_KEY` を `window.SUPABASE_CONFIG` として埋め込み） |
| `GET /logout` | | `session.logged_in` を消して `/` へ |
| `GET,POST /chkwifi` | 🔒 | 旧ユーザー登録画面。**壊れている**（§9） |
| `GET /test-deploy` | | 文字列 `DEPLOYED-V3-POST-OK`（デプロイ確認用） |

### 5.2 マスタ・状態

| メソッド パス | 🔒 | リクエスト | レスポンス／動作 |
|---|---|---|---|
| ★`GET /api/area_status` | | | `[{area_id, instruction, fire}]` |
| ★`POST /api/area_status` | | `[{area_id, instruction?, fire?, ...}]`（配列必須、各要素に `area_id` 必須） | `area_status_v2` に upsert。値の検証なし |
| `GET /api/area` | | | `[{bssid, area_id}]` |
| `POST /api/area` | | `{area_id, bssid}` 両方必須 | upsert |
| `DELETE /api/area` | | `{area_id}` | 行ごと削除（instruction/fire/order も消える） |
| `GET /api/area_order` | | | `area_order` 昇順の `area_id` 配列（失敗/空なら順序なしで全件） |
| `POST /api/area_order` | | `["akiko_lab", ...]` | 各要素に `{area_id, area_order: index}` を upsert |
| `GET /api/user` | | | `[{device_id, username}]` |
| `POST /api/user` | | `{username, device_id}` 両方必須 | upsert。username 欠落時は受け取った JSON をそのまま `error` に返す |
| `DELETE /api/user` | | `{device_id}` | 削除。残りの一覧を `user_table` で返す |
| `GET,POST,DELETE /api/ap_positions` | 🔒 | POST `{mac, position}` / DELETE `{mac}` | GET は `position` 昇順 |
| `GET,POST,DELETE /api/ap_presets` | 🔒 | POST `{name, positions:[{mac,position}]}` / DELETE `{name}` | GET は name 昇順。POST は name で upsert |
| `GET /api/device_instructions` | 🔒 | | `device_instructions` 全行 |
| `POST /api/device_instructions` | 🔒 | `{device_id, instruction, report?}` | `instruction ∈ {none, wait, inward, outward}` を検証して upsert |

### 5.3 位置推定・入退場（§6 で詳説）

| メソッド パス | 🔒 | レスポンス | 副作用 |
|---|---|---|---|
| `GET /api/wifi_map` | 🔒 | `{workers:[{device_id, username, report, ratio, distance_m, area_id, approx, online}], ap_count, ap_labels, ap_markers, area_order, area_layout, online_device_ids}`（§6.2） | **GET なのに書き込む**: `wifi_reports.report` を `device_instructions.report` に同期 |
| `GET /api/entry_status` | | `[{area_id, username, device_id}]`（§6.2 と同じ推定） | なし |
| `GET /api/entry_management` | 🔒 | `{status:[entry_current の今日(JST)分]}` | **GET なのに書き込む**: 入退場判定して `entry_current` upsert / `entry_log` insert |
| `GET /api/entry_log?limit=N` | 🔒 | 今日(JST)の `entry_log` を新しい順に N 件（既定50, 上限200） | なし |
| `GET /api/debug/wifi_map` | 🔒 | 生テーブルとロード結果をまとめて返す | なし |
| `GET /api/fire_location` | 🔒 | `{active, distance_m, updated_at}` | なし |
| `POST /api/fire_location` | 🔒 | `{ratio}`（マップ横軸 0〜1）か `{distance_m}` → `{message, fire}` | `fire_location` を保存し `device_fire_alerts` を更新（§7.7） |
| `DELETE /api/fire_location` | 🔒 | `{message, fire}` | 火災位置を解除し、全デバイスの `fire_active=false` |

`GET /api/wifi_map` は `fire: {active, distance_m, ratio}` と各 worker の `fire_message` も返し、そのたびに `device_fire_alerts` を更新する。

エラーは基本 `{"error": "<例外文字列>"}` + 400/500。ログイン系だけ `{"status":"error","message":...}`。

---

## 6. コアロジック

### 6.1 最新レポートの取り出し `load_wifi_reports()`
`wifi_reports` を **全件** `id` 降順で取得し、`device_id` ごとに最初の1行（＝最新）だけ残す。
（PostgREST の既定上限で最大1000行しか返らない点に注意。§9）

> 2026-10-04 に `latest_wifi_reports` から必要列だけ読む＋`ThreadPoolExecutor` で並列化する「パフォーマンス修正」(`738626b`) が入ったが、`feature/16-404-問題` で**差し戻し**（`586da82`）。理由はコミットに書かれていない。

### 6.2 位置推定 `estimate_positions()`（2026-10-10 改訂）
トンネルマップ（`/api/wifi_map`）とエリアボード（`/api/entry_status`）は**同じ関数**で位置とエリアを決める。

定数（`app.py` の「位置推定」ブロック。画面は `/api/wifi_map` の `ap_markers` / `area_layout` を受け取って描くので JS 側の変更は不要）:

| 定数 | 値 | 意味 |
|---|---|---|
| `AP_LABELS` | `['1','3','4','5','6','11']` | 位置番号 0〜5 の表示名 |
| `AP_DISTANCES_M` | `[1, 3, 4, 5, 6, 11]` | 位置番号 0〜5 の入口からの実距離[m]（画面説明「0=入口1m 〜 5=奥11m」に合わせた。**等間隔ではない**） |
| `MAC01_WEIGHT` | `0.8` | mac01（最も強いAP。ウォッチの仕様）の重み。mac02（2番目）は 0.2 |
| `SMOOTHING_WINDOW_SEC` | `30` | 最新レポートから何秒前までのレポートを使うか |
| `SMOOTHING_HALF_LIFE_SEC` | `8` | 古いレポートの重みが半分になる秒数 |
| `SMOOTHING_MAX_SAMPLES` | `8` | 使うレポートの最大件数 |
| `OUTLIER_M` | `5.0` | 重み付き中央値からこれ以上離れたレポートは外れ値として捨てる |

デバイスごとの手順:
1. 1レポートの距離 = `0.8 × 距離(mac01) + 0.2 × 距離(mac02)`（片方しか `ap_positions` に無ければその AP の距離）
2. 直近 60 秒の `wifi_reports` を1回だけ取得し（`load_recent_wifi_reports`）、そのデバイスの最新から 30 秒以内・最大 8 件を集める
3. 重み `0.5^(経過秒/8)` で重み付き中央値を出し、そこから 5m 以上離れたものを捨てて重み付き平均 → `distance_m`
4. `ratio = (distance_m − 1) / (11 − 1)`（マップ横軸。0=AP1, 1=AP11）
5. エリアの決め方（上ほど優先）:
   1. 全エリアの `bssid`（エリア割当設定）が `ap_positions` にある → エリア中心＝その AP の距離、**最寄りのエリア**。区切りは中心間の中点
   2. 最新レポートの mac01 / mac02 がどれかのエリアの `bssid` と一致 → そのエリア（旧エリアボード方式）
   3. トンネル（AP1〜AP11 の実距離）を `area_order` で等分した区間（旧マップ方式）
6. 最新レポートの AP がどちらも `ap_positions` に無い場合は古い位置を使わない。ただし 5-2 の BSSID 一致があれば、そのエリアの中央に `approx: true` で置く（マップでは点線の円）

`/api/wifi_map` の `workers[]` は `{device_id, username, report, ratio, distance_m, area_id, approx, online}`。ほかに `ap_markers:[{label, distance_m, ratio}]` と `area_layout:[{area_id, start, end}]`（比率）を返す。

`online_device_ids` / `online` = 最新レポートの `created_at` が **60秒以内**（`ONLINE_THRESHOLD_SEC`）。オフラインの作業者はマップで薄く描く（最後に見えた位置）。
`parse_ts()` は小数秒を6桁にそろえてからパースする（Python 3.10 の `fromisoformat` は `.12345` のような桁で失敗し、以前はそのデバイスが常にオフライン扱いになり得た）。

`sync_device_reports_from_wifi()`: デバイス側の書き込み先が `device_instructions.report` へ移行するまでの橋渡し。`wifi_reports` 最新行の `report` と違うデバイスだけ upsert する。

**精度（シミュレーション）**: トンネルを往復する作業者を、距離減衰＋6dB の電波ノイズで「強い順に2つの AP」を5秒ごとに送る設定で比較（40試行）。

| 電波ノイズ / 送信間隔 | 平均誤差 | 90%点誤差 | エリア正答率 | 1回ごとの位置の跳び |
|---|---|---|---|---|
| 4dB / 5秒 | 1.70m → 0.94m | 4.13m → 1.90m | 70% → 79% | 1.19m → 0.52m |
| 6dB / 5秒 | 1.96m → 1.08m | 4.38m → 2.21m | 68% → 76% | 1.30m → 0.59m |
| 8dB / 5秒 | 2.19m → 1.26m | 4.75m → 2.54m | 62% → 74% | 1.41m → 0.72m |
| 6dB / 10秒 | 1.97m → 1.16m | 4.26m → 2.45m | 67% → 83% | 1.41m → 1.14m |

実機の送信間隔とノイズは未計測。平滑化のぶん、動いている人の表示は数秒遅れる。

### 6.3 エリアボードの位置 `GET /api/entry_status`
§6.2 と同じ `estimate_positions()` の `area_id` を返す（2026-10-10 まではマップと別方式の「mac01 と bssid の完全一致」だけだった）。レスポンスの形 `[{area_id, username, device_id}]` は変えていない。

### 6.4 入退場判定 `do_entry_status_update()`（`/api/entry_management` から呼ばれる）
- 入場中の条件: 最新レポートの `mac01` か `mac02` が `ap_positions` に登録済み（`ap_positions` が空なら全員「外」）
- 前回 `entry_current.status` が `in` 以外 → 入場中になったら `entry_current` を `in`（`entry_time=now`）にして `entry_log` に `enter`
- 前回 `in` → 条件を満たさなくなったら `out`（`exit_time=now`）にして `entry_log` に `exit`
- 返すのは `updated_at` が今日（JST 0:00〜24:00）の `entry_current` のみ
- **判定はこのAPIが呼ばれた時だけ走る** = ダッシュボードを誰かが開いている間しか入退場が記録されない
- **レポートの鮮度を見ない** = デバイスが電源断で送信停止すると最後のレポートのまま「入場中」が続く

### 6.5 認証
- Supabase Auth のメール＋パスワード。Flask の署名付き cookie セッションに `logged_in` / `user_email` を入れるだけ。ロールや許可リストは無い。
- サインアップは誰でも可能で、`sign_up` が user を返した時点でログイン扱い（メール確認を待たない）。

---

## 7. ダッシュボード（`templates/index.html` + `static/admin.js`）

### 7.1 画面構成（上から順）

| セクション | DOM id | 描画関数 | データ元 | 操作 |
|---|---|---|---|---|
| トンネルマップ（兼デバイス指示） | `canvas#tunnelMap`, `#workerPopup` | `loadTunnelMap` / `renderTunnelMap` / `openWorkerPopup` | `/api/wifi_map` + `/api/device_instructions` | 作業者アイコンをクリック → ポップアップの指示ボタン → 即 `POST /api/device_instructions`（§7.6） |
| エリアごとの状態 | `#areaBoard` | `loadAreaBoard` / `createAreaCard` | `/api/area_status` + `/api/entry_status` + `/api/area_order` | 指示セレクト・火災チェック → 即 `POST /api/area_status`。カードをドラッグ（SortableJS）→ `POST /api/area_order` |
| 入場管理 | `#entryCurrentBody`, `#entryLogBody` | `loadEntryManagement` / `renderEntry*Table` | `/api/entry_management` + `/api/entry_log?limit=30` | 表示のみ |
| AP位置設定 | `#apPositionsTableBody`, `#apPresetSelect`, `#apPresetNameInput` | `loadApPositionsTable`, `loadApPresetList` | `/api/ap_positions`, `/api/ap_presets` | 行追加・保存（1行ずつPOST）・行削除（即DELETE）、プリセット読込（表に展開するだけ、保存は別操作）・保存・削除 |
| エリア割当設定 | `#areaTableBody` | `loadAreaMapTable` | `/api/area` | 行追加・保存（1行ずつPOST）・行削除（即DELETE） |
| ユーザー設定 | `#userTableBody` | `loadUserTable` | `/api/user` | 行追加・保存（device_id 変更時は旧IDをDELETEしてからPOST）・行削除（即DELETE） |

選択肢:
- エリア指示（`instructionOptions`）: 値 `none, waiting, evacuate_exit, evacuate_upwind, alert`（**サーバー側では検証しない**）。表示は `AREA_INSTRUCTION_LABELS` で「指示なし／待機／出口へ避難／風上へ避難／警戒」（値は変えていない）
- デバイス指示（`DEVICE_INSTRUCTION_LABELS`）: `none=なし, wait=待て, inward=奥へ, outward=手前へ`

### 7.2 更新の仕組み
- `DOMContentLoaded` で全セクションを1回ロード。
- `setInterval` 5秒ごとに `loadAreaBoard, loadAreaMapTable, loadUserTable, loadEntryManagement, loadTunnelMap`（AP位置設定とプリセット一覧は初回のみ）。
- Supabase Realtime: anon key で `latest_wifi_reports` の `postgres_changes` を購読し、変化したら `loadTunnelMap()`。
- **ちらつき防止**: 各ロード関数は前回レスポンスの `JSON.stringify` を `last*Sig` に持ち、同じなら再描画しない。
- **編集中ガード**: `input/select` に focus があると `isEditing=true` で定期更新を止める。ドラッグ中は `isSorting`。
- APIエラーや想定外の形のときは描画をスキップ（カードが消えないように）。

5秒ごとに `/api/wifi_map` が1回（＋Realtime 通知時）走り、毎回 `wifi_reports` 全件取得と report 同期が走る。（2026-10-10 にデバイス指示セクションを廃止するまでは1周期に2回だった）

### 7.3 トンネルマップ描画 `renderTunnelMap`
- 高さ200px固定、幅は親要素。左右40px余白。左端「外」、右端「奥」。
- 上辺にエリア名、点線でエリア区切り。位置はサーバーの `area_layout`（無ければ `area_order` を等分）。
- 下辺に AP マーカー（青丸）を `ap_markers[].ratio`＝**実距離の位置**に配置、ラベル `AP{label}`（無ければ等間隔）。
- オフラインの作業者は透明度 0.4、`approx` の作業者は点線の円。
- 作業者は半径18pxの円。x = `ratio`、重なったら上下に最大3段ずらす。名前は先頭6文字。
- `report: true`（通報中）の作業者は赤＋パルス発光。通報者がいる間だけ `requestAnimationFrame` ループ（`startReportGlowLoop`）で再描画。
- 「なし」以外の指示が出ているデバイスは、アイコン右上に青い指示バッジ（待て／奥へ／手前へ）。
- ポップアップを開いているデバイスのアイコンは青い外枠で強調。
- 描画のたびにアイコン位置を `tunnelMapHitboxes` に保存（クリック判定用）。
- ウィンドウ resize で再描画。

### 7.6 デバイス指示（トンネルマップから送る）
- 指示の値・送信先は従来のデバイス指示セクションと同じ: `DEVICE_INSTRUCTION_LABELS`（`none=なし, wait=待て, inward=奥へ, outward=手前へ`）を `POST /api/device_instructions {device_id, instruction}` → `device_instructions` に upsert → ウォッチが読む。
- `loadTunnelMap` は `/api/wifi_map` と `/api/device_instructions` を並列取得し、`deviceInstructionMap`（device_id → instruction）を更新する。
- キャンバスをクリック → `findWorkerAt` で円の当たり判定（重なっている時は後に描いた方）→ `openWorkerPopup`。
- ポップアップ（`#workerPopup`、`.tunnel-map-wrap` 内に absolute 配置）: 名前、オンライン/オフライン（`online_device_ids`）、現在の指示、指示ボタン4つ（現在値は `is-link`）。ボタンで送信 → 成功ならマップ再描画して閉じる、失敗なら `alert` してボタンを戻す。
- 閉じる: ×ボタン、ポップアップ外クリック、アイコン以外のキャンバスクリック、Esc。5秒ごとの再描画では閉じない。
- **マップに出ていないデバイス（`ap_positions` に一致するAPに繋がっていない）には指示を送れない。**（旧セクションは `user` 登録済み全デバイスが対象だった）

### 7.4 スタイル（`style.css`）
- テーマ色: `--pixel-blue #207ce5`, `--pixel-green #2d9610`, `--pixel-red #ff4b2b`, `--pixel-dark-solid #194c22`。キャンバスの色は `admin.js` 内に別途ハードコード。
- `style.css` 末尾の「見やすさ調整」ブロック（2026-10-10）が後勝ちで上書きする。方針: 状態を上に（マップ→エリア→入場→設定）、赤は火災・通報だけ、色＋文字で示す、文字コントラスト 4.5:1 以上、本文 16px。状態色は `--state-*`（待機=茶 `#8a5300`、避難=青 `#1a5fb4`、警戒=橙 `#a34700`、火災=赤 `#c62828`）。
- エリアカードは `.areacard[data-instruction]` で上辺と見出しの色が変わり、火災チェック中（`.is-alerting`）は赤見出し＋「火災通報あり」帯＋外枠の点滅。
- `#tunnelMap` の CSS 高さ（260px）と `renderTunnelMap` の `H` は同じ値にすること（違うとクリック判定がずれる）。
- 1200px 以下でエリアボードが横スクロール（scroll-snap）、1400px 以下で設定3列が縦積み。
- チェックボックスが checked になると、最も近い `.box`/`tr` に `.is-alerting`（赤点滅）が付く（`admin.js` 末尾のイベント委譲）。火災フラグ用だが**全チェックボックスに効く**。

### 7.5 ログイン画面（`login.html`）
ラベル付きのメール・パスワード欄（16px）と「SYSTEM START」ボタン。`<form>` の submit で処理するので Enter キーでも送信できる。「アカウントを作成する」ボタンで signup モードに切替。`fetch('/', POST {email, password, mode})` → 成功で `redirect` へ遷移、失敗・未入力・通信エラーはフォーム内の赤帯（`#loginError`, `role="alert"`）に表示。ロゴと上下バウンドは従来どおり（`prefers-reduced-motion` では止める）。

### 7.7 火災位置（管理マップで指定 → ウォッチへ通知）
- 画面: マップ上の「火災位置を指定」→ 指定モード（マップに赤い点線枠、カーソル位置に半透明の炎のプレビュー）→ マップをクリック → 確認ダイアログ → `POST /api/fire_location {ratio}`。Esc か「指定をやめる」で取り消し。「火災位置を解除」→ 確認 → `DELETE /api/fire_location`。
- 表示: 火災位置に赤い帯＋ドット絵の炎＋「火災 約Xm」。ボタン横に「火災位置: 入口から約Xm（ウォッチに通知中）」。作業者のポップアップに「ウォッチの表示: 火災: 奥 約4m」。
- サーバー: `fire_location`（id=1 の1行）に `distance_m`（入口からの m、AP1〜AP11 の範囲に丸める）を保存。保存直後と、以後 `/api/wifi_map` のたびに（＝ダッシュボードを開いている間5秒ごと）各デバイスの推定位置（§6.2）と比べて `device_fire_alerts` を更新する（値が変わった行だけ upsert）。
- 方向の判定（`fire_relation`）: `差 = 火災の距離 − 自分の距離`。`|差| ≤ FIRE_NEAR_M(2m)` → `near`、`差 > 0` → `inward`（奥側）、`差 < 0` → `outward`（入口側）。位置が推定できないデバイスは `unknown`。
- `area_status_v2.fire`（エリアカードの火災チェック）とは**連動しない**。別の機能。

#### ウォッチ側との契約（★ ウォッチ側の実装が必要）
ウォッチは `device_fire_alerts` の **自分の `device_id` の行**を読む（ポーリングか Realtime）。

| 列 | 型 | 意味 |
|---|---|---|
| `fire_active` | bool | 火災位置が出ているか。false なら他の列は null |
| `direction` | text | `inward`=奥側に火災 / `outward`=入口側に火災 / `near`=すぐ近く / `unknown`=自分の位置が不明 |
| `distance_m` | float | 自分から火災までの推定距離[m]（誤差 1〜2m） |
| `message` | text | そのまま表示できる文。例「火災: 奥 約4m」「火災: 手前 約3m」「火災: すぐ近く（約1m）」 |
| `approx` | bool | true=自分の位置がエリア単位でしか分かっていない（距離は目安） |
| `updated_at` | timestamptz | 最終更新 |

テーブル作成 SQL は `supabase/fire_location.sql`（**本番 Supabase で1回実行が必要**。未実行だと火災位置の保存は 500、`/api/wifi_map` は火災なしとして動く）。

---

## 8. 使われていないコード（admin.js 内）

`main` の index.html に対応する DOM が無い／どこからも呼ばれない:
- `saveAreaState` 以外の旧エリア状態系: `saveInstruction`, `loadAreaTable`, `saveAreaTable`（`#areaTableBody` を4列前提で扱う旧版。現在 `#areaTableBody` は `loadAreaMapTable` が使う）
- `loadEntryTable`（`#entryTableBody` は存在しない）
- `app.py`: `update_or_append`, `entry_status_table`, `last_seen_dict`, `threading`/`json`/`time` import、`TABLE_WIFI_REPORTS` は debug でのみ使用

---

## 9. 既知の問題・注意点

### セキュリティ
1. **書き込み系 API の多くが認証なし**: `/api/area_status`, `/api/area`, `/api/area_order`, `/api/user` の POST/DELETE は誰でも叩ける（サーバーは service role key で書くので RLS も効かない）。デバイスが使っている可能性があるので、塞ぐ前にデバイス側の呼び出しを確認すること。
2. 誰でもサインアップでき、メール確認前にログイン扱いになる → 実質誰でも管理画面に入れる。
3. `secret_key` ハードコード（cookie 偽造でログイン扱いにできる）。
4. XSS: `username`, `area_id`, `mac`, プリセット名などを `innerHTML` にエスケープせず埋め込んでいる（認証なしの `POST /api/user` と組み合わさる）。`escapeHtml()` は `admin.js` にあるが、使っているのはマップのポップアップだけ。
5. 例外メッセージをそのままクライアントに返す。

### 正しさ
6. ~~エリアボードとトンネルマップで位置推定アルゴリズムが違う。~~ → 2026-10-10 に `estimate_positions()` に統一（§6.2）。
7. 入退場判定がダッシュボード表示中にしか走らず、レポートの鮮度も見ない（§6.4）。
8. `load_wifi_reports` が全履歴を読む。PostgREST の既定 `max_rows`（通常1000）を超えると、しばらく送信していないデバイスが消える／遅くなる。
9. マップ描画は `/api/wifi_map` の `ap_markers` を使うようになったが、AP位置設定のプルダウンはまだ `admin.js` の `AP_LABELS` を使う。AP の数を変えるなら `app.py` の `AP_LABELS` / `AP_DISTANCES_M` と `admin.js` の `AP_LABELS` を直す。`ap_positions.position` は 0〜5 前提。
10. `GET /api/wifi_map` と `GET /api/entry_management` が DB に書き込む（GET の副作用）。
11. エリア指示値がサーバーで検証されない。
12. `/chkwifi`: `wifi.html` は `wifi_data.items()`（dict 前提・ssid/password）だが渡すのは list で 500 になる。フォームの name も `ssid/password` でルート側は `username/device_id` を読む。
13. `DELETE /api/area` は行ごと消すので、そのエリアの instruction/fire/order も消える。
14. `style.css` のチェックボックス checked 色が赤→緑の順に二重定義され、後勝ちで緑になっている（点滅は赤）。
15. `/logout` は `logged_in` だけ消し `user_email` は残る。Supabase 側の sign_out もしない。

### リポジトリ衛生
16. venv（`api/properioai/`）がコミットされている。`requirements.txt` のバージョンが未固定。
17. `api/ANALYSIS.md` は古い（削除済みファイルに言及）。
18. テーブルのスキーマ（SQL）がリポジトリに無い。

---

## 10. ブランチ（2026-10-10 時点の origin）

`main` 以外: `feature/5-位置の推定`, `feature/6-コードのネーミング見直し`, `feature/7-コードの整合性1`（`tests/test_index.py` あり）, `feature/9-エリアカードの表記`, `feature/10-エリアカードの並び`, `feature/12-テーブルの統合`, `feature/16-404-問題`（main にマージ済み）, `kosen_map`, `kosen_map_b`, `dev/Ryo`, `#34`。
履歴の流れ: SSID/パスワード管理（旧 `index.py`）→ AP 位置ベースの位置推定・トンネルマップ（2026-06〜07）→ 入退場・プリセット・デバイス指示（2026-07）→ ファイル整理と Vercel ルーティング修正（2026-09〜10, `index.py` を `api/app.py` にリネーム）。
