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

# ==========================================
#  Supabase 連携データ処理関数
# ==========================================

def load_supabase_table(area_name):
    try:
        response = supabase.table(area_name).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading area table: {e}")
        return []


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
    if request.method == 'POST':
        data = request.json
        if not isinstance(data, list):
            return jsonify({'error': 'リスト形式でデータを送ってください'}), 400

        for item in data:
            if 'area_id' not in item:
                return jsonify({'error': '各要素に area_id が必要です'}), 400

        response = load_supabase_table(TABLE_AREA_STATUS)
        return jsonify({
            'message': 'area status updated in Supabase', 
            'area_status': response
        })
    else:
        response = load_supabase_table(TABLE_AREA_STATUS)
        return jsonify(response)


@app.route('/api/ssid', methods=['POST', 'GET'])
def handle_ssid():
    if request.method == 'POST':
        data = request.json
        # if 'ssid' not in data:
        if not ('username' and 'device_id' in data):
            return jsonify({'error': 'usernameとdevice_idが必要です'}), 400
        try:
            supabase.table(TABLE_USER).upsert(data).execute()
            return jsonify({'message': 'user updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_supabase_table(TABLE_USER))
    

@app.route('/api/ssid', methods=['DELETE'])
def delete_ssid():
    data = request.json or {}
    target_user = data.get('username')
    if not target_user:
        return jsonify({'error': 'username を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するユーザの行を削除
        supabase.table(TABLE_USER).delete().eq("username", target_user).execute()
        return jsonify({'message': 'deleted from Supabase', 'user_table': load_supabase_table(TABLE_USER)})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500


@app.route('/api/area', methods=['POST', 'GET'])
def handle_area():
    if request.method == 'POST':
        data = request.json
        # if 'area_id' not in data:
        if not('area_id' and 'bssid' in data):
            return jsonify({'error': 'area_idとbssidが必要です'}), 400
        try:
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
        # Supabaseのテーブルから、該当するbssidの行を削除
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
def Location_estimation(dev_info):
    try:
        response = supabase.table(TABLE_AP_AREA).select("*").execute()
        area_dict = {}
        for item in response:
            area_dict[item["bssid"]] = item["area"]

        output = list()
        for item in dev_info:
            output.append({"area_id": area_dict[item["mac01"]],"username": item["username"], "device_id": item["dev_id"]})
        
        return output

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)