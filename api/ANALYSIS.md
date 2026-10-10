# api ディレクトリ 解析ドキュメント

> **このドキュメントは古いです（2026-08 時点）。** ここに出てくる `index.py`, `index_v2.py`, `M5emu.py` などは 2026-09 の整理で削除済みです。現状の仕様はリポジトリ直下の [SPEC.md](../SPEC.md) を見てください。

このドキュメントは `api/` ディレクトリ配下のコードを読み解いた結果をまとめたものです。

## 1. このプロジェクトは何か

Wi-Fi の電波状況（どの AP と接続しているか）を使って、**人（デバイス）の屋内位置を推定し、入退場を管理する Flask 製 Web アプリ**です。`app.secret_key = 'mamotchi_secret_key_pixel'` から、社内では「まもっち（mamotchi）」と呼ばれているシステムと推測されます。

大まかな仕組み：

1. 各利用者が持つ M5Stack などのデバイスが、接続している Wi-Fi アクセスポイント（AP）の MAC アドレスなどを一定間隔でサーバーに送信する。
2. サーバー（Flask + Supabase）がそのレポートを保存し、AP の物理配置（`ap_positions`）と照らし合わせてデバイスのおおよその位置（エリア）を計算する。
3. 管理画面（`/index`）でリアルタイムの位置マップや入退場ログを確認できる。

バックエンドの永続化には [Supabase](https://supabase.com/)（PostgreSQL + REST API のBaaS）を使用しています。

## 2. ファイル構成と役割

| ファイル | 役割 |
|---|---|
| `app.py` | **現行の本番アプリ本体。** 認証、位置推定、入退場管理などすべてのAPIを持つ最新版。 |
| `index.py` | `app.py` の旧バージョン（SSID/パスワード管理ベース）。開発途中の実装で、現在は使われていないと思われる。 |
| `index_v2.py` | `index.py` をさらに整理した中間バージョン。これも旧実装。 |
| `M5emu.py` | 実機（M5Stack）の代わりにサーバーへ `alive_check` リクエストを送り続ける**エミュレータ**。動作確認用。 |
| `M5test.json` | `M5emu.py` が読み込む、エミュレートするデバイス一覧の設定ファイル。 |
| `test.py` | `/api/<path>` に何が来ても応答するだけの、Flask ルーティングの疎通確認用スクリプト。 |
| `test_form.py` | Supabase への insert 動作を確認するための簡易フォームアプリ。 |
| `area_order.json` | エリア（入口〜600mなど）の並び順のサンプルデータ。 |
| `area_table.json` | エリアIDとゲートウェイ（AP）の対応表のサンプルデータ。 |
| `ssid_table.json` | SSIDとパスワードの対応表のサンプルデータ（旧実装 `index.py` 系で使用）。 |
| `templates/` | Jinja2 テンプレート（ログイン画面・管理画面・Wi-Fi設定画面など）。`*_deprecated.html` は使われなくなった旧画面。 |
| `static/` | JS/CSS/画像。`admin.js`（1300行超）が管理画面のロジック本体。`script.js` は旧UI用。 |
| `public/templates/index.html` | 別系統の index.html（用途は要確認）。 |
| `properioai/` | Python の仮想環境（venv）。アプリのコードではなく実行環境。 |

## 3. `app.py` の詳細（現行アプリ）

### 3.1 使用テーブル（Supabase）

- `area_status_v2` … エリアごとの状態（`bssid`, `area_id`, `instruction`, `fire`, `area_order` など）
- `user` … ユーザー名とデバイスIDの対応
- `wifi_reports` … デバイスからのWi-Fi接続レポートのログ（全件）
- `latest_wifi_reports` … 各デバイスの最新レポートのみを持つビュー（デバッグ用途）
- `ap_positions` … AP（MACアドレス）ごとの物理的な配置位置
- `ap_position_presets` … AP配置のプリセット（名前付きで保存・呼び出し）
- `device_instructions` … デバイスへの指示（`none`/`wait`/`inward`/`outward`）とレポートON/OFF状態
- `entry_current` … 各デバイスの現在の入退場ステータス
- `entry_log` … 入場・退場のイベントログ

### 3.2 認証

- `/`（GET/POST）でログイン・サインアップを実施。Supabase Auth（`sign_in_with_password` / `sign_up`）を利用し、Flaskの`session`にログイン状態を保持。
- `login_required` デコレータで管理画面・一部APIを保護。

### 3.3 主なAPIエンドポイント

| メソッド/パス | 概要 |
|---|---|
| `POST/GET /api/area_status` | エリアの状態を更新・取得 |
| `POST/GET/DELETE /api/user` | ユーザー（デバイス所有者）の登録・取得・削除 |
| `POST/GET/DELETE /api/area` | エリアマスタの登録・取得・削除 |
| `GET/POST/DELETE /api/ap_positions` | AP配置の取得・保存・削除（ログイン必須） |
| `GET/POST/DELETE /api/ap_presets` | AP配置プリセットの取得・保存・削除（ログイン必須） |
| `GET /api/wifi_map` | **位置推定のメイン処理。** 各デバイスの接続AP位置から相対位置(`ratio`)とエリアを算出し、オンライン状況とあわせて返す（ログイン必須） |
| `GET/POST /api/device_instructions` | デバイスへの指示（前進/後退待機など）とレポート要否の設定・取得 |
| `GET/POST /api/area_order` | エリアの並び順の取得・保存 |
| `GET /api/entry_status` | 現状のデバイスとエリアの対応をシンプルに返す（位置推定・簡易版） |
| `GET /api/entry_management` | 入退場ステータスを最新化して当日分を返す（ログイン必須） |
| `GET /api/entry_log` | 当日の入退場イベントログを返す（ログイン必須） |
| `GET /api/debug/wifi_map` | 各種テーブルの生データとロード結果を突き合わせて返すデバッグ用 |
| `GET /test-deploy` | デプロイ確認用の疎通エンドポイント |

### 3.4 位置推定ロジック（`get_wifi_map` / `do_entry_status_update`）

- デバイスが接続している2つまでのAP（`mac01`, `mac02`）の配置位置（0〜5の6段階、`AP_COUNT=6`）から、0〜1の比率 `ratio` を算出。
- `ratio` とエリア数からエリアインデックスを計算し、どのエリアにいるかを推定。
- `is_recent()` で直近60秒以内に通信があったデバイスを「オンライン」と判定。
- `do_entry_status_update()` は、デバイスが `ap_positions` に登録されたいずれかのAPと接続していれば「入場中」、どれとも繋がっていなければ「退場」とみなし、`entry_current`（現在状態）と`entry_log`（履歴）を更新する。

### 3.5 補足・気になる点（コード中のコメントから）

- `#いる?`（`update_or_append`関数）、`#使ってる？`（`admin_wifi`ルート）といった開発者自身の疑問コメントがあり、未整理・要検証の箇所が残っている。
- `app.secret_key` がハードコードされており、本番運用では環境変数化が望ましい。

## 4. 旧バージョン（`index.py` / `index_v2.py`）との違い

`index.py`・`index_v2.py` は `app.py` に統合される前の初期実装で、以下の点が異なります。

- 位置推定・入退場管理の機能がない（`entry_status_table` はローカルメモリのみで管理する簡易版）。
- Wi-Fi管理が「AP位置」ではなく「SSID/パスワード」ベース（`access_point`, `area`, `area_statuses`, `area_order` テーブルを使用）。
- `index.py` の方が `index_v2.py` より新しく、`login_mock` エンドポイントや `area_order` API が追加されている（`index_v2.py`には無い）。

## 5. 補助スクリプト

- **`M5emu.py`**: `M5test.json` に定義された複数の仮想デバイスから、`interval_sec` 間隔で `/api/alive_check` にPOSTし続ける負荷確認・動作確認用スクリプト（※ `app.py` 側に `/api/alive_check` の実装は見当たらないため、現状は404になる可能性がある＝旧APIとの整合性が取れていない状態）。
- **`test.py`** / **`test_form.py`**: Flaskルーティングや Supabase 接続を単体で試すための最小構成スクリプト。本番アプリとは独立している。

## 6. まとめ

`api/` は、Wi-Fi電波の接続状況からデバイス（＝人）の位置をリアルタイムに推定し、エリア管理・入退場管理を行う Flask + Supabase 製バックエンドです。`app.py` が現行の本体で、`index.py`/`index_v2.py` はその前身にあたる旧実装、`M5emu.py`/`test.py`/`test_form.py` は開発・検証用の補助スクリプトという構成になっています。
