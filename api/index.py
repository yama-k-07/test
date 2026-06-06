from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from functools import wraps
import threading
import json
import os
import time

SSID_TABLE_PATH = "ssid_table.json"
AREA_ORDER_PATH = "area_order.json"
AREA_TABLE_PATH = "area_table.json"

app = Flask(__name__)
app.secret_key = 'mamotchi_secret_key_pixel' # セッション管理に必要

#supabase API Key
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

# === テーブル定義（リストとして管理） ===
# { デバイスID(8桁), area_id }
entry_status_table = [{"device_id": "gfaghear", "area_id": "1", "username": "AA"},
                      {"device_id": "areageag", "area_id": "2", "username": "BB"},
                      {"device_id": "bgfehtre", "area_id": "2", "username": "CC"},
                      {"device_id": "qgrgaadf", "area_id": "1", "username": "DD"}]

# { エリアID, 指示(waiting か evacuate_exit か evacuate_upwind / none(正常時) / alert(通報通知時)), 通報元(火災場所)かどうか }
# リスト順序を配置に用いる, area_idはssidの関連付けのみに使う
area_status_table = [{"area_id": "1", "instruction": "evacuate_exit", "fire": False},
                     {"area_id": "2", "instruction": "waiting",       "fire": True}]

# { エリアID, SSID, パスワード }
# area_idの特定に使う
# アクセスポイントリストに変換して使う
# ssid_table = [{"area_id": "1", "ssid": "Ando", "password": "dsno3946"},
#               {"area_id": "2", "ssid": "k",    "password": "rancer454545"}]
ssid_table = [{"ssid": "Ando", "password": "dsno3946"},
              {"ssid": "k",    "password": "rancer454545"}]

area_table = [{"area_id": "1", "gateway": "192.168.1.10"},
              {"area_id": "2", "gateway": "192.168.1.11"}]

# === デバイスごとの最終アクセス時刻 ===
last_seen_dict = {}  # device_id -> UNIX timestamp

# === SSIDテーブルの読み書き ===
def load_ssid_table():
    global ssid_table
    try:
        f = supabase.table("access_point").select("*").execute()
        ssid_table = [
            {"ssid": row["ssid"], "password": row["password"]} 
            for row in f.data
        ]
    except Exception as e:
        ssid_table = []

def save_ssid_table():
    with open(SSID_TABLE_PATH, 'w', encoding='utf-8') as f:
        json.dump(ssid_table, f, ensure_ascii=False, indent=2)

def load_area_table():
    global area_table
    if os.path.exists(AREA_TABLE_PATH):
        with open(AREA_TABLE_PATH, 'r', encoding='utf-8') as f:
            area_table = json.load(f)
    else:
        area_table = []

def save_area_table():
    with open(AREA_TABLE_PATH, 'w', encoding='utf-8') as f:
        json.dump(area_table, f, ensure_ascii=False, indent=2)

def load_area_order():
    if os.path.exists(AREA_ORDER_PATH):
        with open(AREA_ORDER_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # 初期値：ssid_table の area_id 順
    return [item["area_id"] for item in ssid_table]


def save_area_order(order):
    with open(AREA_ORDER_PATH, "w", encoding="utf-8") as f:
        json.dump(order, f, ensure_ascii=False, indent=2)

# --- ログインチェック用デコレータ ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ファイル変更監視用
def watch_ssid_file(poll_interval=1.0):
    last_mtime = None
    while True:
        try:
            if os.path.exists(SSID_TABLE_PATH):
                mtime = os.path.getmtime(SSID_TABLE_PATH)
                if last_mtime is None:
                    last_mtime = mtime
                elif mtime != last_mtime:
                    last_mtime = mtime
                    # 外部でファイルが書き換えられたら再読込
                    load_ssid_table()
                    # area_status_table を ssid_table に合わせて更新
                    # global area_status_table
                    # area_status_table = [
                    #     {"area_id": ssid_item["area_id"], "instruction": "none", "fire": False}
                    #     for ssid_item in ssid_table
                    # ]
        except Exception:
            pass
        time.sleep(poll_interval)

def watch_area_file(poll_interval=1.0):
    last_mtime = None
    while True:
        try:
            if os.path.exists(AREA_TABLE_PATH):
                mtime = os.path.getmtime(AREA_TABLE_PATH)
                if last_mtime is None:
                    last_mtime = mtime
                elif mtime != last_mtime:
                    last_mtime = mtime
                    # 外部でファイルが書き換えられたら再読込
                    load_area_table()
                    # area_status_table を ssid_table に合わせて更新
                    global area_status_table
                    area_status_table = [
                        {"area_id": area_item["area_id"], "instruction": "none", "fire": False}
                        for area_item in area_table
                    ]
        except Exception:
            pass
        time.sleep(poll_interval)

# === SSID -> password の辞書を生成 ===
def get_wifi_credentials():
    return {
        item["ssid"]: item["password"]
        for item in ssid_table
        if "ssid" in item and "password" in item
    }

# === 汎用ユーティリティ ===
# 同一SSIDがリスト内にあればそのパスワードとエリアIDを上書きする関数
def update_or_append(table, key_field, new_item):
    for i, item in enumerate(table):
        if item.get(key_field) == new_item.get(key_field):
            table[i] = new_item
            return
    table.append(new_item)
    
def reset_all_instructions():
    for area in area_status_table:
        area['instruction'] = 'none'
        area['fire'] = False


# 起動時に SSID テーブルをロード
load_ssid_table()
load_area_order()
load_area_table()
entry_status_table = []

# area_status_table を area_table の area_id に基づいて初期化
area_status_table = [
    {"area_id": area_item["area_id"], "instruction": "none", "fire": False}
    for area_item in area_table
]

# --- 既存のインポートの下に追加 ---
# login.htmlを表示するためのルート
@app.route("/")
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template("login.html")

@app.route("/index")
@login_required # これをつけるだけで未ログインを弾く
def index():
    return render_template("index.html")

@app.route("/api/login_mock", methods=["POST"])
def login_mock():
    # ハリボテ認証：セッションに記録
    session['logged_in'] = True
    return jsonify({"status": "success", "redirect": url_for("index")})

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

# === トップページ ===
# @app.route("/index", methods=["GET", "POST"])
# def index():
#     return render_template("index.html")

# @app.route("/")
# def admin_page():
#     redirect(url_for("index"))


# # ログインボタンを押した後の遷移先（ハリボテなのでそのまま管理画面へ）
# @app.route("/api/login_mock", methods=["POST"])
# def login_mock():
#     # 本来はここで認証しますが、今回は即座にOKを返します
#     return jsonify({"status": "success", "redirect": url_for("index")})


# === 管理者ページ：WiFi設定 ===
@app.route("/chkwifi", methods=["GET", "POST"])
def admin_wifi():
    # テスト用アクセスポイントの登録
    if request.method == "POST":
        ssid = request.form.get("ssid")
        password = request.form.get("password")
        if ssid and password:
            new_entry = {
                "area_id": "any",  # エリアIDが未指定のとき用
                "ssid": ssid,
                "password": password
            }
            update_or_append(ssid_table, "ssid", new_entry)
            save_ssid_table()
        return redirect(url_for("admin_wifi"))

    wifi_data = get_wifi_credentials()
    return render_template("wifi.html", wifi_data=wifi_data)



# @app.route("/")
# def admin_page():
#     return render_template("admin.html")


# 以下すべてAPI定義部
# === エリア状態の更新・取得 ===
# POSTはjs側からアクセス(GETは使わない)
# 順序変更のためリスト全体を入力する形式
@app.route('/api/area_status', methods=['POST', 'GET'])
def handle_area_status():
    if request.method == 'POST':
        # [{ area_id, 指示, 火災場所かどうか }, ...]
        # POST前に必ずGETで現在のリスト全体を取得する必要有
        data = request.json
        if not isinstance(data, list):
            return jsonify({'error': 'リスト形式でデータを送ってください'}), 400

        for item in data:
            if 'area_id' not in item:
                return jsonify({'error': '各要素に area_id が必要です'}), 400
            update_or_append(area_status_table, 'area_id', item)

        return jsonify({'message': 'area status updated', 'area_status': area_status_table})

    else:
        return jsonify(area_status_table)

# === SSID設定の更新・取得 ===
# POSTはjs側からアクセス(GETは使わない)
# エリアごとにアクセスポイントを割り振りする目的
# 1つずつ要素を入れる形式
@app.route('/api/ssid', methods=['POST', 'GET'])
def handle_ssid():
    if request.method == 'POST':
        # { ssid, password }
        data = request.json
        if 'ssid' not in data:
            return jsonify({'error': 'ssidが必要です'}), 400

        # 1. SSIDテーブル更新
        update_or_append(ssid_table, 'ssid', data)
        save_ssid_table()

        return jsonify({'message': 'SSID table updated', 'ssid_table': ssid_table})
    else:
        return jsonify(ssid_table)


@app.route('/api/ssid', methods=['DELETE'])
def delete_ssid():
    # body: { ssid }
    data = request.json or {}
    target_ssid = data.get('ssid')
    removed = False
    if target_ssid:
        new_table = [item for item in ssid_table if item.get('ssid') != target_ssid]
        if len(new_table) != len(ssid_table):
            removed = True
            ssid_table[:] = new_table
    else:
        return jsonify({'error': 'ssid を指定してください'}), 400

    if removed:
        save_ssid_table()
        return jsonify({'message': 'deleted', 'ssid_table': ssid_table})
    else:
        return jsonify({'error': '該当するエントリが見つかりませんでした'}), 404

@app.route('/api/area', methods=['POST', 'GET'])
def handle_area():
    if request.method == 'POST':
        # { area_id, gateway }
        data = request.json
        if 'area_id' not in data:
            return jsonify({'error': 'area_idが必要です'}), 400

        # 1. SSIDテーブル更新
        update_or_append(area_table, 'area_id', data)
        save_area_table()

        # 2. area_status_table に area_id がなければ追加
        existing_area = next((item for item in area_status_table if item['area_id'] == data['area_id']), None)
        if not existing_area:
            area_status_table.append({
                "area_id": data['area_id'],
                "instruction": "none",
                "fire": False
            })

        return jsonify({'message': 'area table updated', 'area_table': area_table})
    else:
        return jsonify(area_table)

@app.route('/api/area', methods=['DELETE'])
def delete_area():
    # body: { area_id }
    data = request.json or {}
    target_area = data.get('area_id')
    removed = False
    if target_area:
        new_table = [item for item in area_table if item.get('area_id') != target_area]
        if len(new_table) != len(area_table):
            removed = True
            area_table[:] = new_table
    else:
        return jsonify({'error': 'area_id を指定してください'}), 400
    if removed:
        save_area_table()
        return jsonify({'message': 'deleted', 'area_table': area_table})
    else:
        return jsonify({'error': '該当するエントリが見つかりませんでした'}), 404

@app.route("/api/area_order", methods=["GET", "POST"])
def handle_area_order():
    if request.method == "POST":
        data = request.json
        if not isinstance(data, list):
            return jsonify({"error": "list形式で送信してください"}), 400

        # area_id のみ許可
        valid_ids = {item["area_id"] for item in area_status_table}
        filtered = [aid for aid in data if aid in valid_ids]

        save_area_order(filtered)
        return jsonify({"message": "area order saved", "order": filtered})

    else:
        return jsonify(load_area_order())

    
# === APリストの取得 ===
# マイコン側からアクセス
@app.route("/api/wifi_list", methods=["GET"])
def get_wifi_list():
    return jsonify(get_wifi_credentials())

# === エントリ状態の取得（1分間応答がないデバイスを除外） ===
@app.route('/api/entry_status', methods=['GET'])
def get_entry_status():
    now = time.time()
    timeout_sec = 60

    valid_ids = {
        device_id
        for device_id, last_seen in last_seen_dict.items()
        if now - last_seen <= timeout_sec
    }

    active_entries = [
        entry for entry in entry_status_table
        if entry['device_id'] in valid_ids
    ]
    return jsonify(active_entries)


# === 入場状態の更新，指示の送信・取得 ===
# マイコン側からアクセス(レスポンスでエリアIDと指示内容)
# 1つずつ要素を入れる形式
@app.route('/api/alive_check', methods=['POST', 'GET'])
def handle_entry():
    if request.method == 'POST':
        # { device_id, ssid, gateway, 通報の有無(True/False), username }
        data = request.json
        if 'device_id' not in data or 'ssid' not in data or 'report' not in data or 'gateway' not in data:
            return jsonify({'error': 'device_id, ssid, gateway, reportが必要です'}), 400

        # 1. gatewayからarea_idを導出
        matched_area = next((item for item in area_table if item['gateway'] == data['gateway']), None)
        if not matched_area:
            print('該当するSSIDが見つかりません')
            return jsonify({'error': '該当するSSIDが見つかりません'}), 404
        area_id = matched_area['area_id']

        # 2. entry_status_tableの更新（device_idで上書き or 追加, keyは"report"）
        new_entry = {'device_id': data['device_id'], 'area_id': area_id, 'username': data['username']}
        update_or_append(entry_status_table, 'device_id', new_entry)
        
        # 最終アクセス時刻を記録
        last_seen_dict[data['device_id']] = time.time()

        # 3. 通報がTrueならエリア状態を更新
        if data['report'] is True:
            # 全エリアの指示を alert に
            for area in area_status_table:
                area['instruction'] = 'alert'
            # 該当エリアのfireをTrueに
            matched_area_status = next((item for item in area_status_table if item['area_id'] == area_id), None)
            if matched_area_status:
                matched_area_status['fire'] = True
        # else:
        #     matched_area_status = next((item for item in area_status_table if item['area_id'] == area_id), None)
        #     if matched_area_status:
        #         matched_area_status['instruction'] = "waiting"
            

        # 4. area_status_tableから指示内容を取得
        matched_area_status = next((item for item in area_status_table if item['area_id'] == area_id), None)
        instruction = matched_area_status['instruction'] if matched_area_status else 'none'
        
        print(area_id, data['username'], f"\n通報：{data['report']}")

        # 5. area_idと指示内容を返す
        return jsonify({
            'area_id': area_id,
            'instruction': instruction
        })

    else:
        # GET: 現在のエントリ状態を返す
        return jsonify(entry_status_table)


if __name__ == "__main__":
    # SSIDファイル監視スレッドを起動
    watcher = threading.Thread(target=watch_ssid_file, daemon=True)
    watcher.start()
    watcher2 = threading.Thread(target=watch_area_file, daemon=True)
    watcher2.start()
    if __name__ == '__main__':
        app.run(host="0.0.0.0", port=5000, debug=False)
