# AGENTS.md — まもっち 開発ガイド（AI・人間 共通）

このファイルは、ChatGPT・Claude・Gemini・Copilot・Cursor・Codex など**どの生成 AI にも最初に読ませる**説明書です。
「何を直したいか」から「どのファイルのどこを、どう書き換えるか」を引けるようにしてあります。
詳しい仕様は [SPEC.md](./SPEC.md)。コードを変えたら SPEC.md の該当箇所も直すこと。`api/ANALYSIS.md` は古いので参照しない。

---

## 1. このシステムは何か

トンネル内の作業者が身に着けた **Galaxy Watch** が、近くの Wi-Fi AP の BSSID（電波の強い順に `mac01` / `mac02`）を Supabase に送る。
**Flask サーバー**がそれを AP の設置距離と照らして位置を推定し、**管理ダッシュボード**で位置の表示・避難指示・個別指示・火災位置の通知・入退場管理を行う。
AP は既設の6台（AP1=入口0m 〜 AP11=500m、100m 間隔）に加え、**ESP32-S3 で自作した AP** を増設できる。

```
Galaxy Watch ──(mac01, mac02)──> Supabase: wifi_reports
                                     │
                     Flask (api/app.py) が位置推定・入退場判定・火災の方向計算
                                     │
          ダッシュボード (index.html + admin.js)   ウォッチ ← device_instructions / device_fire_alerts
ESP32-S3 AP ──heartbeat──> /api/ap_heartbeat ──> Supabase: ap_nodes
```

- 本番: https://test-fawn-iota-73.vercel.app/ （Vercel。`main` に入ると自動デプロイ）
- リポジトリ: https://github.com/yama-k-07/test
- 技術: Python 3 + Flask（1ファイル）／ Supabase（Postgres・Auth・Realtime）／ 素の JavaScript ＋ Bulma ＋ Canvas ／ Arduino-ESP32

---

## 2. ファイル地図（編集するのはこれだけ）

| ファイル | 役割 |
|---|---|
| `api/app.py` | **サーバーのすべて**。全 API・位置推定・入退場判定・火災通知・ESP32 AP 受付 |
| `api/templates/index.html` | ダッシュボードの HTML（セクションの並び・ボタン・表の見出し） |
| `api/templates/login.html` | ログイン画面（HTML と JS が1ファイル） |
| `api/static/admin.js` | **ダッシュボードの動きのすべて**。API 呼び出し・表の描画・トンネルマップ（Canvas） |
| `api/static/style.css` | 見た目。末尾の「見やすさ調整」ブロック以降が現行の上書き |
| `supabase/*.sql` | 追加したテーブルの定義（Supabase の SQL Editor で実行） |
| `firmware/esp32s3_ap/` | ESP32-S3 AP のファームウェア（`.ino`、`config.example.h`、README） |
| `SPEC.md` | 現状仕様（データモデル・API 一覧・計算式・画面の仕組み） |
| `vercel.json`（`api/` 内）, `requirements.txt` | デプロイ設定と Python 依存 |

**触らないもの**: `*_deprecated.*`、`api/public/`、`api/static/script.js`、`api/templates/sql_test.html`、`api/templates/wifi.html`、`api/properioai/`（コミットされた venv）、`firmware/**/config.h`（パスワード入り・Git 管理外）。

---

## 3. やりたいこと → 編集する場所

関数名で探すこと（行番号は変わる）。`app.py` は `def 関数名`、`admin.js` は `function 関数名` で検索する。

### 画面（ダッシュボード）

| やりたいこと | 編集する場所 |
|---|---|
| セクションの並び・見出し・説明文を変える | `index.html`（`<section class="box">` 単位） |
| 新しいセクションを足す | `index.html` に器（`id` 付き）→ `admin.js` に `loadXxx()` を作り、`DOMContentLoaded` と `setInterval` の両方に登録（§4 の更新パターン） |
| エリアカードの見た目・項目 | `admin.js` の `createAreaCard`、色は `style.css` の `.areacard[data-instruction=...]` |
| エリア指示の選択肢・表示名 | `admin.js` の `AREA_INSTRUCTION_LABELS` と `instructionOptions`（値を変える場合はウォッチと要相談） |
| トンネルマップの描き方（色・大きさ・ラベル） | `admin.js` の `renderTunnelMap`（`const H`・色定数 `C_*` もここ）。高さを変えたら `style.css` の `#tunnelMap` の `height` も同じ値に |
| 作業者アイコンのクリック・ポップアップ | `admin.js` の `initTunnelMapInteraction` / `findWorkerAt` / `openWorkerPopup` |
| 個別指示（待て・奥へ…）の選択肢 | `admin.js` の `DEVICE_INSTRUCTION_LABELS` と `app.py` の `DEVICE_INSTRUCTIONS`（両方。値の追加はウォッチと要相談） |
| 火災位置の指定・解除・炎の絵 | `admin.js` の `toggleFireMode` / `placeFireLocation` / `clearFireLocation` / `drawFireMarker` / `updateFireStatus` |
| 入退場の表 | `admin.js` の `loadEntryManagement` / `renderEntryCurrentTable` / `renderEntryLogTable` |
| AP位置設定・プリセット | `admin.js` の `loadApPositionsTable` / `saveApPositionsTable` / `loadApPreset` / `saveApPreset`。選択肢は `AP_LABELS` / `AP_POSITION_DISTANCES_M` |
| ESP32 AP の表 | `admin.js` の `loadApNodesTable` / `saveApNode` / `deleteApNode` |
| ユーザー・エリア割当の表 | `admin.js` の `loadUserTable` / `saveUserTable`、`loadAreaMapTable` / `saveAreaMapTable` |
| 色・文字サイズ・余白 | `style.css` 末尾の「見やすさ調整」ブロック。状態色は `--state-*` |
| ログイン画面 | `login.html`（送信は `POST /` に `{email, password, mode}`） |

### サーバー（`api/app.py`）

| やりたいこと | 編集する場所 |
|---|---|
| 位置推定の計算を変える | `estimate_positions`（全体の流れ）、`report_distance_m`（1回分の距離、`MAC01_WEIGHT`）、`smooth_distance_m`（平滑化）、定数 `SMOOTHING_*` / `OUTLIER_SPACINGS` |
| AP の距離・台数を変える | 既設6台: `AP_LABELS` / `AP_DISTANCES_M`（`admin.js` の同名定数も）。ESP32 AP: 画面の「ESP32 AP」表で設定（コード変更不要） |
| AP の距離の出どころ・トンネルの両端・間隔 | `class ApMap` と `load_ap_map` |
| エリアの決め方 | `build_area_layout` / `area_for_ratio` / `area_centers_m`、`estimate_positions` 内の優先順位 |
| 火災の方向・距離・文言（ウォッチに出る文） | `fire_relation`（文言）、`build_fire_alerts`、定数 `FIRE_NEAR_SPACINGS` / `FIRE_DISTANCE_STEP_M` |
| 入場・退場の判定 | `do_entry_status_update` |
| オンライン判定の秒数 | `ONLINE_THRESHOLD_SEC`（ウォッチ）、`AP_NODE_ONLINE_SEC`（ESP32 AP） |
| API を追加する | 既存の `@app.route` を真似る。管理画面用はログイン必須の `@login_required` を付ける。SPEC.md §5 の API 表に追記 |
| テーブルを追加する | `supabase/新しい名前.sql` を作り、`app.py` 冒頭に `TABLE_XXX = "..."` を足す。SPEC.md §4 に追記 |
| ESP32 AP からの受付 | `ap_heartbeat`（トークン認証）、`handle_ap_nodes` |

### ESP32-S3 ファームウェア（`firmware/esp32s3_ap/`）

| やりたいこと | 編集する場所 |
|---|---|
| 1台ごとの設定（表示名・距離・チャンネル・出力・Wi-Fi） | `config.h`（`config.example.h` をコピーして作る） |
| SSID の付け方・送信出力の扱い | `esp32s3_ap.ino` の `startAccessPoint` / `applyTxPower` |
| heartbeat の内容・間隔 | `esp32s3_ap.ino` の `sendHeartbeat` / `HEARTBEAT_INTERVAL_MS`（サーバー側 `ap_heartbeat` と項目を揃える） |

---

## 4. 守るルール

- **ウォッチ（Galaxy Watch）側のコードはこのリポジトリに無い。** 次の列名・値・API の形はウォッチとの約束なので、**勝手に変えない**（変えるなら先に人間に確認）:
  - テーブル `wifi_reports` / `latest_wifi_reports` / `area_status_v2` / `device_instructions` / `device_fire_alerts`
  - `device_fire_alerts.direction` の値 `inward / outward / near / unknown`
  - ログイン不要の API（`/api/area_status`、`/api/user`、`/api/area`、`/api/area_order`、`/api/entry_status`）
- 位置推定は `estimate_positions` に**一本化**されている（マップもエリアボードも同じ結果）。別の計算を足さない。
- `MAC01_WEIGHT = 0.8` は「mac01 が最も強い AP」というウォッチの仕様が前提。
- AP の距離と表示名は `app.py` と `admin.js` の**両方**にある（`AP_LABELS` / `AP_DISTANCES_M` ↔ `AP_LABELS` / `AP_POSITION_DISTANCES_M`）。片方だけ変えない。同様に指示の値（`DEVICE_INSTRUCTIONS` ↔ `DEVICE_INSTRUCTION_LABELS`）。
- MAC の比較は `norm_mac` で大文字に揃えてから行う（Android は小文字、ESP32 は大文字）。
- **画面の定期更新パターン**: 5 秒ポーリング＋前回と同じ内容なら再描画しない（`last*Sig`）＋入力中は更新しない（`isEditing`）。新しい表もこれに合わせる。
- 画面に文字列を入れるときは `escapeHtml()` を通す（`innerHTML` に生で入れない）。
- チェックボックスは全体の仕組みで「行が赤く点滅（火災表示）」になる。火災以外のオン/オフはプルダウンにする。
- 見た目の調整は `style.css` 末尾のブロックで行う。**ドット調フォント・ピクセル枠・ロゴ（`banner.png`）は変えない。**
- `GET /api/wifi_map` と `GET /api/entry_management` は表示用だが DB にも書き込む（SPEC §6）。呼び出し回数を変えると挙動が変わる。
- Supabase の Python クライアントは `supabase.table(...).select/insert/upsert/update/delete().eq(...).execute()` の形。**ライブラリの API は推測しない**（公式ドキュメントで確認）。Arduino-ESP32 も同じ。
- 秘密情報（`.env`、`config.h`、トークン、パスワード）はコードやチャットに貼らない。

---

## 5. 確認方法

- ローカル: `api/.env` に `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY`（ESP32 を試すなら `AP_SHARED_TOKEN` も）を置き、`cd api && python app.py` → http://localhost:5000
  - `.env` は本番と同じ Supabase を指すことが多い。**ローカルで操作しても本番データが変わる。**
- 本番: https://test-fawn-iota-73.vercel.app/ （`/test-deploy` が `DEPLOYED-V3-POST-OK` を返せばデプロイ済み。ダッシュボードはログイン必須）
- 自動テストは無い。変更後は該当画面を実際に操作して確かめる。
- ESP32: Arduino IDE（ボード: ESP32S3 Dev Module）でコンパイル・書き込み。手順は `firmware/esp32s3_ap/README.md`。

---

## 6. AI への依頼に答えるときの形式

このリポジトリについて変更を頼まれた AI は、次の形で答えること。

1. **方針**: 何をどう変えるかを 2〜3 行で。§4 のルールに触れる変更なら、その旨と確認事項を先に書く。
2. **変更するファイルの一覧**: `パス — 何を変えるか` を箇条書き。
3. **ファイルごとの変更内容**: 関数・ブロック単位で「置き換え前（元のコードをそのまま引用）」と「置き換え後」を示す。新しい関数は「どの関数の後ろに置くか」を書く。ファイル全体の書き直しはしない。
4. **SPEC.md の更新箇所**: 節番号と追記・修正する文。
5. **確認手順**: 画面のどこで何をすれば動作を確かめられるか。DB の変更が要るなら実行する SQL。

渡されたコードに無い関数・列・API を前提にしないこと。分からないときは推測せず、必要なファイルや情報を質問すること。
