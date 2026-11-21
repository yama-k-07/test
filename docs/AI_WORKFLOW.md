# 生成 AI と一緒に開発する手順

ChatGPT・Gemini・Claude・Copilot など、どの AI でも「どのファイルを、どう書き換えればいいか」を答えられるようにするための手順です。
仕組みはひとつだけ: **AI に最初に [AGENTS.md](../AGENTS.md)（説明書）を読ませる。**
AGENTS.md には「やりたいこと → 編集するファイルと関数」の対応表、守るルール、答え方の形式が書いてあります。

---

## 1. 最初に1回だけ

1. GitHub のリポジトリ https://github.com/yama-k-07/test に招待してもらい、手元に clone する
   ```bash
   git clone https://github.com/yama-k-07/test.git
   ```
2. [AGENTS.md](../AGENTS.md) にざっと目を通す（AI に渡すのと同じもの。人が読んでも分かるように書いてある）
3. 使う AI の種類に合わせて、下の 2-A か 2-B を準備する

---

## 2-0. いちばん手軽: 仕様Q&A ページで聞く

仕様書・開発ガイド・ソースコードを埋め込んだ質問ページがあります。準備なしで、ブラウザから聞けます。

- URL: https://claude.ai/artifact/NhhfAQbG1vPLCMjxxLzQC9 （オーナーから共有してもらう）
- 「質問する」に書いて送ると、Claude が仕様書を読み、必要ならソースを検索して、**ファイル名・関数名・行番号付き**で答える
- 「仕様書を読む」「開発ガイドを読む」タブは、質問機能が使えない環境でも読める
- 質問には、開いた人の Claude の利用枠を使う（最初の質問のときに許可を求められる）
- 中身は作った時点のもの。ページ右上の「元にしたコミット」で版を確認できる

**オーナー向け（ページを最新にする）**: 仕様書やコードを変えたら
```bash
python scripts/build_spec_qa.py
```
で `dist/spec_qa.html` を作り直し、Claude Code に「dist/spec_qa.html を仕様Q&A に公開し直して」と頼む（同じ URL のまま更新される）。

## 2-A. リポジトリを直接読める AI の場合

Codex、Cursor、GitHub Copilot、Claude Code、Gemini CLI、Windsurf など、フォルダやリポジトリを開いて使う AI。

- clone したフォルダを開くだけでよい。多くのツールは `AGENTS.md` を自動で読む
- 自動で読まないツールでは、最初の質問の頭に「AGENTS.md を読んでから答えて」と書く

## 2-B. チャットで使う AI の場合（ChatGPT・Gemini・Claude の Web 版など）

チャット AI はリポジトリを見られないので、**まとめファイル**を作って渡す。

1. まとめファイルを作る（Python が入っていれば OK、追加のインストール不要）
   ```bash
   python scripts/make_ai_context.py
   ```
   → `dist/ai_context.md` ができる（約 200KB。容量を減らしたいときは `--no-css` を付ける）
2. AI の「プロジェクト」機能（ChatGPT のプロジェクト、Gemini の Gem、Claude のプロジェクトなど）を作り、
   - ファイルとして `dist/ai_context.md` をアップロード
   - 指示（カスタム指示）欄に下の文をそのまま貼る
   ```text
   あなたは「まもっち」プロジェクトの開発者です。添付の ai_context.md の先頭にある AGENTS.md を説明書として必ず従ってください。
   変更を頼まれたら、AGENTS.md §3 で編集場所を特定し、§4 のルールを守り、§6 の形式（変更ファイル一覧 → 置き換え前/後 → SPEC.md の更新 → 確認手順）で答えてください。
   添付に無い関数・列・API を前提にせず、分からなければ質問してください。
   ```
   プロジェクト機能が無い AI では、会話の最初にファイルを添付して同じ文を送る
3. **`git pull` したら、まとめファイルを作り直してアップロードし直す**（古いコードのまま答えられてしまうため）

---

## 3. AI への頼み方

### 良い頼み方の例
```text
トンネルマップで、オフラインの作業者の名前の横に「最終通信から何分」を出したい。
どのファイルのどこを、どう変えればいい？
```
```text
火災の通知で、ウォッチに出る文を「火災: 奥 約320m」から「奥 320m 先で火災」に変えたい。
ウォッチとの約束（AGENTS.md §4）に触れるなら先に教えて。
```
```text
ESP32 AP の heartbeat に、基板の温度を追加で送りたい。ファームウェアとサーバーの両方の変更を教えて。
```

### コツ
- **何をしたいか**（画面で何が起きてほしいか）を書く。「app.py を直して」より「〜を表示したい」の方が正しい場所を探してくれる
- エラーが出たら、**エラー文と、そのとき何をしたか**をそのまま貼る
- 答えに出てきた関数名で実際のファイルを検索し、**「置き換え前」が本当にあるか確かめてから**書き換える（無ければ AI に「その関数は無い」と返す）
- 秘密情報（`.env` の中身、Supabase のキー、`config.h` のパスワードやトークン）はチャットに貼らない

---

## 4. 編集から本番反映までの流れ

`main` に入ったものは Vercel で**自動で本番に出ます**。直接 `main` には書かず、必ずブランチ → プルリクエスト（PR）で入れます。

### 4-1. 始める前に（毎回）
```bash
git switch main
```
```bash
git pull
```
- 最新を取ってから始める（古いまま書くと、ほかの人の変更とぶつかる）
- チャット AI を使う人は、ここで `python scripts/make_ai_context.py` を実行して、まとめファイルを作り直してアップロードし直す（§2-B）

### 4-2. ブランチを作る
```bash
git switch -c feature/やること
```
- 名前は内容が分かるように（例 `feature/map-offline-minutes`、`fix/fire-message`）
- 1つのブランチには1つの目的だけ。関係ない変更を混ぜない

### 4-3. AI に聞いて書き換える
- §3 の頼み方で聞く。答えの「置き換え前」が本当にファイルにあるか確かめてから書き換える
- AI が「SPEC.md の更新」を挙げたら SPEC.md も直す。関数名を変えた・ファイルを足したら AGENTS.md §3 の表も直す
- 仕様書や関数名を変えたら `python scripts/build_spec_qa.py` も実行しておく（Q&A ページの作り直し。公開し直しはオーナー）

### 4-4. 手元で確かめる
- `api/.env` を置いて `cd api && python app.py` → http://localhost:5000（AGENTS.md §5）
- **`.env` は本番と同じ Supabase を指していることが多い。** 手元で押したボタンも本番のデータを変える。指示・火災・削除のボタンを試すときは、本物のウォッチに届くことを忘れずに
- ウォッチが無くても、§5 のデモで作業者を歩かせて確かめられる

### 4-5. コミットして PR を作る
```bash
git add 変えたファイル
```
```bash
git commit -m "何をなぜ変えたか（日本語で OK）"
```
```bash
git push -u origin feature/やること
```
- push したら GitHub に出る「Compare & pull request」から PR を作る（`gh` コマンドが使えるなら `gh pr create`）
- PR の説明には「何を変えたか」「どう確かめたか」「SQL の実行が要るか」を書く
- **`api/.env`・`config.h`・`configs/*.h`（パスワードやトークン入り）は絶対にコミットしない**（.gitignore で除いてあるが、`git add .` の前に `git status` で確かめる）

### 4-6. マージと本番反映
- PR はオーナー（またはもう1人）が見てからマージする。自分の PR を自分ですぐマージしない
- **SQL の変更がある PR は、マージ前に Supabase の SQL Editor で実行する**（`supabase/*.sql`）。順番が逆だと、本番でエラーになることがある
- マージすると 1〜2 分で本番に出る。本番の画面を Ctrl+F5 で開き直して確かめる
- 同じファイルを2人が同時に変えていると、PR に「conflict（衝突）」と出る。そのときは `git pull origin main` で取り込み、ぶつかった所を直してから push し直す（分からなければ AI に「この conflict の直し方」とファイルの該当部分を貼って聞く）

### 4-7. ウォッチ・ESP32 に関わる変更
- `wifi_reports`・`wifi_reports_v2`・`ble_reports`・`device_instructions` などの列や値（AGENTS.md §4 の「ウォッチとの約束」）を変えるときは、**PR の前にウォッチ担当と相談する**
- ESP32 のファームウェアを変えたら、実機に書き込んで動くことを確かめてから PR にする（カメラは `python scripts/flash_camera.py <カメラID> <ポート>`）

---

## 5. デモ（ウォッチ無しで動かす）

`scripts/demo_watch.py` が、ウォッチの代わりに「トンネルを歩く作業者」のスキャン結果を Supabase に入れ続けます。マップ・区間の指示・位置推定の比較が、本物のウォッチと同じように動きます。

**注意: `api/.env` の Supabase（ふつうは本番）に書き込みます。** デモ用の装置 ID は `demo-01`、`demo-02`… で、終わったら `--cleanup` でまとめて消せます。

1. まず書き込まずに中身を見る（20 秒で終わる）
   ```bash
   python scripts/demo_watch.py --dry-run
   ```
2. デモを始める（2 人が 10 分歩く。Ctrl+C で止める）
   ```bash
   python scripts/demo_watch.py
   ```
   - 人数・時間: `--workers 3 --minutes 5`
   - Wi-Fi だけの場面: `--no-ble`
   - 方式の比べ方も見せる: `--auto-eval`（15 秒ごとに「本当の位置」と ①〜⑥ の推定を記録。「位置推定の方式」の表に方式ごとの誤差がたまる）
3. ダッシュボードを開く。`demo-01` などがマップ上を動く。区間に指示を出すと、その区間にいるデモの作業者にも届く
4. 終わったら必ず消す
   ```bash
   python scripts/demo_watch.py --cleanup
   ```
   `wifi_reports`・`wifi_reports_v2`・`ble_reports`・`device_instructions`・`device_segment_state`・`entry_current`・`entry_log`・`position_eval` の、`demo-` で始まる行だけを消す（本物の装置の行は消さない）

- 電波はシミュレーション（距離で弱くなる式＋ばらつき）なので、実際のトンネルとは違う。方式の良し悪しは、最後は現地で記録して決める
- AP の配置は、画面の「AP位置設定」と「ESP32 AP」表から読む（fw が `ble-` の ESP32 は BLE ビーコン、それ以外は Wi-Fi AP）。距離が入っていない AP は使わない

---

## 6. ESP32 を足す（ビーコン・カメラ）

新しい ESP32 を足すときは**コードを変えない**。ファームウェアを書き込んで、ダッシュボードで距離を入れるだけ。PR も要らない。

### 6-1. 最初に1回だけ
1. リポジトリを clone（または `git pull` で最新に）
2. Arduino IDE の「ボードマネージャ」で **esp32 by Espressif Systems** を入れる
3. オーナーから次を**チャット以外で**受け取る（メッセージやメールに残さない方法で）
   - `AP_SHARED_TOKEN`（ESP32 がサーバーに通信するためのトークン）
   - 現場のインターネット用 Wi-Fi の名前とパスワード

### 6-2. 位置の目印（BLE ビーコン）を足す — `firmware/esp32s3_ap/`
1. `firmware/esp32s3_ap/config.example.h` をコピーして、同じフォルダに `config.h` を作り、書き換える

   | 項目 | 書くこと |
   |---|---|
   | `AP_LABEL` | 表示名。英数字 17 文字まで（例 `A250` = 250m 地点）。**ほかの ESP32 と重ねない** |
   | `AP_DISTANCE_M` | 入口からの距離 [m]（初期値。あとで画面で直せる） |
   | `BLE_TX_POWER` | **全台同じ値**（既定の +3dBm のまま） |
   | `UPLINK_SSID` / `UPLINK_PASSWORD` / `AP_TOKEN` | 6-1 で受け取った Wi-Fi とトークン |

2. Arduino IDE で書き込む
   - ボード: **ESP32S3 Dev Module**
   - Partition Scheme: **Huge APP (3MB No OTA/1MB SPIFFS)**（BLE と Wi-Fi で標準の領域をほぼ使い切るため）
3. シリアルモニタ（115200bps）で確かめる
   - `[BLE] name=MAMOTCHI-A250  address=…` … ビーコンが動いている（`address` が位置推定で使う MAC）
   - `[HB] POST … -> 200` … サーバーに登録された
4. ダッシュボードの「**ESP32 AP**」欄（設定の下）に 30 秒ほどで行が出る。**入口からの距離**を確かめて「保存」。距離が空の行は位置推定に使われない
5. 設置した場所に立ち、マップの位置が合うか確かめる

**インターネットにつなげない場所の ESP32**: `UPLINK_SSID` を `""` のまま書き込み、シリアルに出た `address=…` を「ESP32 AP」欄の下の「**手で追加**」で登録する（種類は BLE、距離も入れる）。

### 6-3. カメラを足す — `firmware/esp32cam_uplink/`
1. CameraWebServer からコピーするファイル（`board_config.h`・`camera_pins.h`・`partitions.csv`・`app_httpd.cpp`・`camera_index.h`）がフォルダにあるか確かめる。無ければ `firmware/esp32cam_uplink/README.md` の手順で用意する（Git には入っていない）
2. 共通の設定 `configs/common.h` が無ければ、`configs/common.example.h` をコピーして作る（Wi-Fi・トークンなど）
3. `configs/camera.example.h` をコピーして `configs/<カメラID>.h` を作り（例 `cam-03.h`）、4つだけ書き換える

   | 項目 | 書くこと |
   |---|---|
   | `CAMERA_ID` | ファイル名と同じ。英数字・`_`・`-` で 17 文字まで。**ほかのカメラと重ねない** |
   | `CAMERA_LABEL` | 画面に出る名前 |
   | `CAMERA_DISTANCE_M` | 入口からの距離 [m]（初期値） |
   | `LOCAL_AP_SSID` | 近くで見るための Wi-Fi の名前。ほかのカメラと重ねない |

4. 書き込む（リポジトリのいちばん上で。ポートは `--list` で確かめる）
   ```bash
   python scripts/flash_camera.py --list
   ```
   ```bash
   python scripts/flash_camera.py cam-03 COM9
   ```
5. ダッシュボードの「カメラ」欄と「ESP32 AP」欄に出るので、距離を入れる（どちらの欄で入れても同じ値になる）。「映像を見る」で映るか確かめる
6. **基板にカメラ ID のシールを貼る**（どのボードがどのカメラか、見た目では分からないため）

**映像の見分け方**: どのカメラの映像かは **カメラ ID（`CAMERA_ID`）** で決まる。MAC（BLE アドレス）は、カメラと「ESP32 AP」欄の行（位置の目印）を結び付けるだけに使う。同じカメラ ID のボードが2台あると、映像が上書きし合って混ざる（`flash_camera.py` は設定ファイルどうしの重なりは止めるが、別の PC で同じ ID を使った場合は防げない）。実物の ID は、USB でつないだときのシリアルの最初の行 `=== MAMOTCHI ESP32 camera fw … (cam-03) ===` で分かる。

### 6-4. 気をつけること
- **`config.h` と `configs/*.h` はコミットしない**（パスワードとトークン入り。`.gitignore` で除いてあるが、`git status` で確かめる）。トークンもチャットに貼らない
- 表示名・カメラ ID・近くで見る Wi-Fi の名前は、ほかの ESP32 と重ねない
- 取り外した ESP32 は「ESP32 AP」欄で「使わない」にするか「削除」する（そのままだとマップに停止中の灰色の × が残る）
- ビーコンが位置推定に効くのは、ウォッチが BLE を送るようになってから（[WATCH_SCAN_REPORTS.md](./WATCH_SCAN_REPORTS.md)）
- ファームウェアそのもの（`.ino`）を直したときは、普通の変更と同じく §4 の流れ（ブランチ → PR）で入れる

---

## 7. なぜこのやり方なのか

- `AGENTS.md` は多くの AI 開発ツールが共通で読むファイル名。1か所に書けば、どの AI にも同じ説明が届く
  （Claude Code 用の `CLAUDE.md` も中身は AGENTS.md を読み込むだけにしてある）
- チャット AI はリポジトリを見られないので、説明書・仕様・ソースを1つにまとめたファイルを渡す
- 説明書には「機能 → ファイル → 関数名」で書いてある。行番号は変わるが関数名は変わりにくいので、コードが更新されても案内が使える
