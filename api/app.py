from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from functools import wraps
import threading
import json
import os
import time

app = Flask(__name__)
app.secret_key = 'mamotchi_secret_key_pixel'

#supabase API Key
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

# TABLE_ACCESS_POINT = "access_point"
# TABLE_AREA = "area"
# TABLE_AREA_STATUS = "area_statuses"
# TABLE_AREA_ORDER = "area_order"
# TABLE_WIFI_REPORTS = "wifi_reports"
TABLE_AP_POSITIONS = "ap_positions"

TABLE_AP_AREA = "ap_areas"
TABLE_AREA_STATUS = "area_status"
TABLE_AREA_ORDER = "area_order"
TABLE_USER = "user"
TABLE_WIFI_REPORTS = "wifi_reports"
TABLE_AP_POSITIONS = "ap_positions"
TABLE_AREA_ORDER = "ap_area_order"

entry_status_table = []
last_seen_dict = {}

# ==========================================
#  Supabase 連携データ処理関数
# ==========================================

def load_wifi_reports():
    try:
        response = supabase.table(TABLE_WIFI_REPORTS).select("*").order("id", desc=False).execute()
        result = {}
        for row in response.data:
            device_id = row.get("device_id")
            result[device_id] = {
                "username": row.get("username"),
                "report": row.get("report"),
                "mac01": row.get("mac01"),
                "mac02": row.get("mac02"),
            }
        return result
    except Exception as e:
        print(f"Error loading wifi_reports: {e}")
        return {}


def load_ap_positions():
    try:
        response = supabase.table(TABLE_AP_POSITIONS).select("*").execute()
        return {row["mac"]: row["position"] for row in response.data}
    except Exception as e:
        print(f"Error loading ap_positions: {e}")
        return {}


def load_user_table():
    try:
        response = supabase.table(TABLE_USER).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading SSID table: {e}")
        return []


def load_area_table():
    try:
        response = supabase.table(TABLE_AP_AREA).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading area table: {e}")
        return []


def load_area_order():
    try:
        response = supabase.table(TABLE_AREA_ORDER).select("area_id").order("sort_order", ascending=True).execute()
        return [item["area_id"] for item in response.data]
    except Exception as e:
        print(f"Error loading area order: {e}")
        return []


# def get_wifi_credentials():
#     """SSIDとパスワードの辞書（マイコン用）を生成"""
#     ssid_table = load_ssid_table()
#     return {
#         item["ssid"]: item["password"]
#         for item in ssid_table
#         if "ssid" in item and "password" in item
#     }


#いる?
def update_or_append(table, key_field, new_item):
    """ローカルリスト用の汎用更新関数"""
    for i, item in enumerate(table):
        if item.get(key_field) == new_item.get(key_field):
            table[i] = new_item
            return
    table.append(new_item)


# ==========================================
#  認証用デコレータ
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function


@app.route("/", methods=["GET", "POST"])
def login_page():
    if request.method == "POST":
        data = request.json or {}
        email = data.get("email", "").strip()
        password = data.get("password", "").strip()
        mode = data.get("mode", "login")

        if not email or not password:
            return jsonify({"status": "error", "message": "IDとパスワードを入力してください"}), 400

        try:
            if mode == "signup":
                result = supabase.auth.sign_up({"email": email, "password": password})
                if result.user:
                    session['logged_in'] = True
                    session['user_email'] = result.user.email
                    return jsonify({"status": "success", "redirect": url_for("index")})
                return jsonify({"status": "error", "message": "登録に失敗しました"}), 400
            else:
                result = supabase.auth.sign_in_with_password({"email": email, "password": password})
                session['logged_in'] = True
                session['user_email'] = result.user.email
                return jsonify({"status": "success", "redirect": url_for("index")})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 401

    if session.get('logged_in'):
        return redirect(url_for('index'))
    return render_template("login.html")


@app.route("/index")
@login_required
def index():
    return render_template("index.html")


@app.route("/logout")
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login_page'))


#使ってる？
@app.route("/chkwifi", methods=["GET", "POST"])
@login_required
def admin_wifi():
    if request.method == "POST":
        username = request.form.get("username")
        device_id = request.form.get("device_id")
        if username and device_id:
            new_entry = {"area_id": "any", "username": username, "device_id": device_id}
            try:
                supabase.table(TABLE_USER).upsert(new_entry).execute()
            except Exception as e:
                print(f"Error saving Wi-Fi to Supabase: {e}")
        return redirect(url_for("admin_wifi"))

    wifi_data = load_user_table()
    return render_template("wifi.html", wifi_data=wifi_data)



# API

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
            response = supabase.table(TABLE_AREA_STATUS).upsert(data).execute()
            return jsonify({
                'message': 'area status updated in Supabase', 
                'area_status': response.data
            })
        except Exception as e:
            return jsonify({'error': f'Supabaseの更新に失敗しました: {str(e)}'}), 500
    else:
        try:
            response = supabase.table(TABLE_AREA_STATUS).select("*").execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': f'Supabaseからのデータ取得に失敗しました: {str(e)}'}), 500


@app.route('/api/user', methods=['POST', 'GET'])
def handle_user():
    if request.method == 'POST':
        data = request.json
        if not data.get("username"):
            # return jsonify({'error': 'ユーザー名が入力されていません。str(data.get("username"))'}), 400
            return jsonify({'error': data}), 400
        
        if not data.get("device_id"):
            return jsonify({'error': 'デバイスIDが入力されていません。'}), 400

        try:
            supabase.table(TABLE_USER).upsert(data).execute()
            return jsonify({'message': 'User updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_user_table())
    

@app.route('/api/user', methods=['DELETE'])
def delete_user():
    data = request.json or {}
    target_username = data.get('username')
    if not target_username:
        return jsonify({'error': 'username を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するUsernameの行を削除
        supabase.table(TABLE_USER).delete().eq("username", target_username).execute()
        return jsonify({'message': 'deleted from Supabase', 'user_table': load_user_table()})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500


@app.route('/api/area', methods=['POST', 'GET'])
def handle_area():
    if request.method == 'POST':
        data = request.json
        if not data.get("area_id"):
            return jsonify({'error': 'エリアIDが入力されていません。'}), 400
        
        if not data.get("bssid"):
            return jsonify({'error': 'BSSIDが入力されていません。'}), 400
        
        try:
            supabase.table(TABLE_AP_AREA).upsert(data).execute()
            return jsonify({'message': 'Area master updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_area_table())
    

@app.route('/api/area', methods=['DELETE'])
def delete_area():
    data = request.json or {}
    target_area = data.get('area_id')
    if not target_area:
        return jsonify({'error': 'area_id を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するarea_idの行を削除
        supabase.table(TABLE_AP_AREA).delete().eq("area_id", target_area).execute()
        return jsonify({'message': 'deleted from Supabase', 'area_table': load_area_table()})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500
    




@app.route('/api/ap_positions', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_ap_positions():
    if request.method == 'GET':
        try:
            response = supabase.table(TABLE_AP_POSITIONS).select("*").order("position", ascending=True).execute()
            return jsonify(response.data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    elif request.method == 'POST':
        data = request.json
        if 'mac' not in data or 'position' not in data:
            return jsonify({'error': 'mac と position が必要です'}), 400
        try:
            supabase.table(TABLE_AP_POSITIONS).upsert(data).execute()
            return jsonify({'message': 'AP position saved'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        data = request.json or {}
        mac = data.get('mac')
        if not mac:
            return jsonify({'error': 'mac を指定してください'}), 400
        try:
            supabase.table(TABLE_AP_POSITIONS).delete().eq('mac', mac).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/wifi_map', methods=['GET'])
@login_required
def get_wifi_map():
    AP_COUNT = 5
    reports = load_wifi_reports()
    ap_pos = load_ap_positions()
    area_order = load_area_order()

    workers = []
    for device_id, info in reports.items():
        mac1 = info.get('mac01')
        mac2 = info.get('mac02')

        pos1 = ap_pos.get(mac1)
        pos2 = ap_pos.get(mac2)

        if pos1 is None:
            continue

        r1 = pos1 / (AP_COUNT - 1)
        if pos2 is not None:
            r2 = pos2 / (AP_COUNT - 1)
            ratio = 0.67 * r1 + 0.33 * r2
        else:
            ratio = r1

        n = len(area_order)
        area_idx = min(int(ratio * n), n - 1) if n > 0 else 0
        area_id = area_order[area_idx] if area_order else None

        workers.append({
            'device_id': device_id,
            'username': info.get('username'),
            'report': info.get('report'),
            'ratio': round(ratio, 4),
            'area_id': area_id,
        })

    return jsonify({
        'workers': workers,
        'ap_count': AP_COUNT,
        'area_order': area_order,
    })


@app.route("/api/area_order", methods=["GET", "POST"])
def handle_area_order():
    if request.method == "POST":
        data = request.json  # array of area_id strings: ["入口", "100m", ...]
        records = [{"area_id": aid, "sort_order": i} for i, aid in enumerate(data)]
        try:
            supabase.table(TABLE_AREA_ORDER).upsert(records).execute()
            return jsonify({"message": "area order saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify(load_area_order())


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


@app.route("/test-deploy")
def test_deploy():
    return "DEPLOYED-V3-POST-OK"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)