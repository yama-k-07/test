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
supabase: Client | None = create_client(url, key) if url and key else None

# TABLE_ACCESS_POINT = "access_point"
# TABLE_AREA = "ap_areas"
# TABLE_AREA_STATUS = "area_statuses"
# TABLE_AREA_ORDER = "area_order"

# TABLE_SSID_LIST = "SSID_List"
TABLE_AP_AREA = "ap_areas"          #読み書き　(area追加時にarea_statusも追加)
TABLE_AREA_STATUS = "area_status"   #読み取り
# TABLE_REPORT = "device_id"
TABLE_EMPLOYEE = "employee_status"  #読み取り　user追加時に一緒に追加
TABLE_USER = "user"                 #読み書き
TABLE_SIGNAL = "wifi_reports"       #読み取り

entry_status_table = []
last_seen_dict = {}
ap_position_map = {}
area_order_list = []
area_status_store = []

# ==========================================
#  Supabase 連携データ処理関数
# ==========================================

def load_supabase_table(area_name):
    if supabase is None:
        return []
    try:
        response = supabase.table(area_name).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading area table: {e}")
        return []


def load_wifi_reports():
    if supabase is None:
        return {}
    try:
        response = supabase.table(TABLE_SIGNAL).select("*").execute()
        result = {}
        for row in response.data:
            device_id = row.get("device_id")
            if device_id:
                result[device_id] = {
                    "username": row.get("username"),
                    "report": row.get("report"),
                    "mac01": row.get("mac01"),
                    "mac02": row.get("mac02"),
                }
        return result
    except Exception as e:
        print(f"Error loading wifi reports: {e}")
        return {}


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


# @app.route("/chkwifi", methods=["GET", "POST"])
# @login_required
# def admin_wifi():
#     if request.method == "POST":
#         ssid = request.form.get("ssid")
#         password = request.form.get("password")
#         if ssid and password:
#             new_entry = {"area_id": "any", "ssid": ssid, "password": password}
#             try:
#                 supabase.table(TABLE_ACCESS_POINT).upsert(new_entry).execute()
#             except Exception as e:
#                 print(f"Error saving Wi-Fi to Supabase: {e}")
#         return redirect(url_for("admin_wifi"))

#     wifi_data = get_wifi_credentials()
#     return render_template("wifi.html", wifi_data=wifi_data)



# API

@app.route('/api/area_status', methods=['POST', 'GET'])
def handle_area_status():
    global area_status_store
    if request.method == 'POST':
        data = request.json
        if not isinstance(data, list):
            return jsonify({'error': 'リスト形式でデータを送ってください'}), 400

        for item in data:
            if 'area_id' not in item:
                return jsonify({'error': '各要素に area_id が必要です'}), 400

        for incoming in data:
            existing = next((item for item in area_status_store if item.get('area_id') == incoming.get('area_id')), None)
            if existing is None:
                area_status_store.append({
                    'area_id': incoming.get('area_id'),
                    'instruction': incoming.get('instruction', 'none'),
                    'fire': bool(incoming.get('fire', False))
                })
            else:
                existing['instruction'] = incoming.get('instruction', existing.get('instruction', 'none'))
                existing['fire'] = bool(incoming.get('fire', existing.get('fire', False)))

        if supabase is not None:
            try:
                supabase.table(TABLE_AREA_STATUS).upsert(data).execute()
            except Exception as e:
                print(f"Error updating area status: {e}")

        return jsonify({
            'message': 'area status updated',
            'area_status': area_status_store
        })
    else:
        if area_status_store:
            return jsonify(area_status_store)
        response = load_supabase_table(TABLE_AREA_STATUS)
        if response:
            area_status_store = response
        return jsonify(response)


@app.route('/api/ssid', methods=['POST', 'GET'])
def handle_ssid():
    if request.method == 'POST':
        data = request.json or {}
        payload = dict(data)

        if 'username' not in payload and 'ssid' in payload:
            payload['username'] = payload['ssid']
        if 'device_id' not in payload and 'password' in payload:
            payload['device_id'] = payload['password']

        if not payload.get('username') and not payload.get('device_id'):
            return jsonify({'error': 'usernameまたはdevice_idが必要です'}), 400

        try:
            if supabase is not None:
                supabase.table(TABLE_USER).upsert(payload).execute()
            if payload.get('device_id'):
                last_seen_dict[payload['device_id']] = time.time()
            return jsonify({'message': 'user updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_supabase_table(TABLE_USER))


@app.route('/api/ssid', methods=['DELETE'])
def delete_ssid():
    data = request.json or {}
    target_user = data.get('username') or data.get('ssid') or data.get('device_id')
    if not target_user:
        return jsonify({'error': 'username を指定してください'}), 400

    try:
        if supabase is not None:
            supabase.table(TABLE_USER).delete().eq("username", target_user).execute()
        return jsonify({'message': 'deleted from Supabase', 'user_table': load_supabase_table(TABLE_USER)})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500


@app.route('/api/area', methods=['POST', 'GET'])
def handle_area():
    if request.method == 'POST':
        data = request.json or {}
        if not data.get('area_id') or not data.get('bssid'):
            return jsonify({'error': 'area_idとbssidが必要です'}), 400
        try:
            if supabase is not None:
                supabase.table(TABLE_AP_AREA).upsert(data).execute()
            return jsonify({'message': 'Area master updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_supabase_table(TABLE_AP_AREA))


@app.route('/api/area', methods=['DELETE'])
def delete_area():
    data = request.json or {}
    target_area = data.get('bssid')
    if not target_area:
        return jsonify({'error': 'bssid を指定してください'}), 400

    try:
        if supabase is not None:
            supabase.table(TABLE_AP_AREA).delete().eq("bssid", target_area).execute()
        return jsonify({'message': 'deleted from Supabase', 'area_table': load_supabase_table(TABLE_AP_AREA)})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500
    

# @app.route("/api/area_order", methods=["GET", "POST"])
# def handle_area_order():
#     if request.method == "POST":
#         data = request.json  # 画面側から送られてきた順序データ（リスト、またはオブジェクト）
#         try:
#             # そのままSupabaseの順序テーブルに upsert（上書き保存）
#             supabase.table(TABLE_AREA_ORDER).upsert(data).execute()
#             return jsonify({"message": "area order saved in Supabase", "order": data})
#         except Exception as e:
#             return jsonify({"error": str(e)}), 500
#     else:
#         return jsonify(load_area_order())



# @app.route('/api/entry_status', methods=['GET'])
# def get_entry_status():
#     global entry_status_table
#     now = time.time()
#     timeout_sec = 60

#     # 1分以内に定期連絡（alive_check）があったデバイスIDだけを有効とする
#     valid_ids = {
#         device_id for device_id, last_seen in last_seen_dict.items()
#         if now - last_seen <= timeout_sec
#     }
    
#     # 有効なデバイスの生存データだけをリストにして画面に返却
#     active_entries = [
#         entry for entry in entry_status_table
#         if entry['device_id'] in valid_ids
#     ]
#     return jsonify(active_entries)

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
        if entry.get('device_id') in valid_ids
    ]

    if active_entries:
        return jsonify(active_entries)

    if supabase is not None:
        try:
            response = supabase.table(TABLE_USER).select("username, device_id").execute()
            fallback = []
            for row in response.data:
                if row.get('device_id') or row.get('username'):
                    fallback.append({
                        'device_id': row.get('device_id', ''),
                        'username': row.get('username', ''),
                        'area_id': ''
                    })
            return jsonify(fallback)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    return jsonify([])


@app.route('/api/area_order', methods=['GET', 'POST'])
def handle_area_order():
    global area_order_list
    if request.method == 'POST':
        data = request.json or []
        if isinstance(data, list):
            area_order_list = data
        return jsonify({'message': 'area order saved', 'order': area_order_list})
    return jsonify(area_order_list)


@app.route('/api/ap_positions', methods=['GET', 'POST', 'DELETE'])
def handle_ap_positions():
    global ap_position_map
    if request.method == 'GET':
        return jsonify([{"mac": mac, "position": pos} for mac, pos in ap_position_map.items()])
    if request.method == 'POST':
        data = request.json or {}
        mac = data.get('mac')
        position = data.get('position')
        if not mac or position is None:
            return jsonify({'error': 'mac と position が必要です'}), 400
        ap_position_map[mac] = int(position)
        return jsonify({'message': 'AP position saved'})

    data = request.json or {}
    mac = data.get('mac')
    if not mac:
        return jsonify({'error': 'mac を指定してください'}), 400
    ap_position_map.pop(mac, None)
    return jsonify({'message': 'deleted'})


@app.route('/api/wifi_map', methods=['GET'])
def get_wifi_map():
    reports = load_wifi_reports()
    ap_positions = ap_position_map
    order = area_order_list

    workers = []
    for device_id, info in reports.items():
        mac1 = info.get('mac01')
        mac2 = info.get('mac02')
        pos1 = ap_positions.get(mac1)
        pos2 = ap_positions.get(mac2)

        if pos1 is None:
            continue

        ratio = pos1 / 4 if pos1 is not None else 0
        if pos2 is not None:
            ratio = round((ratio + pos2 / 4) / 2, 4)

        area_id = order[min(int(ratio * len(order)), len(order) - 1)] if order else None
        workers.append({
            'device_id': device_id,
            'username': info.get('username'),
            'report': info.get('report'),
            'ratio': ratio,
            'area_id': area_id,
        })

    return jsonify({'workers': workers, 'ap_count': 5, 'area_order': order})
    

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)