from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from functools import wraps
import os
import time

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = "mamotchi_secret_key_pixel"

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client | None = create_client(url, key) if url and key else None

TABLE_AP_AREA = "ap_areas"
TABLE_AREA_STATUS = "area_status"
TABLE_AREA_ORDER = "area_order"
TABLE_USER = "user"
TABLE_WIFI_REPORTS = "wifi_reports"
TABLE_AP_POSITIONS = "ap_positions"

entry_status_table = []
last_seen_dict = {}
ap_position_map = {}
area_order_list = []
area_status_store = []


# ==========================================
#  共通ヘルパー
# ==========================================
def load_supabase_table(table_name: str):
    if supabase is None:
        return []
    try:
        response = supabase.table(table_name).select("*").execute()
        return response.data or []
    except Exception as exc:
        print(f"Error loading table {table_name}: {exc}")
        return []


def load_wifi_reports():
    if supabase is None:
        return {}
    try:
        response = supabase.table(TABLE_WIFI_REPORTS).select("*").execute()
        result = {}
        for row in response.data or []:
            device_id = row.get("device_id")
            if device_id:
                result[device_id] = {
                    "username": row.get("username"),
                    "report": row.get("report"),
                    "mac01": row.get("mac01"),
                    "mac02": row.get("mac02"),
                }
        return result
    except Exception as exc:
        print(f"Error loading wifi reports: {exc}")
        return {}


def load_ap_positions():
    if supabase is None:
        return dict(ap_position_map)
    try:
        response = supabase.table(TABLE_AP_POSITIONS).select("*").execute()
        items = response.data or []
        result = {str(item.get("mac")): int(item.get("position", 0)) for item in items if item.get("mac") is not None}
        ap_position_map.clear()
        ap_position_map.update(result)
        return result
    except Exception:
        return dict(ap_position_map)


def load_area_order():
    if supabase is None:
        return list(area_order_list)
    try:
        response = supabase.table(TABLE_AREA_ORDER).select("*").execute()
        rows = response.data or []
        ordered = [row.get("area_id") for row in sorted(rows, key=lambda item: item.get("sort_order", 0)) if row.get("area_id")]
        area_order_list[:] = ordered
        return ordered
    except Exception:
        return list(area_order_list)


# ==========================================
#  認証用デコレータ
# ==========================================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login_page"))
        return f(*args, **kwargs)

    return decorated_function


@app.route("/")
def login_page():
    if session.get("logged_in"):
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.route("/index")
@login_required
def index():
    return render_template("index.html")


@app.route("/api/login_mock", methods=["POST"])
def login_mock():
    session["logged_in"] = True
    return jsonify({"status": "success", "redirect": url_for("index")})


@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login_page"))


# ==========================================
#  API: エリア状態
# ==========================================
@app.route("/api/area_status", methods=["GET", "POST"])
def handle_area_status():
    global area_status_store

    if request.method == "POST":
        payload = request.json or []
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return jsonify({"error": "リスト形式でデータを送ってください"}), 400

        normalized = []
        for item in payload:
            if not isinstance(item, dict) or not item.get("area_id"):
                return jsonify({"error": "各要素に area_id が必要です"}), 400
            normalized.append({
                "area_id": item.get("area_id"),
                "instruction": item.get("instruction", "none"),
                "fire": bool(item.get("fire", False)),
            })

        for incoming in normalized:
            existing = next((item for item in area_status_store if item.get("area_id") == incoming.get("area_id")), None)
            if existing is None:
                area_status_store.append(incoming)
            else:
                existing.update(incoming)

        if supabase is not None:
            try:
                supabase.table(TABLE_AREA_STATUS).upsert(normalized).execute()
            except Exception as exc:
                print(f"Error updating area status: {exc}")

        return jsonify({"message": "area status updated", "area_status": area_status_store})

    if area_status_store:
        return jsonify(area_status_store)

    response = load_supabase_table(TABLE_AREA_STATUS)
    area_status_store = response
    return jsonify(response)


# ==========================================
#  API: ユーザー / デバイス
# ==========================================
@app.route("/api/ssid", methods=["GET", "POST", "DELETE"])
def handle_ssid():
    if request.method == "POST":
        data = request.json or {}
        payload = dict(data)

        if "username" not in payload and "ssid" in payload:
            payload["username"] = payload["ssid"]
        if "device_id" not in payload and "password" in payload:
            payload["device_id"] = payload["password"]

        username = payload.get("username") or payload.get("ssid")
        device_id = payload.get("device_id") or payload.get("password")
        if not username and not device_id:
            return jsonify({"error": "username または device_id が必要です"}), 400

        try:
            if supabase is not None:
                supabase.table(TABLE_USER).upsert({
                    "username": username,
                    "device_id": device_id,
                }).execute()
        except Exception as exc:
            print(f"Error saving user to Supabase: {exc}")

        if device_id:
            last_seen_dict[device_id] = time.time()
        return jsonify({"message": "user updated"})

    if request.method == "DELETE":
        data = request.json or {}
        target = data.get("username") or data.get("ssid") or data.get("device_id")
        if not target:
            return jsonify({"error": "username を指定してください"}), 400
        try:
            if supabase is not None:
                supabase.table(TABLE_USER).delete().eq("username", target).execute()
            return jsonify({"message": "deleted from Supabase", "user_table": load_supabase_table(TABLE_USER)})
        except Exception as exc:
            return jsonify({"error": f"Supabaseからの削除に失敗しました: {str(exc)}"}), 500

    return jsonify(load_supabase_table(TABLE_USER))


# ==========================================
#  API: エリア割当
# ==========================================
@app.route("/api/area", methods=["GET", "POST", "DELETE"])
def handle_area():
    if request.method == "POST":
        data = request.json or {}
        area_id = data.get("area_id")
        bssid = data.get("bssid") or data.get("gateway")
        if not area_id or not bssid:
            return jsonify({"error": "area_id と bssid が必要です"}), 400
        try:
            if supabase is not None:
                supabase.table(TABLE_AP_AREA).upsert({"area_id": area_id, "bssid": bssid}).execute()
            return jsonify({"message": "Area master updated in Supabase"})
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    if request.method == "DELETE":
        data = request.json or {}
        target_area = data.get("bssid") or data.get("gateway") or data.get("area_id")
        if not target_area:
            return jsonify({"error": "bssid または area_id を指定してください"}), 400
        try:
            if supabase is not None:
                supabase.table(TABLE_AP_AREA).delete().eq("bssid", target_area).execute()
            return jsonify({"message": "deleted from Supabase", "area_table": load_supabase_table(TABLE_AP_AREA)})
        except Exception as exc:
            return jsonify({"error": f"Supabaseからの削除に失敗しました: {str(exc)}"}), 500

    return jsonify(load_supabase_table(TABLE_AP_AREA))


# ==========================================
#  API: 入場状態
# ==========================================
@app.route("/api/entry_status", methods=["GET"])
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
        if entry.get("device_id") in valid_ids
    ]

    if active_entries:
        return jsonify(active_entries)

    if supabase is not None:
        try:
            response = supabase.table(TABLE_USER).select("username, device_id").execute()
            fallback = []
            for row in response.data or []:
                if row.get("device_id") or row.get("username"):
                    fallback.append({
                        "device_id": row.get("device_id", ""),
                        "username": row.get("username", ""),
                        "area_id": "",
                    })
            return jsonify(fallback)
        except Exception as exc:
            return jsonify({"error": str(exc)}), 500

    return jsonify([])


# ==========================================
#  API: エリア順序
# ==========================================
@app.route("/api/area_order", methods=["GET", "POST"])
def handle_area_order():
    global area_order_list
    if request.method == "POST":
        data = request.json or []
        if isinstance(data, dict):
            data = data.get("order") or []
        if isinstance(data, list):
            area_order_list = [item for item in data if item]
        else:
            return jsonify({"error": "配列形式で送ってください"}), 400

        if supabase is not None:
            try:
                records = [{"area_id": area_id, "sort_order": index} for index, area_id in enumerate(area_order_list)]
                supabase.table(TABLE_AREA_ORDER).upsert(records).execute()
            except Exception as exc:
                print(f"Error saving area order: {exc}")

        return jsonify({"message": "area order saved", "order": area_order_list})

    return jsonify(load_area_order())


# ==========================================
#  API: AP 位置
# ==========================================
@app.route("/api/ap_positions", methods=["GET", "POST", "DELETE"])
def handle_ap_positions():
    global ap_position_map

    if request.method == "GET":
        positions = load_ap_positions()
        return jsonify([{"mac": mac, "position": pos} for mac, pos in positions.items()])

    if request.method == "POST":
        data = request.json or {}
        mac = data.get("mac")
        position = data.get("position")
        if not mac or position is None:
            return jsonify({"error": "mac と position が必要です"}), 400
        ap_position_map[str(mac)] = int(position)
        if supabase is not None:
            try:
                supabase.table(TABLE_AP_POSITIONS).upsert({"mac": str(mac), "position": int(position)}).execute()
            except Exception as exc:
                print(f"Error saving AP positions: {exc}")
        return jsonify({"message": "AP position saved"})

    data = request.json or {}
    mac = data.get("mac")
    if not mac:
        return jsonify({"error": "mac を指定してください"}), 400
    ap_position_map.pop(str(mac), None)
    if supabase is not None:
        try:
            supabase.table(TABLE_AP_POSITIONS).delete().eq("mac", str(mac)).execute()
        except Exception as exc:
            print(f"Error deleting AP position: {exc}")
    return jsonify({"message": "deleted"})


# ==========================================
#  API: Wi-Fi マップ
# ==========================================
@app.route("/api/wifi_map", methods=["GET"])
def get_wifi_map():
    reports = load_wifi_reports()
    ap_positions = load_ap_positions()
    order = load_area_order()

    workers = []
    for device_id, info in reports.items():
        mac1 = info.get("mac01")
        mac2 = info.get("mac02")
        pos1 = ap_positions.get(mac1)
        pos2 = ap_positions.get(mac2)

        if pos1 is None:
            continue

        ratio = pos1 / 4 if pos1 is not None else 0
        if pos2 is not None:
            ratio = round((ratio + pos2 / 4) / 2, 4)

        if order:
            area_id = order[min(int(ratio * len(order)), len(order) - 1)]
        else:
            area_id = None

        workers.append({
            "device_id": device_id,
            "username": info.get("username"),
            "report": info.get("report"),
            "ratio": ratio,
            "area_id": area_id,
        })

    return jsonify({"workers": workers, "ap_count": 5, "area_order": order})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
