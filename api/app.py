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

TABLE_ACCESS_POINT = "access_point"
TABLE_AREA = "area"
TABLE_AREA_STATUS = "area_statuses"

entry_status_table = []
last_seen_dict = {}

# ==========================================
#  Supabase 連携データ処理関数
# ==========================================

def load_ssid_table():
    try:
        response = supabase.table(TABLE_ACCESS_POINT).select("*").execute()
        return response.data
    except Exception as e:
        print(f"Error loading SSID table: {e}")
        return []


def load_area_table():
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


@app.route("/chkwifi", methods=["GET", "POST"])
@login_required
def admin_wifi():
    if request.method == "POST":
        ssid = request.form.get("ssid")
        password = request.form.get("password")
        if ssid and password:
            new_entry = {"area_id": "any", "ssid": ssid, "password": password}
            try:
                supabase.table(TABLE_ACCESS_POINT).upsert(new_entry).execute()
            except Exception as e:
                print(f"Error saving Wi-Fi to Supabase: {e}")
        return redirect(url_for("admin_wifi"))

    wifi_data = get_wifi_credentials()
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
    

@app.route('/api/ssid', methods=['DELETE'])
def delete_ssid():
    data = request.json or {}
    target_ssid = data.get('ssid')
    if not target_ssid:
        return jsonify({'error': 'ssid を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するSSIDの行を削除
        supabase.table(TABLE_ACCESS_POINT).delete().eq("ssid", target_ssid).execute()
        return jsonify({'message': 'deleted from Supabase', 'ssid_table': load_ssid_table()})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500


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
    

@app.route('/api/area', methods=['DELETE'])
def delete_area():
    data = request.json or {}
    target_area = data.get('area_id')
    if not target_area:
        return jsonify({'error': 'area_id を指定してください'}), 400

    try:
        # Supabaseのテーブルから、該当するarea_idの行を削除
        supabase.table(TABLE_AREA).delete().eq("area_id", target_area).execute()
        return jsonify({'message': 'deleted from Supabase', 'area_table': load_area_table()})
    except Exception as e:
        return jsonify({'error': f'Supabaseからの削除に失敗しました: {str(e)}'}), 500
    




@app.route("/test-deploy")
def test_deploy():
    return "DEPLOYED-V3-POST-OK"

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)