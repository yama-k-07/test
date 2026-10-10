from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timezone, timedelta
import threading
import json
import os
import re
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
TABLE_AP_PRESETS = "ap_position_presets"
TABLE_DEVICE_INSTRUCTIONS = "device_instructions"
DEVICE_INSTRUCTIONS = {"none", "wait", "inward", "outward"}
TABLE_ENTRY_CURRENT = "entry_current"
TABLE_ENTRY_LOG = "entry_log"
# 火災位置（管理マップで指定。1行だけ: id=1）と、ウォッチごとの「自分から見た火災の方向」。
# スキーマは supabase/fire_location.sql。ウォッチは device_fire_alerts の自分の行を読む。
TABLE_FIRE_LOCATION = "fire_location"
TABLE_DEVICE_FIRE_ALERTS = "device_fire_alerts"

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


ONLINE_THRESHOLD_SEC = 60


_FRACTION_RE = re.compile(r'\.(\d+)')


def parse_ts(iso_str):
    """Supabase の timestamptz 文字列を aware datetime にする。失敗したら None。
    Python 3.10 の fromisoformat は小数秒が6桁以外（例 '.12345'）だと失敗するので6桁にそろえる。"""
    if not iso_str:
        return None
    try:
        s = iso_str.replace('Z', '+00:00')
        s = _FRACTION_RE.sub(lambda m: '.' + m.group(1)[:6].ljust(6, '0'), s, count=1)
        ts = datetime.fromisoformat(s)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts
    except (ValueError, TypeError, AttributeError):
        return None


def is_recent(iso_str, threshold_sec=ONLINE_THRESHOLD_SEC):
    """指定したISO日時文字列が現在時刻からthreshold_sec以内かどうか"""
    ts = parse_ts(iso_str)
    if ts is None:
        return False
    return (datetime.now(timezone.utc) - ts).total_seconds() <= threshold_sec


JST = timezone(timedelta(hours=9))


def jst_today_utc_bounds():
    """日本時間で「今日」の0時〜24時をUTCのISO文字列範囲で返す"""
    start_jst = datetime.now(JST).replace(hour=0, minute=0, second=0, microsecond=0)
    end_jst = start_jst + timedelta(days=1)
    return start_jst.astimezone(timezone.utc).isoformat(), end_jst.astimezone(timezone.utc).isoformat()


def load_device_instructions():
    try:
        response = supabase.table(TABLE_DEVICE_INSTRUCTIONS).select("*").execute()
        return response.data or []
    except Exception as e:
        print(f"Error loading device_instructions: {e}")
        return []


def sync_device_reports_from_wifi(reports):
    """wifi_reports.report を device_instructions.report に同期する
    （デバイス側の書き込み先移行が完了するまでの橋渡し）。
    値が実際に変化したデバイスだけ upsert し、device_id -> device_instructions行 の辞書を返す。"""
    instr_map = {d['device_id']: d for d in load_device_instructions() if d.get('device_id')}

    for row in (reports or []):
        device_id = row.get('device_id')
        if not device_id:
            continue
        wifi_report = bool(row.get('report'))
        current = instr_map.get(device_id)
        if current is not None and bool(current.get('report')) == wifi_report:
            continue
        try:
            supabase.table(TABLE_DEVICE_INSTRUCTIONS).upsert({
                'device_id': device_id,
                'report': wifi_report,
            }).execute()
            if current is not None:
                current['report'] = wifi_report
            else:
                instr_map[device_id] = {'device_id': device_id, 'instruction': 'none', 'report': wifi_report}
        except Exception as e:
            print(f"Error syncing report for {device_id}: {e}")

    return instr_map


def load_ap_presets():
    try:
        response = supabase.table(TABLE_AP_PRESETS).select("*").order("name").execute()
        return response.data or []
    except Exception as e:
        print(f"Error loading ap_position_presets: {e}")
        return []


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


# ==========================================
#  位置推定
# ==========================================
# ap_positions.position（位置番号 0〜5）ごとの表示名と、入口からの実距離[m]。
# 画面の説明「0=入口1m 〜 5=奥11m」とラベルの通り、APは等間隔ではない。
# AP を増減・移設したらここだけ直す（画面はこの値を /api/wifi_map から受け取って描く）。
AP_LABELS = ['1', '3', '4', '5', '6', '11']
AP_DISTANCES_M = [1.0, 3.0, 4.0, 5.0, 6.0, 11.0]
AP_COUNT = len(AP_LABELS)
TUNNEL_START_M = min(AP_DISTANCES_M)
TUNNEL_END_M = max(AP_DISTANCES_M)

# 平滑化: デバイスの最新レポートから遡って SMOOTHING_WINDOW_SEC 以内のレポートを
# 新しいほど重く（半減期 SMOOTHING_HALF_LIFE_SEC）まとめる。
# 重み付き中央値から OUTLIER_M 以上離れたサンプル（電波の一時的なブレ）は捨てる。
SMOOTHING_WINDOW_SEC = 30
SMOOTHING_HALF_LIFE_SEC = 8
SMOOTHING_MAX_SAMPLES = 8
OUTLIER_M = 5.0

# 1レポート内の重み。mac01 は最も電波の強いAP、mac02 は2番目（ウォッチ側の仕様）なので、
# 人は mac01 寄りにいる。値はシミュレーションで決めた（結果は SPEC.md §6.2）。
MAC01_WEIGHT = 0.8


def ap_distance_m(ap_pos, mac):
    """MAC に対応する AP の入口からの距離[m]。未登録・範囲外なら None"""
    pos = ap_pos.get(mac) if mac else None
    try:
        pos = int(pos)
    except (TypeError, ValueError):
        return None
    if not (0 <= pos < AP_COUNT):
        return None
    return AP_DISTANCES_M[pos]


def report_distance_m(row, ap_pos):
    """1レポート分の推定距離[m]。mac01（最強）と mac02（2番目）を MAC01_WEIGHT で内分、片方だけならその AP"""
    d1 = ap_distance_m(ap_pos, row.get('mac01'))
    d2 = ap_distance_m(ap_pos, row.get('mac02'))
    if d1 is not None and d2 is not None:
        return MAC01_WEIGHT * d1 + (1 - MAC01_WEIGHT) * d2
    return d1 if d1 is not None else d2


def to_ratio(distance_m):
    """距離[m] → マップ横軸の比率 0.0（入口側AP）〜 1.0（最奥AP）"""
    span = TUNNEL_END_M - TUNNEL_START_M
    if span <= 0:
        return 0.0
    return max(0.0, min(1.0, (distance_m - TUNNEL_START_M) / span))


def weighted_median(samples):
    """samples: [(value, weight)] の重み付き中央値"""
    ordered = sorted(samples)
    half = sum(w for _, w in ordered) / 2
    acc = 0.0
    for value, w in ordered:
        acc += w
        if acc >= half:
            return value
    return ordered[-1][0]


def smooth_distance_m(samples):
    """samples: [(distance_m, age_sec)]（age は最新レポートからの経過秒）→ 平滑化した距離[m]"""
    weighted = [(d, 0.5 ** (age / SMOOTHING_HALF_LIFE_SEC)) for d, age in samples]
    if len(weighted) == 1:
        return weighted[0][0]
    med = weighted_median(weighted)
    kept = [(d, w) for d, w in weighted if abs(d - med) <= OUTLIER_M]
    total = sum(w for _, w in kept)
    return sum(d * w for d, w in kept) / total


def load_recent_wifi_reports(window_sec=SMOOTHING_WINDOW_SEC * 2):
    """平滑化用に直近 window_sec 秒の wifi_reports を新しい順で返す"""
    since = (datetime.now(timezone.utc) - timedelta(seconds=window_sec)).isoformat()
    try:
        response = (
            supabase.table(TABLE_WIFI_LOG)
            .select("device_id, mac01, mac02, created_at")
            .gte("created_at", since)
            .order("id", desc=True)
            .limit(1000)
            .execute()
        )
        return response.data or []
    except Exception as e:
        print(f"Error loading recent wifi_reports: {e}")
        return []


def area_centers_m(area_rows, ap_pos):
    """エリア割当設定（area_status_v2.bssid）の AP が AP位置設定にあれば、その距離をエリアの中心とする"""
    centers = {}
    for row in (area_rows or []):
        d = ap_distance_m(ap_pos, row.get('bssid'))
        if row.get('area_id') and d is not None:
            centers[row['area_id']] = d
    return centers


def build_area_layout(area_order, centers):
    """マップ上のエリア区間 [{area_id, start, end}]（比率）。
    全エリアに中心があれば中心間の中点で区切る（＝最寄りのエリアに割り当て）。無ければ従来どおり等分。"""
    n = len(area_order)
    if n == 0:
        return []
    if all(a in centers for a in area_order):
        ordered = sorted(area_order, key=lambda a: centers[a])
        layout = []
        for i, a in enumerate(ordered):
            start = 0.0 if i == 0 else to_ratio((centers[ordered[i - 1]] + centers[a]) / 2)
            end = 1.0 if i == n - 1 else to_ratio((centers[a] + centers[ordered[i + 1]]) / 2)
            layout.append({'area_id': a, 'start': round(start, 4), 'end': round(end, 4)})
        return layout
    return [{'area_id': a, 'start': round(i / n, 4), 'end': round((i + 1) / n, 4)} for i, a in enumerate(area_order)]


def area_for_ratio(layout, ratio):
    for seg in layout:
        if ratio < seg['end']:
            return seg['area_id']
    return layout[-1]['area_id'] if layout else None


def estimate_positions(latest_reports, ap_pos, area_order, area_rows):
    """デバイスごとの推定位置を返す。
    戻り値: (positions, layout)
      positions: {device_id: {'distance_m', 'ratio', 'area_id', 'samples', 'approx'}}（推定できないデバイスは含まない）
        approx=True は AP位置設定では位置が出せず、エリア割当の BSSID 一致だけで決めたもの（ratio はエリアの中央）
      layout: build_area_layout の結果

    エリアの決め方（上ほど優先）:
      1. 全エリアの BSSID が AP位置設定にある → 平滑化した距離に最も近いエリア
      2. 最新レポートの mac01 / mac02 がエリア割当の BSSID と一致 → そのエリア（従来のエリアボードの方式）
      3. 平滑化した距離でトンネルを等分したエリア（従来のトンネルマップの方式）"""
    centers = area_centers_m(area_rows, ap_pos)
    layout = build_area_layout(area_order, centers)
    centered = bool(layout) and all(a in centers for a in area_order)
    bssid_area = {row['bssid']: row['area_id'] for row in (area_rows or []) if row.get('bssid') and row.get('area_id')}
    segment = {seg['area_id']: seg for seg in layout}

    history = {}
    for row in load_recent_wifi_reports():
        did = row.get('device_id')
        if did:
            history.setdefault(did, []).append(row)

    positions = {}
    for latest in (latest_reports or []):
        did = latest.get('device_id')
        if not did:
            continue
        latest_ts = parse_ts(latest.get('created_at'))

        rows = history.get(did) or [latest]
        samples = []
        for row in rows[:SMOOTHING_MAX_SAMPLES]:
            d = report_distance_m(row, ap_pos)
            if d is None:
                continue
            ts = parse_ts(row.get('created_at'))
            age = (latest_ts - ts).total_seconds() if (latest_ts and ts) else 0.0
            if age < 0 or age > SMOOTHING_WINDOW_SEC:
                continue
            samples.append((d, age))

        direct_area = bssid_area.get(latest.get('mac01')) or bssid_area.get(latest.get('mac02'))

        # 最新レポートで AP が分からない時に、古い位置で表示し続けない
        if report_distance_m(latest, ap_pos) is None or not samples:
            seg = segment.get(direct_area)
            if seg is None:
                continue
            positions[did] = {
                'distance_m': None,
                'ratio': round((seg['start'] + seg['end']) / 2, 4),
                'area_id': direct_area,
                'samples': 0,
                'approx': True,
            }
            continue

        distance = smooth_distance_m(samples)
        ratio = to_ratio(distance)
        if centered or not direct_area:
            area_id = area_for_ratio(layout, ratio)
        else:
            area_id = direct_area
        positions[did] = {
            'distance_m': round(distance, 2),
            'ratio': round(ratio, 4),
            'area_id': area_id,
            'samples': len(samples),
            'approx': False,
        }
    return positions, layout


# ==========================================
#  火災位置
# ==========================================
# 火災までの距離がこれ以内なら「すぐ近く」（位置推定の誤差が約1〜2mのため）
FIRE_NEAR_M = 2.0


def ratio_to_distance_m(ratio):
    return TUNNEL_START_M + max(0.0, min(1.0, ratio)) * (TUNNEL_END_M - TUNNEL_START_M)


def load_fire_location():
    """{'active': bool, 'distance_m': float|None, 'updated_at'}。テーブルが無い・未設定なら active=False"""
    try:
        res = supabase.table(TABLE_FIRE_LOCATION).select("*").eq("id", 1).execute()
        row = (res.data or [None])[0]
    except Exception as e:
        print(f"Error loading fire_location: {e}")
        row = None
    if not row or not row.get('active') or row.get('distance_m') is None:
        return {'active': False, 'distance_m': None, 'updated_at': (row or {}).get('updated_at')}
    return {'active': True, 'distance_m': float(row['distance_m']), 'updated_at': row.get('updated_at')}


def fire_relation(worker_m, fire_m):
    """作業者から見た火災の方向と距離。
    direction: 'inward'（奥側）/ 'outward'（入口側）/ 'near'（すぐ近く）"""
    diff = fire_m - worker_m
    distance = round(abs(diff), 1)
    if abs(diff) <= FIRE_NEAR_M:
        return 'near', distance, f"火災: すぐ近く（約{distance:.0f}m）"
    if diff > 0:
        return 'inward', distance, f"火災: 奥 約{distance:.0f}m"
    return 'outward', distance, f"火災: 手前 約{distance:.0f}m"


def build_fire_alerts(device_ids, positions, fire):
    """device_fire_alerts に書く行 {device_id: row}。
    位置が分からないデバイスは direction='unknown'（火災が出ていることだけ知らせる）"""
    alerts = {}
    for did in device_ids:
        row = {
            'device_id': did,
            'fire_active': fire['active'],
            'direction': None,
            'distance_m': None,
            'message': None,
            'approx': False,
        }
        if fire['active']:
            pos = positions.get(did)
            if pos is None:
                row.update(direction='unknown', message='火災発生: 位置不明。管理者の指示に従ってください')
            else:
                worker_m = pos['distance_m'] if pos['distance_m'] is not None else ratio_to_distance_m(pos['ratio'])
                direction, distance, message = fire_relation(worker_m, fire['distance_m'])
                row.update(direction=direction, distance_m=distance, message=message, approx=bool(pos['approx']))
        alerts[did] = row
    return alerts


_ALERT_KEYS = ('fire_active', 'direction', 'distance_m', 'message', 'approx')


def sync_device_fire_alerts(alerts):
    """内容が変わったデバイスの行だけ upsert する（5秒ごとに呼ばれるため）"""
    if not alerts:
        return
    try:
        res = supabase.table(TABLE_DEVICE_FIRE_ALERTS).select("*").execute()
        current = {r['device_id']: r for r in (res.data or []) if r.get('device_id')}
    except Exception as e:
        print(f"Error loading device_fire_alerts: {e}")
        return

    changed = []
    for did, row in alerts.items():
        cur = current.get(did)
        if cur is not None and all(cur.get(k) == row[k] for k in _ALERT_KEYS):
            continue
        changed.append({**row, 'updated_at': now_iso()})
    if not changed:
        return
    try:
        supabase.table(TABLE_DEVICE_FIRE_ALERTS).upsert(changed).execute()
    except Exception as e:
        print(f"Error syncing device_fire_alerts: {e}")


def update_fire_alerts(reports, positions, fire):
    """最新レポートのある全デバイスと登録ユーザーの device_fire_alerts を最新化し、alerts を返す"""
    device_ids = {r.get('device_id') for r in (reports or []) if r.get('device_id')}
    device_ids |= {u.get('device_id') for u in (load_user_table() or []) if u.get('device_id')}
    alerts = build_fire_alerts(sorted(device_ids), positions, fire)
    sync_device_fire_alerts(alerts)
    return alerts


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
    return render_template(
        "index.html",
        supabase_url=url,
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY", ""),
    )


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


@app.route('/api/ap_presets', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_ap_presets():
    if request.method == 'GET':
        return jsonify(load_ap_presets())

    data = request.json or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'プリセット名を指定してください'}), 400

    if request.method == 'POST':
        positions = data.get('positions')
        if not isinstance(positions, list) or not positions:
            return jsonify({'error': 'positions（AP設定の配列）が必要です'}), 400
        for item in positions:
            if 'mac' not in item or 'position' not in item:
                return jsonify({'error': '各要素に mac と position が必要です'}), 400
        try:
            supabase.table(TABLE_AP_PRESETS).upsert({
                'name': name,
                'positions': positions,
                'updated_at': now_iso(),
            }).execute()
            return jsonify({'message': 'AP preset saved'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    else:
        try:
            supabase.table(TABLE_AP_PRESETS).delete().eq('name', name).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500


@app.route('/api/wifi_map', methods=['GET'])
@login_required
def get_wifi_map():
    reports = load_wifi_reports()
    ap_pos = load_ap_positions()
    area_order = load_area_order()
    positions, layout = estimate_positions(reports, ap_pos, area_order, load_area_table())

    user_map = {u['device_id']: u['username'] for u in (load_user_table() or []) if u.get('device_id') and u.get('username')}
    instruction_map = sync_device_reports_from_wifi(reports)

    online_device_ids = sorted({
        row.get('device_id') for row in (reports or [])
        if row.get('device_id') and is_recent(row.get('created_at'))
    })
    online_set = set(online_device_ids)

    # 火災位置が出ていれば、各ウォッチ向けの「自分から見た火災の方向」を更新する
    fire = load_fire_location()
    alerts = update_fire_alerts(reports, positions, fire)

    workers = []
    for row in (reports or []):
        device_id = row.get('device_id')
        pos = positions.get(device_id)
        if pos is None:
            continue
        alert = alerts.get(device_id) or {}
        workers.append({
            'device_id': device_id,
            'username': user_map.get(device_id),
            'report': bool(instruction_map.get(device_id, {}).get('report')),
            'ratio': pos['ratio'],
            'distance_m': pos['distance_m'],
            'area_id': pos['area_id'],
            'approx': pos['approx'],
            'online': device_id in online_set,
            'fire_message': alert.get('message'),
        })

    return jsonify({
        'workers': workers,
        'ap_count': AP_COUNT,
        'ap_labels': AP_LABELS,
        'ap_markers': [
            {'label': label, 'distance_m': d, 'ratio': round(to_ratio(d), 4)}
            for label, d in zip(AP_LABELS, AP_DISTANCES_M)
        ],
        'area_order': area_order,
        'area_layout': layout,
        'online_device_ids': online_device_ids,
        'fire': {
            'active': fire['active'],
            'distance_m': fire['distance_m'],
            'ratio': round(to_ratio(fire['distance_m']), 4) if fire['active'] else None,
        },
    })


@app.route('/api/fire_location', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_fire_location():
    """管理マップで指定した火災位置。POST {ratio}（マップ横軸 0〜1）か {distance_m}、DELETE で解除。
    保存後すぐに各ウォッチ向けの device_fire_alerts も更新する"""
    if request.method == 'GET':
        return jsonify(load_fire_location())

    if request.method == 'POST':
        data = request.json or {}
        try:
            if data.get('distance_m') is not None:
                distance = float(data['distance_m'])
            else:
                distance = ratio_to_distance_m(float(data['ratio']))
        except (KeyError, TypeError, ValueError):
            return jsonify({'error': 'ratio（0〜1）か distance_m を数値で指定してください'}), 400
        distance = round(max(TUNNEL_START_M, min(TUNNEL_END_M, distance)), 1)
        payload = {'id': 1, 'active': True, 'distance_m': distance, 'updated_at': now_iso()}
    else:
        payload = {'id': 1, 'active': False, 'distance_m': None, 'updated_at': now_iso()}

    try:
        supabase.table(TABLE_FIRE_LOCATION).upsert(payload).execute()
    except Exception as e:
        return jsonify({'error': f'火災位置の保存に失敗しました（supabase/fire_location.sql は実行済みですか？）: {e}'}), 500

    reports = load_wifi_reports()
    positions, _ = estimate_positions(reports, load_ap_positions(), load_area_order(), load_area_table())
    update_fire_alerts(reports, positions, load_fire_location())
    return jsonify({'message': 'fire location saved', 'fire': load_fire_location()})


@app.route('/api/device_instructions', methods=['GET', 'POST'])
@login_required
def handle_device_instructions():
    if request.method == 'GET':
        return jsonify(load_device_instructions())

    data = request.json or {}
    device_id = data.get('device_id')
    instruction = data.get('instruction')

    if not device_id:
        return jsonify({'error': 'device_id を指定してください'}), 400
    if instruction not in DEVICE_INSTRUCTIONS:
        return jsonify({'error': f'instruction は {sorted(DEVICE_INSTRUCTIONS)} のいずれかである必要があります'}), 400

    payload = {
        'device_id': device_id,
        'instruction': instruction,
        'updated_at': now_iso(),
    }
    if 'report' in data:
        payload['report'] = bool(data.get('report'))

    try:
        supabase.table(TABLE_DEVICE_INSTRUCTIONS).upsert(payload).execute()
        return jsonify({'message': 'device instruction saved'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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
    """エリアボード用。トンネルマップ（/api/wifi_map）と同じ estimate_positions でエリアを決める"""
    dev_info = load_wifi_reports() or []

    try:
        positions, _ = estimate_positions(dev_info, load_ap_positions(), load_area_order(), load_area_table())

        user_dict = {}
        for item in (load_user_table() or []):
            device_id = item.get("device_id")
            if device_id is not None:
                user_dict[device_id] = item.get("username")

        output = []
        for item in dev_info:
            device_id = item.get("device_id")
            output.append({
                "area_id": (positions.get(device_id) or {}).get("area_id"),
                "username": user_dict.get(device_id),
                "device_id": device_id,
            })

        return jsonify(output), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/test-deploy")
def test_deploy():
    return "DEPLOYED-V3-POST-OK"


def do_entry_status_update():
    """AP位置設定(ap_positions)に登録されたAPのいずれかと接続中は入場中、
    そのどれとも接続できなくなったら退場とみなして entry_current / entry_log を更新する"""
    ap_pos = load_ap_positions()
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
        at_entry = bool(ap_pos) and (mac1 in ap_pos or mac2 in ap_pos)

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