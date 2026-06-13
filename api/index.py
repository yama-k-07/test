import os
import time
import json
from functools import wraps
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client

app = Flask(__name__, template_folder='templates')
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "mamotchi_secret_key_pixel")

# ==========================================
# 🛠️ Supabase 初期化設定
# ==========================================
url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ROLE_KEY") or os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY")
supabase: Client = create_client(url, key)

# Supabase上の実際のテーブル名（環境に合わせて変更してください）
TABLE_ACCESS_POINT = "access_point"
TABLE_AREA = "area"
TABLE_AREA_STATUS = "area_statuses"  # 👈 前回の typo (status_table) を修正

# ==========================================
# 💾 ローカルキャッシュ＆状態管理
# ==========================================
# リアルタイムで頻繁にアクセスされる一時データはメモリ上で管理します
entry_status_table = []
last_seen_dict = {}  # device_id -> UNIX timestamp

# ==========================================
# 🔄 Supabase 連携データ処理関数
# ==========================================

def load_ssid_table():
    """Supabaseからアクセスポイント（Wi-Fi）一覧を取得"""
    try:
        response = supabase.table(TABLE_ACCESS_POINT).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading SSID table: {e}")
        return []

def load_area_table():
    """Supabaseからエリア＆ゲートウェイ一覧を取得"""
    try:
        response = supabase.table(TABLE_AREA).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading area table: {e}")
        return []

def get_wifi_credentials():
    """SSIDとパスワードの辞書（マイコン用）を生成"""
    ssid_table = load_ssid_table()
    return {
        item["ssid"]: item["password"]
        for item in ssid_table
        if "ssid" in item and "password" in item
    }

def update_or_append(table, key_field, new_item):
    """ローカルリスト用の汎用更新関数"""
    for i, item in enumerate(table):
        if item.get(key_field) == new_item.get(key_field):
            table[i] = new_item
            return
    table.append(new_item)

# ==========================================
# 🔐 認証用デコレータ
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

# ==========================================
# 🌐 画面表示・認証ルート定義
# ==========================================

@app.route("/")
def login_page():
    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template("login.html")

@app.route("/index")
@login_required
def index():
    return render_template("index.html")

@app.route("/api/login_mock", methods=["POST"])
def login_mock():
    session['logged_in'] = True
    return jsonify({"status": "success", "redirect": url_for("index")})

@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))

@app.route("/chkwifi", methods=["GET", "POST"])
@login_required
def admin_wifi():
    if request.method == "POST":
        ssid = request.form.get("ssid")
        password = request.form.get("password")
        if ssid and password:
            new_entry = {"area_id": "any", "ssid": ssid, "password": password}
            try:
                # Web画面からの新しいWi-Fi登録も、直接Supabaseへupsert（自動上書き/追加）
                supabase.table(TABLE_ACCESS_POINT).upsert(new_entry).execute()
            except Exception as e:
                print(f"Error saving Wi-Fi to Supabase: {e}")
        return redirect(url_for("admin_wifi"))

    wifi_data = get_wifi_credentials()
    return render_template("wifi.html", wifi_data=wifi_data)

# ==========================================
# 🔌 API定義部（JavaScript ＆ マイコン向け）
# ==========================================

# --- エリア状態の更新・取得 (JS/管理者画面用) ---
@app.route('/api/area_status', methods=['POST', 'GET'])
def handle_area_status():
    if request.method == 'POST':
        data = request.json
        if not isinstance(data, list):
            return jsonify({'error': 'リスト形式でデータを送ってください'}), 400

        for item in data:
            if 'area_id' not in item:
                return jsonify({'error': '各要素に area_id が必要です'}), 400

        try:
            # 修正：変数 typos を直し、直接Supabaseにupsert
            response = supabase.table(TABLE_AREA_STATUS).upsert(data).execute()
            return jsonify({
                'message': 'area status updated in Supabase', 
                'area_status': response.data
            })
        except Exception as e:
            return jsonify({'error': f'Supabaseの更新に失敗しました: {str(e)}'}), 500

    else:
        try:
            # 直接Supabaseから最新のエリア火災状況・避難指示を取得
            response = supabase.table(TABLE_AREA_STATUS).select("*").execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': f'Supabaseからのデータ取得に失敗しました: {str(e)}'}), 500


# --- SSID（アクセスポイント）個別操作用 ---
@app.route('/api/ssid', methods=['POST', 'GET'])
def handle_ssid():
    if request.method == 'POST':
        data = request.json
        if 'ssid' not in data:
            return jsonify({'error': 'ssidが必要です'}), 400
        try:
            supabase.table(TABLE_ACCESS_POINT).upsert(data).execute()
            return jsonify({'message': 'SSID updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_ssid_table())


# --- エリア定義マスタの操作用 ---
@app.route('/api/area', methods=['POST', 'GET'])
def handle_area():
    if request.method == 'POST':
        data = request.json
        if 'area_id' not in data:
            return jsonify({'error': 'area_idが必要です'}), 400
        try:
            supabase.table(TABLE_AREA).upsert(data).execute()
            return jsonify({'message': 'Area master updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_area_table())


# --- マイコン（Pico等）用：Wi-Fi一覧取得 ---
@app.route("/api/wifi_list", methods=["GET"])
def get_wifi_list():
    return jsonify(get_wifi_credentials())


# --- 入退場状態の取得（1分間応答がないデバイスを除外） ---
@app.route('/api/entry_status', methods=['GET'])
def get_entry_status():
    global entry_status_table
    now = time.time()
    timeout_sec = 60

    valid_ids = {
        device_id for device_id, last_seen in last_seen_dict.items()
        if now - last_seen <= timeout_sec
    }
    active_entries = [
        entry for entry in entry_status_table
        if entry['device_id'] in valid_ids
    ]
    return jsonify(active_entries)


# --- マイコン用：生存確認 ＆ 火災通報 ＆ 避難指示取得 ---
@app.route('/api/alive_check', methods=['POST', 'GET'])
def handle_entry():
    global entry_status_table
    if request.method == 'POST':
        data = request.json
        if not data or 'device_id' not in data or 'gateway' not in data or 'report' not in data:
            return jsonify({'error': 'device_id, gateway, reportが必要です'}), 400

        # 1. gateway（IP）から所属area_idを判定
        area_table_data = load_area_table()
        matched_area = next((item for item in area_table_data if item['gateway'] == data['gateway']), None)
        if not matched_area:
            return jsonify({'error': '該当するゲートウェイエリアが見つかりません'}), 404
        area_id = matched_area['area_id']

        # 2. メモリ上の生存リストを更新
        username = data.get('username', 'Unknown')
        new_entry = {'device_id': data['device_id'], 'area_id': area_id, 'username': username}
        update_or_append(entry_status_table, 'device_id', new_entry)
        last_seen_dict[data['device_id']] = time.time()

        # 3. ボタン等で「火災通報（report=True）」された場合のSupabase処理
        if data['report'] is True:
            try:
                # 3-1. まず現在の全エリア状況をSupabaseから引っ張る
                current_status = supabase.table(TABLE_AREA_STATUS).select("*").execute().data
                
                # 3-2. 全エリアを一斉に「alert（通報通知）」にし、通報元のarea_idだけ「fire=True」に書き換える
                for area in current_status:
                    area['instruction'] = 'alert'
                    if area['area_id'] == area_id:
                        area['fire'] = True
                
                # 3-3. まとめてSupabaseへupsert
                supabase.table(TABLE_AREA_STATUS).upsert(current_status).execute()
            except Exception as e:
                print(f"Error handling emergency report in Supabase: {e}")

        # 4. マイコンへ返すために、現在の該当エリアの「避難指示内容」をSupabaseから取得
        try:
            status_response = supabase.table(TABLE_AREA_STATUS).select("instruction").eq("area_id", area_id).execute()
            if status_response.data:
                instruction = status_response.data[0]['instruction']
            else:
                instruction = 'none'
        except Exception:
            instruction = 'none'

        print(f"Area: {area_id}, User: {username}, Report: {data['report']}, Instruction: {instruction}")

        return jsonify({
            'area_id': area_id,
            'instruction': instruction
        })
    else:
        # GET時はメモリ内の生存一覧を返却
        return get_entry_status()


if __name__ == '__main__':
    # ローカル検証用 (Vercelデプロイ時はここは無視され、上のappオブジェクトが自動的に呼ばれます)
    app.run(host="0.0.0.0", port=5000, debug=False)