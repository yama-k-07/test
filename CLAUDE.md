# CLAUDE.md

まもっち（Wi-Fi AP による作業者位置推定・入退場・避難指示ダッシュボード）。Flask + Supabase、Vercel デプロイ。
**現状仕様は [SPEC.md](./SPEC.md)。** 作業前に読み、コードを変えたら該当箇所を直す。`api/ANALYSIS.md` は古いので参照しない。

## どこに何があるか
- サーバー: `api/app.py` だけ（全ルート・位置推定・入退場判定）
- 画面: `api/templates/index.html`（ダッシュボード）、`api/templates/login.html`
- 画面ロジック: `api/static/admin.js` だけ。見た目: `api/static/style.css`
- `*_deprecated.*`, `api/public/`, `api/static/script.js`, `templates/sql_test.html`, `api/properioai/`（venv）は使われていない。編集対象にしない

## 変更時の注意
- **デバイス（Galaxy Watch）側のコードはこのリポジトリに無い。** `wifi_reports` / `latest_wifi_reports` / `area_status_v2` / `device_instructions` の列名・値、および認証なし API（`/api/area_status` など）の形は、デバイスとの契約の可能性があるので勝手に変えない。変えるなら先にユーザーに確認する。
- 火災位置機能（SPEC §7.7）のテーブルは `supabase/fire_location.sql`。`device_fire_alerts` はウォッチが読む契約なので列名・値（`inward/outward/near/unknown`）を勝手に変えない。
- 位置推定は `app.py` の `estimate_positions()` に一本化（マップもエリアボードも）。定数と精度の根拠は SPEC §6.2。AP の距離は `AP_DISTANCES_M`。`AP_LABELS` は `admin.js`（AP位置設定のプルダウン）にもあるので片方だけ変えない。
- `MAC01_WEIGHT = 0.8` は「mac01 が最も強い AP」というウォッチの仕様が前提。
- デバイス指示の値 `none/wait/inward/outward` は `app.py` の `DEVICE_INSTRUCTIONS` と `admin.js` の `DEVICE_INSTRUCTION_LABELS` の両方にある。
- 定期更新は 5 秒ポーリング＋ `last*Sig` による差分スキップ＋ `isEditing` ガード。新しいセクションを足すときもこのパターンに合わせる（`DOMContentLoaded` と `setInterval` の両方に登録）。
- 見た目の調整は `style.css` 末尾の「見やすさ調整」ブロックにまとめてある（方針は SPEC §7.4）。ドット調フォント・ピクセル枠・ロゴ（`banner.png`）は変えない。`#tunnelMap` の CSS 高さと `renderTunnelMap` の `H` は揃える。
- `GET /api/wifi_map` と `GET /api/entry_management` は DB に書き込む（SPEC §6）。呼び出し回数を変えると挙動が変わる。
- Supabase の Python クライアントは `supabase.table(...).select/upsert/delete().eq(...).execute()` 形式。API は推測せず、インストール済みパッケージか公式ドキュメントで確認する。

## 確認方法
- ローカル: `api/.env` に `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` / `SUPABASE_ANON_KEY` を置き `cd api && python app.py` → http://localhost:5000
  - `.env` は本番と同じ Supabase を指すことが多い。**ローカルで操作しても本番データが変わる**ので、書き込み系の動作確認は事前にユーザーに確認する。
- 本番: https://test-fawn-iota-73.vercel.app/ （`/test-deploy` でデプロイ確認。ダッシュボードはログイン必須）
- 自動テストは無い。
