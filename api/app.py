from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timezone, timedelta
import threading
import json
import os
import time

load_dotenv()

app = Flask(__name__)
app.secret_key = 'mamotchi_secret_key_pixel'

#supabase API Key
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

# TABLE_AP_AREA = "ap_areas"
# TABLE_AREA_STATUS = "area_status"
TABLE_AREA_STATUS = "area_status_v2"
# TABLE_AREA_ORDER = "ap_area_order"
TABLE_USER = "user"
TABLE_WIFI_LOG = "wifi_reports"
TABLE_WIFI_REPORTS = "latest_wifi_reports"
TABLE_AP_POSITIONS = "ap_positions"
TABLE_ENTRY_AP_CONFIG = "entry_ap_config"
TABLE_ENTRY_CURRENT = "entry_current"
TABLE_ENTRY_LOG = "entry_log"

entry_status_table = []
last_seen_dict = {}

# ==========================================
#  Supabase 連携データ処理関数
# ==========================================

def load_wifi_reports():
    """wifi_reports から device_id ごとの最新レコードを返す（同一APに複数デバイスがいても全員返す）"""
    try:
        response = supabase.table(TABLE_WIFI_LOG).select("*").order("id", desc=True).execute()
        seen = set()
        result = []
        for row in (response.data or []):
            did = row.get('device_id')
            if did and did not in seen:
                seen.add(did)
                result.append(row)
        return result
    except Exception as e:
        print(f"Error loading wifi_reports: {e}")
        return []


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
        response = supabase.table(TABLE_AREA_STATUS).select("bssid, area_id").execute()
        return response.data
    except Exception as e:
        print(f"Error loading area table: {e}")
        return []


def now_iso():
    return datetime.now(timezone.utc).isoformat()


JST = timezone(timedelta(hours=9))


def jst_today_utc_bounds():
    """日本時間で「今日」の0時〜24時をUTCのISO文字列範囲で返す"""
    start_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    end_jst = start_jst + timedelta(days=1)
    return start_jst.astimezone(timezone.utc).isoformat(), end_jst.astimezone(timezone.utc).isoformat()


def load_area_order():
    try:
        response = supabase.table(TABLE_AREA_STATUS).select("area_id").order("area_order", desc=False).execute()
        if response.data:
            return [item["area_id"] for item in response.data]
        fallback = supabase.table(TABLE_AREA_STATUS).select("area_id").execute()
        return [item["area_id"] for item in (fallback.data or [])]
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
            return jsonify({'error': f'Supabaseの更新に失敗しました: {str(e)}  data{str(data)}'}), 500
    else:
        try:
            response = supabase.table(TABLE_AREA_STATUS).select("instruction, fire, area_id").execute()
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
            supabase
            return jsonify({'message': 'User updated in Supabase'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify(load_user_table())
    

@app.route('/api/user', methods=['DELETE'])
def delete_user():
    data = request.json or {}
    target_device_id = data.get('device_id')
    if not target_device_id:
        return jsonify({'error': 'device_ID を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するUsernameの行を削除
        supabase.table(TABLE_USER).delete().eq("device_id", target_device_id).execute()
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
            supabase.table(TABLE_AREA_STATUS).upsert(data).execute()
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
        supabase.table(TABLE_AREA_STATUS).delete().eq("area_id", target_area).execute()
        return jsonify({'message': 'deleted from Supabase', 'area_table': load_area_table()})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500
    




@app.route('/api/ap_positions', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_ap_positions():
    if request.method == 'GET':
        try:
            response = supabase.table(TABLE_AP_POSITIONS).select("*").execute()
            data = sorted(response.data or [], key=lambda r: r.get("position", 0))
            return jsonify(data)
        except Exception as e:
            print(f"[ap_positions GET] {type(e).__name__}: {e}")
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
    AP_COUNT = 6
    AP_LABELS = ['1', '3', '4', '5', '6', '11']
    reports = load_wifi_reports()
    ap_pos = load_ap_positions()
    area_order = load_area_order()

    user_map = {u['device_id']: u['username'] for u in (load_user_table() or []) if u.get('device_id') and u.get('username')}

    workers = []
    for row in (reports or []):
        device_id = row.get('device_id')
        mac1 = row.get('mac01')
        mac2 = row.get('mac02')

        pos1 = ap_pos.get(mac1)
        pos2 = ap_pos.get(mac2)

        if pos1 is None and pos2 is None:
            continue

        if pos1 is not None and pos2 is not None:
            ratio = (pos1 / (AP_COUNT - 1) + pos2 / (AP_COUNT - 1)) / 2
        elif pos1 is not None:
            ratio = pos1 / (AP_COUNT - 1)
        else:
            ratio = pos2 / (AP_COUNT - 1)

        n = len(area_order)
        area_idx = min(int(ratio * n), n - 1) if n > 0 else 0
        area_id = area_order[area_idx] if area_order else None

        workers.append({
            'device_id': device_id,
            'username': user_map.get(device_id),
            'report': row.get('report'),
            'ratio': round(ratio, 4),
            'area_id': area_id,
        })

    return jsonify({
        'workers': workers,
        'ap_count': AP_COUNT,
        'ap_labels': AP_LABELS,
        'area_order': area_order,
    })


@app.route("/api/area_order", methods=["GET", "POST"])
def handle_area_order():
    if request.method == "POST":
        data = request.json  # array of area_id strings: ["入口", "100m", ...]
        records = [{"area_id": aid, "area_order": i} for i, aid in enumerate(data)]
        try:
            supabase.table(TABLE_AREA_STATUS).upsert(records).execute()
            return jsonify({"message": "area order saved"})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    else:
        return jsonify(load_area_order())


# @app.route('/api/entry_status', methods=['GET'])
# def get_entry_status():
#     global entry_status_table
#     now = time.time()
#     timeout_sec = 60
#     valid_ids = {
#         device_id for device_id, last_seen in last_seen_dict.items()
#         if now - last_seen <= timeout_sec
#     }
#     active_entries = [
#         entry for entry in entry_status_table
#         if entry['device_id'] in valid_ids
#     ]
#     return jsonify(active_entries)


@app.route('/api/entry_status', methods=['GET'])
def Location_estimation():
    dev_info = load_wifi_reports() or []

    try:
        r = supabase.table(TABLE_AREA_STATUS).select("bssid, area_id").execute()
        area_rows = getattr(r, "data", []) or []
        area_dict = {}
        for item in area_rows:
            bssid = item.get("bssid")
            if bssid is not None:
                area_dict[bssid] = item.get("area_id") or item.get("area")

        r = supabase.table(TABLE_USER).select("*").execute()
        user_rows = getattr(r, "data", []) or []
        user_dict = {}
        for item in user_rows:
            device_id = item.get("device_id")
            if device_id is not None:
                user_dict[device_id] = item.get("username")

        output = []
        for item in dev_info:
            mac = item.get("mac01")
            device_id = item.get("device_id")
            output.append({
                "area_id": area_dict.get(mac),
                "username": user_dict.get(device_id),
                "device_id": device_id,
            })

        return jsonify(output), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test-deploy")
def test_deploy():
    return "DEPLOYED-V3-POST-OK"


def load_entry_ap_config():
    try:
        response = supabase.table(TABLE_ENTRY_AP_CONFIG).select("mac").execute()
        return {row["mac"] for row in (response.data or [])}
    except Exception as e:
        print(f"Error loading entry_ap_config: {e}")
        return set()


def do_entry_status_update():
    """latest_wifi_reports を元に入退場を検出し entry_current / entry_log を更新する"""
    entry_ap_macs = load_entry_ap_config()
    reports = load_wifi_reports() or []
    user_map = {
        u['device_id']: u['username']
        for u in (load_user_table() or [])
        if u.get('device_id') and u.get('username')
    }

    try:
        cur_res = supabase.table(TABLE_ENTRY_CURRENT).select("*").execute()
        current_status = {row['device_id']: row for row in (cur_res.data or [])}
    except Exception as e:
        print(f"Error loading entry_current: {e}")
        current_status = {}

    now = now_iso()

    for row in reports:
        device_id = row.get('device_id')
        if not device_id:
            continue
        mac1 = row.get('mac01') or ''
        mac2 = row.get('mac02') or ''
        at_entry = bool(entry_ap_macs) and (mac1 in entry_ap_macs or mac2 in entry_ap_macs)

        prev = current_status.get(device_id, {})
        prev_status = prev.get('status', 'out')
        username = user_map.get(device_id)

        if at_entry and prev_status != 'in':
            supabase.table(TABLE_ENTRY_CURRENT).upsert({
                'device_id': device_id, 'username': username,
                'status': 'in', 'entry_time': now, 'exit_time': None, 'updated_at': now,
            }).execute()
            supabase.table(TABLE_ENTRY_LOG).insert({
                'device_id': device_id, 'username': username,
                'event_type': 'enter', 'event_time': now,
            }).execute()

        elif not at_entry and prev_status == 'in':
            supabase.table(TABLE_ENTRY_CURRENT).upsert({
                'device_id': device_id, 'username': username,
                'status': 'out', 'entry_time': prev.get('entry_time'),
                'exit_time': now, 'updated_at': now,
            }).execute()
            supabase.table(TABLE_ENTRY_LOG).insert({
                'device_id': device_id, 'username': username,
                'event_type': 'exit', 'event_time': now,
            }).execute()

    try:
        start_utc, end_utc = jst_today_utc_bounds()
        res = (
            supabase.table(TABLE_ENTRY_CURRENT)
            .select("*")
            .gte("updated_at", start_utc)
            .lt("updated_at", end_utc)
            .execute()
        )
        return res.data or []
    except Exception as e:
        print(f"Error fetching entry_current: {e}")
        return []


@app.route('/api/entry_ap_config', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_entry_ap_config():
    if request.method == 'GET':
        try:
            res = supabase.table(TABLE_ENTRY_AP_CONFIG).select("*").execute()
            return jsonify(res.data or [])
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    elif request.method == 'POST':
        data = request.json or {}
        mac = data.get('mac', '').strip()
        if not mac:
            return jsonify({'error': 'mac が必要です'}), 400
        try:
            supabase.table(TABLE_ENTRY_AP_CONFIG).upsert({'mac': mac, 'label': data.get('label', '')}).execute()
            return jsonify({'message': 'saved'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        data = request.json or {}
        mac = data.get('mac', '').strip()
        if not mac:
            return jsonify({'error': 'mac が必要です'}), 400
        try:
            supabase.table(TABLE_ENTRY_AP_CONFIG).delete().eq('mac', mac).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/entry_management', methods=['GET'])
@login_required
def get_entry_management():
    try:
        status_list = do_entry_status_update()
        return jsonify({'status': status_list})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/entry_log', methods=['GET'])
@login_required
def get_entry_log():
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
        start_utc, end_utc = jst_today_utc_bounds()
        res = (
            supabase.table(TABLE_ENTRY_LOG)
            .select("*")
            .gte("event_time", start_utc)
            .lt("event_time", end_utc)
            .order("event_time", desc=True)
            .limit(limit)
            .execute()
        )
        return jsonify(res.data or [])
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/debug/wifi_map")
@login_required
def debug_wifi_map():
    try:
        wifi_raw = supabase.table(TABLE_WIFI_REPORTS).select("*").execute()
        ap_raw   = supabase.table(TABLE_AP_POSITIONS).select("*").execute()
        ao_raw   = supabase.table(TABLE_AREA_STATUS).select("area_id, area_order").execute()

        wifi_reports = load_wifi_reports()
        ap_pos       = load_ap_positions()
        area_order   = load_area_order()

        return jsonify({
            "wifi_reports_raw":   wifi_raw.data,
            "ap_positions_raw":   ap_raw.data,
            "area_order_raw":     ao_raw.data,
            "load_wifi_reports":  wifi_reports,
            "load_ap_positions":  ap_pos,
            "load_area_order":    area_order,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)