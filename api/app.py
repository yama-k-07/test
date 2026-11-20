from flask import Flask, Response, request, jsonify, render_template, redirect, url_for, session
from supabase import create_client, Client
from dotenv import load_dotenv
from functools import wraps
from datetime import datetime, timezone, timedelta
import threading
import hmac
import math
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
# ESP32-S3 で作った AP（firmware/esp32s3_ap）。heartbeat で自動登録され、距離は管理画面で設定する。
# スキーマは supabase/ap_nodes.sql。
TABLE_AP_NODES = "ap_nodes"
# ESP32 カメラ（firmware/esp32cam_uplink）。スキーマと Storage バケットは supabase/cameras.sql。
TABLE_CAMERAS = "cameras"
# ウォッチのスキャン結果（RSSI 上位3つの MAC と RSSI）。Wi-Fi と BLE で別テーブル。
# 位置推定の方式の設定（1行だけ: id=1）と、現地での比較記録。スキーマは supabase/scan_reports.sql。
TABLE_WIFI_SCAN = "wifi_reports_v2"
TABLE_BLE_SCAN = "ble_reports"
TABLE_POSITION_SETTINGS = "position_settings"
TABLE_POSITION_EVAL = "position_eval"
# AP の区間（0〜100m など）ごとのまとめた指示と、各ウォッチに最後に送った区間の指示。
# 区間の指示は device_instructions（個別指示）として送るので、ウォッチ側は変わらない。スキーマは supabase/segment_instructions.sql。
TABLE_SEGMENT_INSTRUCTIONS = "segment_instructions"
TABLE_DEVICE_SEGMENT_STATE = "device_segment_state"

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


def load_ap_position_rows():
    """AP位置設定（現場の Wi-Fi AP）の行。各行に distance_m（入口からの距離）と label を入れて返す。
    distance_m 列（supabase/ap_positions_distance.sql）が空・無い行は、位置番号 0〜5 なら AP_DISTANCES_M の値。
    位置番号 6 以降で距離が無い行は distance_m=None（位置推定に使わない）"""
    try:
        rows = supabase.table(TABLE_AP_POSITIONS).select("*").execute().data or []
    except Exception as e:
        print(f"Error loading ap_positions: {e}")
        return []
    out = []
    for row in rows:
        try:
            pos = int(row.get('position'))
        except (TypeError, ValueError):
            continue
        d = row.get('distance_m')
        if not isinstance(d, (int, float)):
            d = AP_DISTANCES_M[pos] if 0 <= pos < AP_COUNT else None
        out.append(dict(row, position=pos, distance_m=(float(d) if d is not None else None),
                        label=ap_position_label(pos)))
    return sorted(out, key=lambda r: r['position'])


def ap_position_label(pos):
    """位置番号 → 表示名。0〜5 は既設の AP の名前（AP1, AP3, …, AP11）、6 以降は「AP#7」のように番号＋1"""
    return f"AP{AP_LABELS[pos]}" if 0 <= pos < AP_COUNT else f"AP#{pos + 1}"


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
#  AP の配置（AP位置設定 ＋ ESP32 AP）
# ==========================================
# AP位置設定（ap_positions）の位置番号 0〜5 ごとの表示名（AP の名前。距離ではない）と、入口からの距離[m]。
# 実機トンネルは入口の AP1=0m から 100m 間隔で AP11=500m。
# admin.js の AP_LABELS / AP_POSITION_DISTANCES_M は AP位置設定のプルダウン表示用なので合わせて直す。
# ESP32 AP（ap_nodes）は AP ごとに distance_m を持つので、台数・間隔はここに縛られない。
AP_LABELS = ['1', '3', '4', '5', '6', '11']
AP_DISTANCES_M = [0.0, 100.0, 200.0, 300.0, 400.0, 500.0]
AP_COUNT = len(AP_LABELS)

# ESP32 AP の heartbeat がこの秒数届かなければ「停止」とみなす（firmware は 30 秒ごとに送る）
AP_NODE_ONLINE_SEC = 90


def norm_mac(mac):
    """MAC を比較用にそろえる（前後の空白を除いて大文字）。空なら空文字"""
    return str(mac).strip().upper() if mac else ""


class ApMap:
    """MAC → AP（入口からの距離・表示名・種類）と、そこから決まるトンネルの形。
    トンネルの両端は最も手前と最も奥の AP、AP 間隔は隣り合う AP の間隔の中央値。
    外れ値・「すぐ近く」の閾値は AP 間隔の倍数なので、ESP32 AP を増やして間隔を詰めれば自動で細かくなる。"""

    def __init__(self, entries):
        # entries: {mac: {'distance_m': float, 'label': str, 'source': 'manual'|'esp', 'online': bool|None}}
        # MAC は大文字小文字を区別しない（Android の BSSID は小文字、ESP32 は大文字で報告する）
        self.entries = {norm_mac(m): e for m, e in entries.items() if norm_mac(m)}
        # 同じ AP が大文字・小文字の両方で入っていたら後の方（load_ap_map では ESP32 AP）が残る
        ds = sorted({e['distance_m'] for e in self.entries.values()}) or list(AP_DISTANCES_M)
        self.start = ds[0]
        self.end = ds[-1]
        gaps = sorted(b - a for a, b in zip(ds, ds[1:]) if b - a > 0)
        default_gap = AP_DISTANCES_M[1] - AP_DISTANCES_M[0]
        self.spacing = gaps[len(gaps) // 2] if gaps else default_gap

    def __contains__(self, mac):
        return norm_mac(mac) in self.entries

    def __bool__(self):
        return bool(self.entries)

    def distance(self, mac):
        e = self.entries.get(norm_mac(mac))
        return e['distance_m'] if e else None

    def to_ratio(self, distance_m):
        """距離[m] → マップ横軸の比率 0.0（最も手前の AP）〜 1.0（最も奥の AP）"""
        span = self.end - self.start
        if span <= 0:
            return 0.0
        return max(0.0, min(1.0, (distance_m - self.start) / span))

    def from_ratio(self, ratio):
        return self.start + max(0.0, min(1.0, ratio)) * (self.end - self.start)

    def clamp(self, distance_m):
        return max(self.start, min(self.end, distance_m))

    @property
    def outlier_m(self):
        return OUTLIER_SPACINGS * self.spacing

    @property
    def near_m(self):
        return FIRE_NEAR_SPACINGS * self.spacing

    def markers(self):
        """マップ下端に描く AP。同じ距離の AP は1つにまとめる。
        status: 'online' / 'offline'（ESP32 AP の heartbeat 途絶）/ 'manual'（AP位置設定。死活は分からない）"""
        by_distance = {}
        for e in self.entries.values():
            by_distance.setdefault(e['distance_m'], []).append(e)
        out = []
        for d in sorted(by_distance):
            group = by_distance[d]
            esp = [e for e in group if e['source'] == 'esp']
            if esp:
                status = 'online' if any(e['online'] for e in esp) else 'offline'
            else:
                status = 'manual'
            out.append({
                'label': '/'.join(dict.fromkeys(e['label'] for e in group)),
                'distance_m': d,
                'ratio': round(self.to_ratio(d), 4),
                'status': status,
            })
        return out


def load_ap_nodes():
    """ESP32 AP の一覧（ap_nodes）。テーブルが無ければ空"""
    try:
        res = supabase.table(TABLE_AP_NODES).select("*").execute()
        return res.data or []
    except Exception as e:
        print(f"Error loading ap_nodes: {e}")
        return []


def load_ap_map():
    """AP位置設定（ap_positions、現場の Wi-Fi AP。距離は distance_m か位置番号から）と
    ESP32 AP（ap_nodes, 距離を直接持つ）を合わせた ApMap。
    同じ MAC が両方にあれば ESP32 AP の設定を優先する。距離未設定・無効の AP は位置推定に使わない。"""
    entries = {}
    for row in load_ap_position_rows():
        if row.get('mac') and row.get('distance_m') is not None:
            entries[row['mac']] = {'distance_m': row['distance_m'], 'label': row['label'],
                                   'source': 'manual', 'online': None}
    for node in load_ap_nodes():
        mac = node.get('mac')
        if not mac or node.get('enabled') is False or node.get('distance_m') is None:
            continue
        entries[mac] = {
            'distance_m': float(node['distance_m']),
            'label': node.get('label') or mac[-5:],
            'source': 'esp',
            'online': is_recent(node.get('last_seen'), AP_NODE_ONLINE_SEC),
        }
    return ApMap(entries)


# ==========================================
#  位置推定
# ==========================================
# 平滑化: デバイスの最新レポートから遡って SMOOTHING_WINDOW_SEC 以内のレポートを
# 新しいほど重く（半減期 SMOOTHING_HALF_LIFE_SEC）まとめる。
# 重み付き中央値から「AP 間隔 × OUTLIER_SPACINGS」以上離れたサンプル（AP を飛び越える電波のブレ）は捨てる。
SMOOTHING_WINDOW_SEC = 30
SMOOTHING_HALF_LIFE_SEC = 8
SMOOTHING_MAX_SAMPLES = 8
OUTLIER_SPACINGS = 1.5

# 1レポート内の重み。mac01 は最も電波の強いAP、mac02 は2番目（ウォッチ側の仕様）なので、
# 人は mac01 寄りにいる。値はシミュレーションで決めた（結果は SPEC.md §10）。
MAC01_WEIGHT = 0.8


def report_distance_m(row, ap_map):
    """1レポート分の推定距離[m]。mac01（最強）と mac02（2番目）を MAC01_WEIGHT で内分、片方だけならその AP"""
    d1 = ap_map.distance(row.get('mac01'))
    d2 = ap_map.distance(row.get('mac02'))
    if d1 is not None and d2 is not None:
        return MAC01_WEIGHT * d1 + (1 - MAC01_WEIGHT) * d2
    return d1 if d1 is not None else d2


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


def smooth_distance_m(samples, outlier_m):
    """samples: [(distance_m, age_sec)] または [(distance_m, age_sec, weight)]
    （age は最新レポートからの経過秒、weight は Wi-Fi / BLE の比重）→ 平滑化した距離[m]"""
    weighted = [(x[0], (x[2] if len(x) > 2 else 1.0) * 0.5 ** (x[1] / SMOOTHING_HALF_LIFE_SEC)) for x in samples]
    if len(weighted) == 1:
        return weighted[0][0]
    med = weighted_median(weighted)
    kept = [(d, w) for d, w in weighted if abs(d - med) <= outlier_m]
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


# ==========================================
#  位置推定の方式（①〜④）
# ==========================================
# ウォッチのスキャン 1 回分（scan）: {'t': datetime, 'source': 'wifi'|'ble', 'aps': [(mac, rssi|None), ...]}
#   aps は電波の強い順。旧 wifi_reports は RSSI が無い（None）。
# 1回のスキャン → 距離:   'top2'（上位2つを MAC01_WEIGHT で内分）/ 'rssi'（RSSI の差で隣の AP との間に置く）
# 時間でならす:            'basic'（今までの平滑化）/ 'series'（カルマンフィルタ＋歩く速さの上限）
# この組み合わせで 4 方式。画面・エリアボード・火災通知に使うのは position_settings で選んだ 1 つだけ。
POSITION_METHODS = [
    ('top2_basic', '① 上位2つ＋今までの平滑化'),
    ('top2_series', '② 上位2つ＋時系列（カルマン）'),
    ('rssi_basic', '③ RSSI の差＋今までの平滑化'),
    ('rssi_series', '④ RSSI の差＋時系列（カルマン）'),
    ('wifi3_series', '⑤ Wi-Fi だけ・上位3つの当てはめ＋時系列'),
    ('fusion_series', '⑥ Wi-Fi と BLE をそれぞれ向いた計算で合わせる＋時系列'),
]
POSITION_METHOD_KEYS = [k for k, _ in POSITION_METHODS]
# position_eval に後から ALTER TABLE で足した列（無い DB でも記録できるよう、失敗したら外して保存し直す）
POSITION_EVAL_LATER_COLUMNS = ['wifi3_series', 'fusion_series']
DEFAULT_POSITION_METHOD = 'top2_basic'   # 今までと同じ結果

# ③: RSSI の差から、強い AP(a) と次の AP(b) の間のどこにいるかを出す（距離減衰 RSSI = P0 - 10·n·log10(r)）。
#   RSSI_a - RSSI_b = 10·n·log10(r_b / r_a)、r_a + r_b = |d_a - d_b| として r_a を解く。
#   n はトンネルの減衰の係数（自由空間 2、トンネルは 1.5〜3 程度。現地の記録で決める）。
#   差を使うので、機種ごとの出力（P0）の違いは打ち消し合う。
PATH_LOSS_N = 2.0

# Wi-Fi と BLE の比重。basic では重みの掛け算、series では測定のばらつき（AP 間隔に対する割合）として使う。
# 値は仮置き。position_eval の記録を見て決める。
SOURCE_WEIGHT = {'wifi': 1.0, 'ble': 1.0}
SOURCE_SIGMA_SPACINGS = {'wifi': 0.35, 'ble': 0.25}

# ②④: カルマンフィルタ（1次元、位置だけ）。人の速さを超える飛びは捨てる。
SERIES_WINDOW_SEC = 60        # この秒数分のスキャンを使う
SERIES_MAX_SAMPLES = 60
SERIES_WALK_MPS = 3.0         # 位置のゆらぎ [m/s]。人の歩く速さより大きめにして遅れを減らす（1.5 → 3.0 でシミュレーションの誤差が減った）
SERIES_MAX_SPEED_MPS = 3.0    # これを超える速さでしか説明できない飛びは捨てる [m/s]
SERIES_GATE_SIGMA = 3.0       # 予測から 3σ を超えた値は捨てる
SERIES_RESET_AFTER = 3        # 続けてこの回数捨てたら、本当に動いたとみなして新しい値から始め直す

# ⑤: Wi-Fi のスキャンだけを使い、上位3つの RSSI すべてに距離減衰の式を当てはめる（③ のように2つの間に置くのではない）。
#   トンネル上の各地点 x について、AP i までの距離 r_i = √((x − d_i)² + 高さ²) から
#   予想 RSSI = A − 10·n·log10(r_i) を作り、実際の RSSI との差の二乗和が最小の x を 1m 刻みで探す。
#   A（出力など機種の違い）は x ごとに最小二乗で決めるので、絶対値は要らない。3つ目の AP がずれを打ち消す。
WIFI3_AP_HEIGHT_M = 3.0     # AP とウォッチの高さの差（真下で r が 0 にならないように）
WIFI3_STEP_M = 1.0

# 新しい表（wifi_reports_v2 / ble_reports）で、最後に AP が分かったスキャンがこれより古ければ「今どこか分からない」
SCAN_STALE_SEC = 2 * SMOOTHING_HALF_LIFE_SEC


def scan_top2_m(scan, ap_map):
    """上位2つの既知 AP を MAC01_WEIGHT で内分（旧 report_distance_m と同じ計算）。分からなければ None"""
    ds = [ap_map.distance(mac) for mac, _ in scan['aps']]
    ds = [d for d in ds if d is not None][:2]
    if len(ds) == 2:
        return MAC01_WEIGHT * ds[0] + (1 - MAC01_WEIGHT) * ds[1]
    return ds[0] if ds else None


def scan_rssi_m(scan, ap_map):
    """RSSI の差で、いちばん強い既知 AP と 2 番目の既知 AP の間に置く。RSSI が無ければ top2 と同じ"""
    known = [(ap_map.distance(mac), rssi) for mac, rssi in scan['aps'] if ap_map.distance(mac) is not None]
    if not known:
        return None
    if len(known) == 1 or any(r is None for _, r in known[:2]):
        return scan_top2_m(scan, ap_map)
    (da, ra), (db, rb) = known[0], known[1]
    span = abs(db - da)
    if span <= 0:
        return da
    k = 10 ** ((ra - rb) / (10 * PATH_LOSS_N))   # r_b / r_a（a が強いほど大きい）
    r_a = span / (1 + k)
    return da + (r_a if db > da else -r_a)


def scan_wifi3_m(scan, ap_map):
    """⑤ Wi-Fi の上位3つ（最低2つ）の RSSI に距離減衰の式を当てはめた位置。BLE のスキャンには使わない（None）。
    RSSI が無い旧形式は top2 と同じ"""
    if scan['source'] != 'wifi':
        return None
    known = [(ap_map.distance(mac), rssi) for mac, rssi in scan['aps'][:3] if ap_map.distance(mac) is not None]
    with_rssi = [(d, r) for d, r in known if r is not None]
    if len(with_rssi) < 2:
        return scan_top2_m(scan, ap_map)
    # 探すのは「いちばん強い AP の前後 1 区間」だけ（トンネル全体だと、遠い AP の電波のぶれで離れた所を選ぶことがある。
    # シミュレーションで平均誤差が 28m → 14m に減った。scripts/demo_watch.py の電波モデル、2026-11-20）
    d0 = with_rssi[0][0]
    all_d = sorted({e['distance_m'] for e in ap_map.entries.values()})
    lo = max([d for d in all_d if d < d0], default=d0 - ap_map.spacing * 0.5)
    hi = min([d for d in all_d if d > d0], default=d0 + ap_map.spacing * 0.5)
    best_x, best_err = None, None
    steps = int(round((hi - lo) / WIFI3_STEP_M)) + 1
    for k in range(steps):
        x = lo + k * WIFI3_STEP_M
        terms = [(r, 10 * PATH_LOSS_N * math.log10(math.sqrt((x - d) ** 2 + WIFI3_AP_HEIGHT_M ** 2))) for d, r in with_rssi]
        A = sum(r + loss for r, loss in terms) / len(terms)
        err = sum((r - (A - loss)) ** 2 for r, loss in terms)
        if best_err is None or err < best_err - 1e-9:
            best_x, best_err = x, err
    return best_x


def scan_fusion_m(scan, ap_map):
    """⑥ スキャンの種類ごとに向いた計算を使う: BLE は ③（RSSI の差。回数が多く2つの間に置くので十分）、
    Wi-Fi は ⑤（3つ目まで使う当てはめ）。どちらも同じ時系列（カルマン）に入れ、
    ばらつき SOURCE_SIGMA_SPACINGS（BLE の方が小さい＝重い）で自然に重み付けされる"""
    if scan['source'] == 'ble':
        return scan_rssi_m(scan, ap_map)
    return scan_wifi3_m(scan, ap_map)


SCAN_ESTIMATORS = {'top2': scan_top2_m, 'rssi': scan_rssi_m, 'wifi3': scan_wifi3_m, 'fusion': scan_fusion_m}
# 方式ごとに作る組み合わせ（1回分の求め方 → basic / series）。⑤ ⑥ は series だけ
SCAN_ESTIMATOR_MODES = {'top2': ('basic', 'series'), 'rssi': ('basic', 'series'),
                        'wifi3': ('series',), 'fusion': ('series',)}


def series_distance_m(points, ap_map):
    """points: [(t_sec, distance_m, source)] を古い順に、1次元カルマンフィルタでならした最新の距離[m]"""
    x = P = None
    last_t = None
    rejected = 0
    for t, z, source in points:
        R = (SOURCE_SIGMA_SPACINGS.get(source, 0.35) * ap_map.spacing) ** 2
        if x is None:
            x, P, last_t = z, R, t
            continue
        dt = max(0.0, t - last_t)
        P_pred = P + (SERIES_WALK_MPS * dt) ** 2
        innov = z - x
        S = P_pred + R
        too_far = innov * innov > (SERIES_GATE_SIGMA ** 2) * S and abs(innov) > SERIES_MAX_SPEED_MPS * dt + ap_map.spacing * 0.5
        if too_far:
            rejected += 1
            if rejected < SERIES_RESET_AFTER:
                continue
            x, P, last_t, rejected = z, R, t, 0   # 続けて外れる＝本当に動いた
            continue
        rejected = 0
        K = P_pred / S
        x = x + K * innov
        P = (1 - K) * P_pred
        last_t = t
    return x


def _scan_rows_to_scans(rows, source, with_rssi):
    scans = []
    for row in rows or []:
        t = parse_ts(row.get('scanned_at')) or parse_ts(row.get('created_at'))
        if t is None:
            continue
        aps = []
        for i in ('01', '02', '03'):
            mac = row.get(f'mac{i}')
            if not mac:
                continue
            rssi = row.get(f'rssi{i}') if with_rssi else None
            aps.append((mac, rssi if isinstance(rssi, (int, float)) else None))
        if with_rssi:
            aps.sort(key=lambda a: -(a[1] if a[1] is not None else -999))   # 念のため強い順に並べ直す
        scans.append({'device_id': row.get('device_id'), 't': t, 'source': source, 'aps': aps})
    return scans


def load_recent_scan_reports(table, window_sec):
    """新しい表（wifi_reports_v2 / ble_reports）の直近 window_sec 秒分。テーブルが無ければ空"""
    since = (datetime.now(timezone.utc) - timedelta(seconds=window_sec)).isoformat()
    try:
        return (
            supabase.table(table)
            .select("device_id, scanned_at, created_at, mac01, rssi01, mac02, rssi02, mac03, rssi03")
            .gte("created_at", since)
            .order("id", desc=True)
            .limit(3000)
            .execute()
        ).data or []
    except Exception as e:
        print(f"Error loading {table}: {e}")
        return []


def load_recent_scans():
    """device_id → スキャンのリスト（新しい順）。新しい表に行がある装置は、旧 wifi_reports を使わない（二重に数えない）"""
    window = max(SMOOTHING_WINDOW_SEC, SERIES_WINDOW_SEC) * 2
    new_scans = (_scan_rows_to_scans(load_recent_scan_reports(TABLE_WIFI_SCAN, window), 'wifi', True)
                 + _scan_rows_to_scans(load_recent_scan_reports(TABLE_BLE_SCAN, window), 'ble', True))
    by_device = {}
    for sc in new_scans:
        if sc['device_id']:
            by_device.setdefault(sc['device_id'], []).append(sc)
    legacy = {}
    for sc in _scan_rows_to_scans(load_recent_wifi_reports(window), 'wifi', False):
        if sc['device_id'] and sc['device_id'] not in by_device:
            legacy.setdefault(sc['device_id'], []).append(sc)
    for scans in by_device.values():
        scans.sort(key=lambda sc: sc['t'], reverse=True)
    return by_device, legacy


def estimate_methods(scans, ap_map, ref_t):
    """1台分のスキャン（新しい順）から 4 方式すべての距離[m]。サンプルが無い方式は None"""
    out = {}
    for est_name, estimator in SCAN_ESTIMATORS.items():
        points = []   # (age, distance, source, 新しい方から何番目のスキャンか)
        for i, sc in enumerate(scans):
            age = max(0.0, (ref_t - sc['t']).total_seconds())
            if age > max(SMOOTHING_WINDOW_SEC, SERIES_WINDOW_SEC):
                continue
            d = estimator(sc, ap_map)
            if d is not None:
                points.append((age, d, sc['source'], i))
        # basic は今までと同じく「新しい方から SMOOTHING_MAX_SAMPLES 回のスキャン」のうち AP が分かったもの
        basic = [(d, age, SOURCE_WEIGHT.get(src, 1.0)) for age, d, src, i in points
                 if i < SMOOTHING_MAX_SAMPLES and age <= SMOOTHING_WINDOW_SEC]
        modes = SCAN_ESTIMATOR_MODES.get(est_name, ('basic', 'series'))
        if 'basic' in modes:
            out[f'{est_name}_basic'] = smooth_distance_m(basic, ap_map.outlier_m) if basic else None
        if 'series' in modes:
            series = sorted(points[:SERIES_MAX_SAMPLES], key=lambda p: -p[0])   # 古い順
            out[f'{est_name}_series'] = (series_distance_m([(-age, d, src) for age, d, src, _ in series], ap_map)
                                         if series else None)
        out[f'{est_name}_samples'] = len(basic) if 'basic' in modes else len(points[:SERIES_MAX_SAMPLES])
    for k in POSITION_METHOD_KEYS:
        if out.get(k) is not None:
            out[k] = round(ap_map.clamp(out[k]), 1)
    return out


def load_position_method():
    """画面で選んだ方式（position_settings id=1）。テーブルが無い・未設定なら DEFAULT_POSITION_METHOD"""
    try:
        row = (supabase.table(TABLE_POSITION_SETTINGS).select("method").eq("id", 1).execute().data or [None])[0]
    except Exception as e:
        print(f"Error loading position_settings: {e}")
        row = None
    method = (row or {}).get('method')
    return method if method in POSITION_METHOD_KEYS else DEFAULT_POSITION_METHOD


def area_centers_m(area_rows, ap_map):
    """エリア割当設定（area_status_v2.bssid）の AP の距離が分かれば、それをエリアの中心とする"""
    centers = {}
    for row in (area_rows or []):
        d = ap_map.distance(row.get('bssid'))
        if row.get('area_id') and d is not None:
            centers[row['area_id']] = d
    return centers


def build_area_layout(area_order, centers, ap_map):
    """マップ上のエリア区間 [{area_id, start, end}]（比率）。
    全エリアに中心があれば中心間の中点で区切る（＝最寄りのエリアに割り当て）。無ければ従来どおり等分。"""
    n = len(area_order)
    if n == 0:
        return []
    if all(a in centers for a in area_order):
        ordered = sorted(area_order, key=lambda a: centers[a])
        layout = []
        for i, a in enumerate(ordered):
            start = 0.0 if i == 0 else ap_map.to_ratio((centers[ordered[i - 1]] + centers[a]) / 2)
            end = 1.0 if i == n - 1 else ap_map.to_ratio((centers[a] + centers[ordered[i + 1]]) / 2)
            layout.append({'area_id': a, 'start': round(start, 4), 'end': round(end, 4)})
        return layout
    return [{'area_id': a, 'start': round(i / n, 4), 'end': round((i + 1) / n, 4)} for i, a in enumerate(area_order)]


def area_for_ratio(layout, ratio):
    for seg in layout:
        if ratio < seg['end']:
            return seg['area_id']
    return layout[-1]['area_id'] if layout else None


def estimate_positions(latest_reports, ap_map, area_order, area_rows, method=None):
    """デバイスごとの推定位置を返す。
    戻り値: (positions, layout)
      positions: {device_id: {'distance_m', 'ratio', 'area_id', 'samples', 'approx', 'method', 'methods', 'sources'}}
        （推定できないデバイスは含まない）
        approx=True は AP の距離では位置が出せず、エリア割当の BSSID 一致だけで決めたもの（ratio はエリアの中央）
        methods は ①〜④ すべての距離（比較用）。distance_m / ratio / area_id は method（既定は画面で選んだ方式）のもの
      layout: build_area_layout の結果

    使うスキャン: 新しい表（wifi_reports_v2 / ble_reports、RSSI 付き）に行がある装置はそれだけ、
    無い装置は旧 wifi_reports（RSSI なし。① と ③、② と ④ は同じ値になる）。
    装置の一覧は latest_reports（旧 wifi_reports の最新行）。

    エリアの決め方（上ほど優先）:
      1. 全エリアの BSSID の距離が分かる → 推定した距離に最も近いエリア
      2. 最新レポートの mac01 / mac02 がエリア割当の BSSID と一致 → そのエリア（従来のエリアボードの方式）
      3. 推定した距離でトンネルを等分したエリア（従来のトンネルマップの方式）"""
    method = method if method in POSITION_METHOD_KEYS else load_position_method()
    centers = area_centers_m(area_rows, ap_map)
    layout = build_area_layout(area_order, centers, ap_map)
    centered = bool(layout) and all(a in centers for a in area_order)
    bssid_area = {norm_mac(row['bssid']): row['area_id'] for row in (area_rows or []) if row.get('bssid') and row.get('area_id')}
    segment = {seg['area_id']: seg for seg in layout}
    new_scans, legacy_scans = load_recent_scans()

    positions = {}
    for latest in (latest_reports or []):
        did = latest.get('device_id')
        if not did:
            continue
        direct_area = bssid_area.get(norm_mac(latest.get('mac01'))) or bssid_area.get(norm_mac(latest.get('mac02')))

        if did in new_scans:
            scans = new_scans[did]
            ref_t = scans[0]['t']
            known_t = next((sc['t'] for sc in scans if scan_top2_m(sc, ap_map) is not None), None)
            # 最後に AP が分かったスキャンが古ければ、古い位置で表示し続けない
            fresh = known_t is not None and (ref_t - known_t).total_seconds() <= SCAN_STALE_SEC
            if known_t is not None:
                ref_t = known_t
        else:
            latest_scan = _scan_rows_to_scans([latest], 'wifi', False)
            latest_ts = latest_scan[0]['t'] if latest_scan else None
            scans = legacy_scans.get(did) or latest_scan
            ref_t = latest_ts or (scans[0]['t'] if scans else None)
            # 最新レポートで AP が分からない時に、古い位置で表示し続けない（今までと同じ）
            fresh = report_distance_m(latest, ap_map) is not None
            if ref_t is not None and latest_ts is not None:
                scans = [sc for sc in scans if sc['t'] <= latest_ts]

        methods = estimate_methods(scans, ap_map, ref_t) if (scans and ref_t is not None) else {}
        distance = methods.get(method)
        if not fresh or distance is None:
            seg = segment.get(direct_area)
            if seg is None:
                continue
            positions[did] = {
                'distance_m': None,
                'ratio': round((seg['start'] + seg['end']) / 2, 4),
                'area_id': direct_area,
                'samples': 0,
                'approx': True,
                'method': method,
                'methods': {k: methods.get(k) for k in POSITION_METHOD_KEYS},
                'sources': sorted({sc['source'] for sc in scans}) if did in new_scans else ['wifi_legacy'],
            }
            continue

        ratio = ap_map.to_ratio(distance)
        if centered or not direct_area:
            area_id = area_for_ratio(layout, ratio)
        else:
            area_id = direct_area
        positions[did] = {
            'distance_m': round(distance, 1),
            'ratio': round(ratio, 4),
            'area_id': area_id,
            'samples': methods.get(f"{method.split('_')[0]}_samples", 0),
            'approx': False,
            'method': method,
            'methods': {k: methods.get(k) for k in POSITION_METHOD_KEYS},
            'sources': sorted({sc['source'] for sc in scans}) if did in new_scans else ['wifi_legacy'],
        }
    return positions, layout

# ==========================================
#  火災位置
# ==========================================
# 火災までの距離が「AP 間隔 × FIRE_NEAR_SPACINGS」以内なら「すぐ近く」（100m 間隔なら 50m）。
# 位置推定の誤差は AP 間隔の 2 割前後あるため、これより細かく分けても意味がない。
FIRE_NEAR_SPACINGS = 0.5
# ウォッチに出す距離の丸め単位（推定誤差より細かい数字を見せない）
FIRE_DISTANCE_STEP_M = 10.0


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


def fire_relation(worker_m, fire_m, near_m):
    """作業者から見た火災の方向と距離。
    direction: 'inward'（奥側）/ 'outward'（入口側）/ 'near'（すぐ近く）"""
    diff = fire_m - worker_m
    distance = round(abs(diff) / FIRE_DISTANCE_STEP_M) * FIRE_DISTANCE_STEP_M
    if abs(diff) <= near_m:
        return 'near', distance, f"火災: すぐ近く（約{distance:.0f}m）"
    if diff > 0:
        return 'inward', distance, f"火災: 奥 約{distance:.0f}m"
    return 'outward', distance, f"火災: 手前 約{distance:.0f}m"


def build_fire_alerts(device_ids, positions, fire, ap_map):
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
                worker_m = pos['distance_m'] if pos['distance_m'] is not None else ap_map.from_ratio(pos['ratio'])
                direction, distance, message = fire_relation(worker_m, fire['distance_m'], ap_map.near_m)
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


def update_fire_alerts(reports, positions, fire, ap_map):
    """最新レポートのある全デバイスと登録ユーザーの device_fire_alerts を最新化し、alerts を返す"""
    device_ids = {r.get('device_id') for r in (reports or []) if r.get('device_id')}
    device_ids |= {u.get('device_id') for u in (load_user_table() or []) if u.get('device_id')}
    alerts = build_fire_alerts(sorted(device_ids), positions, fire, ap_map)
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
    """AP位置設定（現場の Wi-Fi AP）。GET は位置番号順に、距離（distance_m）と表示名（label）付き。
    POST {mac, distance_m, position?, original_mac?}: position を省くと自動で振る（今の最大＋1、6 以上）。
      original_mac は表で MAC を書き換えたときの元の MAC（元の行を消して付け替える）。
    DELETE {mac}"""
    if request.method == 'GET':
        return jsonify(load_ap_position_rows())

    data = request.json or {}
    mac = str(data.get('mac') or '').strip().upper()
    if request.method == 'DELETE':
        if not mac:
            return jsonify({'error': 'mac を指定してください'}), 400
        try:
            rows = supabase.table(TABLE_AP_POSITIONS).select("mac").execute().data or []
            for r in rows:   # 大文字・小文字の違う同じ MAC もまとめて消す
                if norm_mac(r.get('mac')) == mac:
                    supabase.table(TABLE_AP_POSITIONS).delete().eq('mac', r['mac']).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if not _MAC_RE.match(mac):
        return jsonify({'error': 'MAC アドレスは AA:BB:CC:DD:EE:FF の形で入れてください'}), 400
    try:
        distance = float(data.get('distance_m'))
    except (TypeError, ValueError):
        return jsonify({'error': '入口からの距離（m）を数値で入れてください'}), 400
    if distance < 0:
        return jsonify({'error': '距離は 0 以上にしてください'}), 400
    try:
        rows = supabase.table(TABLE_AP_POSITIONS).select("*").execute().data or []
        original = norm_mac(data.get('original_mac')) or mac
        same = [r for r in rows if norm_mac(r.get('mac')) in (mac, original)]
        position = data.get('position')
        if position is None and same:
            position = same[0].get('position')            # 既にある AP は番号をそのまま
        if position is None:
            used = [int(r['position']) for r in rows if str(r.get('position', '')).lstrip('-').isdigit()]
            # 新しい AP は自動で次の番号。既設の 6 台の番号 0〜5（AP1〜AP11 の名前）とは重ねない
            position = max([AP_COUNT - 1] + used) + 1
        position = int(position)
        for r in same:                                     # MAC を書き換えた・大文字小文字の違う行は消して付け替える
            if r.get('mac') != mac:
                supabase.table(TABLE_AP_POSITIONS).delete().eq('mac', r['mac']).execute()
        row = {'mac': mac, 'position': position, 'distance_m': distance}
        try:
            supabase.table(TABLE_AP_POSITIONS).upsert(row).execute()
        except Exception as e:
            print(f"ap_positions upsert retry without distance_m: {e}")
            row.pop('distance_m')
            supabase.table(TABLE_AP_POSITIONS).upsert(row).execute()
            return jsonify({'message': 'saved', 'position': position,
                            'warning': '距離の列がありません。supabase/ap_positions_distance.sql を実行してください（今は位置番号の距離を使います）'})
        return jsonify({'message': 'saved', 'position': position, 'label': ap_position_label(position)})
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
            if 'mac' not in item or ('position' not in item and 'distance_m' not in item):
                return jsonify({'error': '各要素に mac と distance_m（または position）が必要です'}), 400
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


# ==========================================
#  ESP32 AP（firmware/esp32s3_ap）
# ==========================================
# ESP32 が送る heartbeat の共有トークン（環境変数 AP_SHARED_TOKEN。firmware の AP_TOKEN と同じ値）。
# 未設定なら heartbeat を受け付けない。
AP_SHARED_TOKEN = os.environ.get("AP_SHARED_TOKEN", "")
_MAC_RE = re.compile(r'^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$')


@app.route('/api/ap_heartbeat', methods=['POST'])
def ap_heartbeat():
    """ESP32 AP が 30 秒ごとに送る。ログイン不要の代わりに X-AP-Token ヘッダーで認証する。
    初回は ap_nodes に行を作り、firmware に書いた label / distance_m を初期値にする。
    2回目以降は稼働情報だけ更新する（管理画面で直した label / distance_m / enabled は上書きしない）。"""
    if not AP_SHARED_TOKEN:
        return jsonify({'error': 'heartbeat is disabled (AP_SHARED_TOKEN not set)'}), 503
    token = request.headers.get('X-AP-Token', '')
    if not hmac.compare_digest(token, AP_SHARED_TOKEN):
        return jsonify({'error': 'invalid token'}), 401

    data = request.get_json(silent=True) or {}
    mac = str(data.get('mac') or '').upper()
    if not _MAC_RE.match(mac):
        return jsonify({'error': 'mac は AA:BB:CC:DD:EE:FF 形式で指定してください'}), 400

    def as_int(key):
        try:
            return int(data[key]) if data.get(key) is not None else None
        except (TypeError, ValueError):
            return None

    payload = {
        'mac': mac,
        'last_seen': now_iso(),
        'fw': str(data.get('fw') or '')[:32] or None,
        'uptime_s': as_int('uptime_s'),
        'sta_count': as_int('sta_count'),
        'tx_power_dbm': data.get('tx_power_dbm') if isinstance(data.get('tx_power_dbm'), (int, float)) else None,
        'channel': as_int('channel'),
        'uplink_rssi': as_int('uplink_rssi'),
    }
    try:
        existing = supabase.table(TABLE_AP_NODES).select("mac").eq("mac", mac).execute().data
        if not existing:
            payload['label'] = str(data.get('label') or '')[:32] or None
            d = data.get('distance_m')
            payload['distance_m'] = float(d) if isinstance(d, (int, float)) else None
            payload['enabled'] = True
        supabase.table(TABLE_AP_NODES).upsert(payload).execute()
    except Exception as e:
        print(f"Error saving ap heartbeat {mac}: {e}")
        return jsonify({'error': 'heartbeat の保存に失敗しました'}), 500
    return jsonify({'message': 'ok', 'registered': not existing})


@app.route('/api/ap_nodes', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_ap_nodes():
    """ESP32 AP の一覧と設定。GET は online（heartbeat が AP_NODE_ONLINE_SEC 以内）付き。
    POST {mac, label?, distance_m?, enabled?} で設定を変更、DELETE {mac} で削除（動いていれば次の heartbeat で再登録される）。
    POST {create: true, mac, label, distance_m, kind: 'ble'|'wifi'} で画面から追加（上り回線の無い ESP32 など）。
    追加した行の fw は 'ble-manual' / 'wifi-manual'。実物の heartbeat が届くと fw などは実物の値になる"""
    if request.method == 'GET':
        nodes = sorted(load_ap_nodes(), key=lambda n: (n.get('distance_m') is None, n.get('distance_m') or 0, n.get('mac')))
        for n in nodes:
            n['online'] = is_recent(n.get('last_seen'), AP_NODE_ONLINE_SEC)
        return jsonify(nodes)

    data = request.json or {}
    mac = str(data.get('mac') or '').upper()
    if not _MAC_RE.match(mac):
        return jsonify({'error': 'mac を指定してください'}), 400

    if request.method == 'DELETE':
        try:
            supabase.table(TABLE_AP_NODES).delete().eq('mac', mac).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            print(f"Error deleting ap node {mac}: {e}")
            return jsonify({'error': '削除に失敗しました'}), 500

    if data.get('create'):
        try:
            d = data.get('distance_m')
            distance = None if d in (None, '') else float(d)
        except (TypeError, ValueError):
            return jsonify({'error': '入口からの距離（m）は数値で入れてください'}), 400
        if distance is not None and distance < 0:
            return jsonify({'error': '距離は 0 以上にしてください'}), 400
        kind = 'wifi' if data.get('kind') == 'wifi' else 'ble'
        try:
            exists = supabase.table(TABLE_AP_NODES).select("mac").eq('mac', mac).execute().data
            if exists:
                return jsonify({'error': 'その MAC はもう登録されています（表の行を直してください）'}), 409
            supabase.table(TABLE_AP_NODES).insert({
                'mac': mac, 'label': (str(data.get('label') or '').strip()[:32]) or None,
                'distance_m': distance, 'enabled': True, 'fw': f'{kind}-manual',
            }).execute()
            return jsonify({'message': 'created'})
        except Exception as e:
            print(f"Error creating ap node {mac}: {e}")
            return jsonify({'error': '追加に失敗しました'}), 500

    update = {}
    if 'label' in data:
        update['label'] = (str(data.get('label') or '').strip()[:32]) or None
    if 'distance_m' in data:
        d = data.get('distance_m')
        if d in (None, ''):
            update['distance_m'] = None
        else:
            try:
                update['distance_m'] = float(d)
            except (TypeError, ValueError):
                return jsonify({'error': 'distance_m は数値（入口からの m）で指定してください'}), 400
            if update['distance_m'] < 0:
                return jsonify({'error': 'distance_m は 0 以上にしてください'}), 400
    if 'enabled' in data:
        update['enabled'] = bool(data.get('enabled'))
    if not update:
        return jsonify({'error': '変更する項目がありません'}), 400
    try:
        supabase.table(TABLE_AP_NODES).update(update).eq('mac', mac).execute()
        return jsonify({'message': 'saved'})
    except Exception as e:
        print(f"Error updating ap node {mac}: {e}")
        return jsonify({'error': '保存に失敗しました'}), 500


# ==========================================
#  ESP32 カメラ（firmware/esp32cam_uplink）
# ==========================================
# 見ている人がいる間だけ、カメラが JPEG を 1 枚ずつ送る（コマ送り）。
#   カメラ: 10 秒ごとに /api/camera_poll →「送って」と返されたら /api/camera_frame に JPEG を送り続ける
#   画面:   /api/camera_frame/<id> を 1 秒ごとに取りに来る → そのたびに watch_until を延ばす
# 画像は Supabase Storage の CAMERA_BUCKET に「<camera_id>/latest.jpg」として上書き保存する（最新 1 枚だけ）。
# 認証はカメラ側が X-AP-Token（AP_SHARED_TOKEN）、画面側がログイン。スキーマは supabase/cameras.sql。
CAMERA_BUCKET = "camera-frames"
CAMERA_WATCH_SEC = 20            # 最後に画面が画像を取りに来てから、この秒数は送り続ける
CAMERA_IDLE_POLL_SEC = 10        # 誰も見ていない間、カメラが問い合わせる間隔
CAMERA_FRAME_INTERVAL_MS = 1000  # 見られている間、カメラが送る間隔
CAMERA_ONLINE_SEC = 60           # last_seen がこの秒数以内なら「稼働中」
CAMERA_MAX_FRAME_BYTES = 600 * 1024
_CAMERA_ID_RE = re.compile(r'^[A-Za-z0-9_-]{1,32}$')


def device_token_ok():
    """ESP32（AP・カメラ）からの要求の共有トークンを確かめる。(ok, エラー応答)"""
    if not AP_SHARED_TOKEN:
        return False, (jsonify({'error': 'device API is disabled (AP_SHARED_TOKEN not set)'}), 503)
    if not hmac.compare_digest(request.headers.get('X-AP-Token', ''), AP_SHARED_TOKEN):
        return False, (jsonify({'error': 'invalid token'}), 401)
    return True, None


def load_camera(camera_id):
    try:
        res = supabase.table(TABLE_CAMERAS).select("*").eq("camera_id", camera_id).execute()
        return (res.data or [None])[0]
    except Exception as e:
        print(f"Error loading camera {camera_id}: {e}")
        return None


def camera_ap_node(row, nodes_by_mac):
    """カメラが兼ねている ESP32 AP（ap_nodes の行）。cameras.ap_mac が無い・未登録なら None"""
    mac = norm_mac((row or {}).get('ap_mac'))
    return nodes_by_mac.get(mac) if mac else None


def camera_watching(row):
    """誰かが今このカメラを見ているか（watch_until が未来）"""
    ts = parse_ts((row or {}).get('watch_until'))
    return ts is not None and ts > datetime.now(timezone.utc)


def camera_instruction(row):
    """カメラへの返事: 送るかどうかと、次に連絡する間隔"""
    send = bool(row) and row.get('enabled') is not False and camera_watching(row)
    return {'send': send, 'interval_ms': CAMERA_FRAME_INTERVAL_MS, 'poll_sec': CAMERA_IDLE_POLL_SEC}


@app.route('/api/camera_poll', methods=['POST'])
def camera_poll():
    """カメラが 10 秒ごとに送る生存通知。初回は cameras に行を作る（label / distance_m は初期値）。
    返事の send が true の間、カメラは /api/camera_frame に画像を送る。"""
    ok, err = device_token_ok()
    if not ok:
        return err
    data = request.get_json(silent=True) or {}
    camera_id = str(data.get('camera_id') or '')
    if not _CAMERA_ID_RE.match(camera_id):
        return jsonify({'error': 'camera_id は英数字・_・- の 1〜32 文字で指定してください'}), 400

    row = load_camera(camera_id)
    payload = {'camera_id': camera_id, 'last_seen': now_iso(), 'fw': str(data.get('fw') or '')[:32] or None}
    if isinstance(data.get('rssi'), int):
        payload['wifi_rssi'] = data['rssi']
    ap_mac = str(data.get('ap_mac') or '').upper()
    if _MAC_RE.match(ap_mac):
        payload['ap_mac'] = ap_mac   # このカメラが兼ねている AP（距離は ap_nodes と連動させる）
    if row is None:
        payload['label'] = str(data.get('label') or '')[:32] or camera_id
        d = data.get('distance_m')
        payload['distance_m'] = float(d) if isinstance(d, (int, float)) else None
        payload['enabled'] = True
    try:
        try:
            supabase.table(TABLE_CAMERAS).upsert(payload).execute()
        except Exception as e:
            if 'ap_mac' not in payload:
                raise
            # supabase/cameras.sql の ap_mac 列をまだ足していない DB でも動かす
            print(f"camera poll without ap_mac ({camera_id}): {e}")
            payload.pop('ap_mac')
            supabase.table(TABLE_CAMERAS).upsert(payload).execute()
    except Exception as e:
        print(f"Error saving camera poll {camera_id}: {e}")
        return jsonify({'error': 'カメラ情報の保存に失敗しました（supabase/cameras.sql は実行済みですか？）'}), 500
    return jsonify(camera_instruction(row or payload))


@app.route('/api/camera_frame', methods=['POST'])
def camera_frame_upload():
    """カメラが JPEG を 1 枚送る（本文は image/jpeg そのもの、?camera_id=xxx）。最新 1 枚だけ保存する。"""
    ok, err = device_token_ok()
    if not ok:
        return err
    camera_id = request.args.get('camera_id', '')
    if not _CAMERA_ID_RE.match(camera_id):
        return jsonify({'error': 'camera_id が不正です'}), 400
    jpeg = request.get_data(cache=False)
    if not jpeg or len(jpeg) > CAMERA_MAX_FRAME_BYTES or jpeg[:2] != b'\xff\xd8':
        return jsonify({'error': f'JPEG（{CAMERA_MAX_FRAME_BYTES // 1024}KB まで）を送ってください'}), 400

    row = load_camera(camera_id)
    if row is None:
        return jsonify({'error': '先に /api/camera_poll で登録してください'}), 409
    if not camera_watching(row) or row.get('enabled') is False:
        # 誰も見ていないので保存しない（カメラは送るのをやめる）
        return jsonify(camera_instruction(row))

    try:
        supabase.storage.from_(CAMERA_BUCKET).upload(
            f"{camera_id}/latest.jpg", jpeg,
            {"content-type": "image/jpeg", "cache-control": "0", "upsert": "true"},
        )
        now = now_iso()
        update = {'last_frame_at': now, 'last_seen': now, 'frame_bytes': len(jpeg)}
        for key, header in (('width', 'X-Frame-Width'), ('height', 'X-Frame-Height')):
            if request.headers.get(header, '').isdigit():
                update[key] = int(request.headers[header])
        supabase.table(TABLE_CAMERAS).update(update).eq('camera_id', camera_id).execute()
    except Exception as e:
        print(f"Error saving camera frame {camera_id}: {e}")
        return jsonify({'error': '画像の保存に失敗しました（Storage の camera-frames バケットはありますか？）'}), 500
    return jsonify(camera_instruction(row))


@app.route('/api/cameras', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_cameras():
    """カメラの一覧と設定。GET は online（CAMERA_ONLINE_SEC 以内に連絡あり）と watching 付き。
    POST {camera_id, label?, distance_m?, enabled?} で設定変更、DELETE {camera_id} で削除。
    カメラが AP を兼ねている（ap_mac が ap_nodes にある）ときは、距離は ap_nodes の値を正とする:
    GET はその距離を返し（distance_source='ap'）、POST の distance_m は ap_nodes にも書く。"""
    if request.method == 'GET':
        try:
            rows = supabase.table(TABLE_CAMERAS).select("*").execute().data or []
        except Exception as e:
            print(f"Error loading cameras: {e}")
            rows = []
        nodes_by_mac = {norm_mac(n.get('mac')): n for n in load_ap_nodes() if n.get('mac')}
        for r in rows:
            node = camera_ap_node(r, nodes_by_mac)
            if node is not None:
                r['distance_m'] = node.get('distance_m')
                r['distance_source'] = 'ap'
                r['ap_label'] = node.get('label')
        rows.sort(key=lambda r: (r.get('distance_m') is None, r.get('distance_m') or 0, r.get('camera_id')))
        for r in rows:
            r['online'] = is_recent(r.get('last_seen'), CAMERA_ONLINE_SEC)
            r['watching'] = camera_watching(r)
        return jsonify(rows)

    data = request.json or {}
    camera_id = str(data.get('camera_id') or '')
    if not _CAMERA_ID_RE.match(camera_id):
        return jsonify({'error': 'camera_id を指定してください'}), 400

    if request.method == 'DELETE':
        try:
            supabase.table(TABLE_CAMERAS).delete().eq('camera_id', camera_id).execute()
            return jsonify({'message': 'deleted'})
        except Exception as e:
            print(f"Error deleting camera {camera_id}: {e}")
            return jsonify({'error': '削除に失敗しました'}), 500

    update = {}
    if 'label' in data:
        update['label'] = (str(data.get('label') or '').strip()[:32]) or camera_id
    if 'distance_m' in data:
        d = data.get('distance_m')
        try:
            update['distance_m'] = None if d in (None, '') else float(d)
        except (TypeError, ValueError):
            return jsonify({'error': 'distance_m は数値（入口からの m）で指定してください'}), 400
    if 'enabled' in data:
        update['enabled'] = bool(data.get('enabled'))
    if not update:
        return jsonify({'error': '変更する項目がありません'}), 400
    try:
        supabase.table(TABLE_CAMERAS).update(update).eq('camera_id', camera_id).execute()
        if 'distance_m' in update:
            # AP を兼ねるカメラなら、位置推定に使う ap_nodes の距離も同じ値にする
            nodes_by_mac = {norm_mac(n.get('mac')): n for n in load_ap_nodes() if n.get('mac')}
            node = camera_ap_node(load_camera(camera_id), nodes_by_mac)
            if node is not None:
                supabase.table(TABLE_AP_NODES).update({'distance_m': update['distance_m']}).eq('mac', node['mac']).execute()
        return jsonify({'message': 'saved'})
    except Exception as e:
        print(f"Error updating camera {camera_id}: {e}")
        return jsonify({'error': '保存に失敗しました'}), 500


@app.route('/api/camera_frame/<camera_id>', methods=['GET'])
@login_required
def camera_frame_view(camera_id):
    """画面が 1 秒ごとに呼ぶ。最新の 1 枚を返し、「見ている」期限（watch_until）を延ばす。
    まだ画像が無い・カメラが起きる前は 204（X-Camera-Status で理由）。"""
    if not _CAMERA_ID_RE.match(camera_id):
        return jsonify({'error': 'camera_id が不正です'}), 400
    row = load_camera(camera_id)
    if row is None:
        return jsonify({'error': 'そのカメラはありません'}), 404

    # 期限が残り半分を切ったときだけ延ばす（毎秒 DB に書かないため）
    watch_until = parse_ts(row.get('watch_until'))
    now = datetime.now(timezone.utc)
    if watch_until is None or (watch_until - now).total_seconds() < CAMERA_WATCH_SEC / 2:
        try:
            supabase.table(TABLE_CAMERAS).update(
                {'watch_until': (now + timedelta(seconds=CAMERA_WATCH_SEC)).isoformat()}
            ).eq('camera_id', camera_id).execute()
        except Exception as e:
            print(f"Error extending camera watch {camera_id}: {e}")

    headers = {'Cache-Control': 'no-store', 'X-Frame-At': row.get('last_frame_at') or ''}
    last_frame = parse_ts(row.get('last_frame_at'))
    # 見始めたばかりで、前回見たときの古い画像しか無いなら「起こしている」を返す
    if last_frame is None or (now - last_frame).total_seconds() > CAMERA_WATCH_SEC + CAMERA_IDLE_POLL_SEC:
        headers['X-Camera-Status'] = 'waking'
        return Response(status=204, headers=headers)
    try:
        jpeg = supabase.storage.from_(CAMERA_BUCKET).download(f"{camera_id}/latest.jpg")
    except Exception as e:
        print(f"Error downloading camera frame {camera_id}: {e}")
        headers['X-Camera-Status'] = 'no-frame'
        return Response(status=204, headers=headers)
    return Response(jpeg, mimetype='image/jpeg', headers=headers)


@app.route('/api/wifi_map', methods=['GET'])
@login_required
def get_wifi_map():
    reports = load_wifi_reports()
    ap_map = load_ap_map()
    area_order = load_area_order()
    positions, layout = estimate_positions(reports, ap_map, area_order, load_area_table())

    user_map = {u['device_id']: u['username'] for u in (load_user_table() or []) if u.get('device_id') and u.get('username')}
    instruction_map = sync_device_reports_from_wifi(reports)

    online_device_ids = sorted({
        row.get('device_id') for row in (reports or [])
        if row.get('device_id') and is_recent(row.get('created_at'))
    })
    online_set = set(online_device_ids)

    # 火災位置が出ていれば、各ウォッチ向けの「自分から見た火災の方向」を更新する
    fire = load_fire_location()
    alerts = update_fire_alerts(reports, positions, fire, ap_map)

    # AP の区間の指示: 区間に入ったウォッチに送る（送ったら instruction_map も新しくする）
    segments = ap_segments(ap_map)
    seg_rows = load_segment_instructions()
    if apply_segment_instructions(positions, segments, seg_rows):
        instruction_map = {r['device_id']: r for r in load_device_instructions() if r.get('device_id')}

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
            'methods': pos.get('methods'),
            'sources': pos.get('sources'),
        })

    return jsonify({
        'workers': workers,
        'ap_count': AP_COUNT,
        'ap_labels': AP_LABELS,
        'ap_markers': ap_map.markers(),
        'ap_spacing_m': ap_map.spacing,
        'area_order': area_order,
        'area_layout': layout,
        'online_device_ids': online_device_ids,
        'position_method': positions_method(positions),
        'segments': segments_with_instructions(segments, seg_rows, positions),
        'fire': {
            'active': fire['active'],
            'distance_m': fire['distance_m'],
            'ratio': round(ap_map.to_ratio(fire["distance_m"]), 4) if fire['active'] else None,
        },
    })


# ==========================================
#  AP の区間ごとの指示
# ==========================================
# 区間は隣り合う AP の間（0〜100m、100〜200m …）。AP を足す・距離を変えると区間も変わる。
# 区間に指示を出すと、その区間に今いるウォッチに個別指示（device_instructions）を送る（「なし」も送る）。
# あとから区間に入ったウォッチには、その区間の指示が「なし」以外なら送る（「なし」の区間に入っても今の指示は消さない）。
# 区間の指示のあとに個別に出した指示は、別の区間に移るか区間の指示が変わるまで残る。

def ap_segments(ap_map):
    """[{key, start_m, end_m, start, end}]（start / end はマップ横軸の比率）"""
    ds = sorted({e['distance_m'] for e in ap_map.entries.values()})
    out = []
    for a, b in zip(ds, ds[1:]):
        out.append({'key': f"{a:g}-{b:g}", 'start_m': a, 'end_m': b,
                    'start': round(ap_map.to_ratio(a), 4), 'end': round(ap_map.to_ratio(b), 4)})
    return out


def segment_for_distance(segments, distance_m):
    if not segments or distance_m is None:
        return None
    for seg in segments:
        if distance_m < seg['end_m']:
            return seg
    return segments[-1]


def load_segment_instructions():
    """segment_key → 行。テーブルが無ければ空"""
    try:
        rows = supabase.table(TABLE_SEGMENT_INSTRUCTIONS).select("*").execute().data or []
    except Exception as e:
        print(f"Error loading segment_instructions: {e}")
        return {}
    return {r['segment_key']: r for r in rows if r.get('segment_key')}


def load_device_segment_state():
    try:
        rows = supabase.table(TABLE_DEVICE_SEGMENT_STATE).select("*").execute().data or []
    except Exception as e:
        print(f"Error loading device_segment_state: {e}")
        return {}
    return {r['device_id']: r for r in rows if r.get('device_id')}


def send_segment_instruction(device_id, seg_key, row, now):
    """区間の指示を個別指示として送り、送ったことを記録する"""
    supabase.table(TABLE_DEVICE_INSTRUCTIONS).upsert({
        'device_id': device_id, 'instruction': row['instruction'], 'updated_at': now,
    }).execute()
    supabase.table(TABLE_DEVICE_SEGMENT_STATE).upsert({
        'device_id': device_id, 'segment_key': seg_key, 'segment_updated_at': row.get('updated_at'), 'updated_at': now,
    }).execute()


def apply_segment_instructions(positions, segments, seg_rows=None):
    """区間に入ったウォッチに、その区間の指示を送る（GET /api/wifi_map から毎回呼ぶ。変化があったときだけ書く）。
    戻り値: 送った device_id の集合"""
    seg_rows = load_segment_instructions() if seg_rows is None else seg_rows
    if not segments:
        return set()
    states = load_device_segment_state()
    now = now_iso()
    sent = set()
    for did, pos in (positions or {}).items():
        seg = segment_for_distance(segments, pos.get('distance_m'))
        if seg is None:
            continue
        row = seg_rows.get(seg['key'])
        state = states.get(did) or {}
        moved = state.get('segment_key') != seg['key']
        changed = row is not None and state.get('segment_updated_at') != row.get('updated_at')
        try:
            if row and row.get('instruction') not in (None, 'none') and (moved or changed):
                send_segment_instruction(did, seg['key'], row, now)
                sent.add(did)
            elif moved:
                # 「なし」の区間に入った: 指示は変えず、どの区間にいるかだけ覚える（次に区間の指示が出たら送る）
                supabase.table(TABLE_DEVICE_SEGMENT_STATE).upsert({
                    'device_id': did, 'segment_key': seg['key'],
                    'segment_updated_at': (row or {}).get('updated_at'), 'updated_at': now,
                }).execute()
        except Exception as e:
            print(f"Error applying segment instruction to {did}: {e}")
    return sent


def segments_with_instructions(segments, seg_rows, positions):
    by_seg = {}
    for did, pos in (positions or {}).items():
        seg = segment_for_distance(segments, pos.get('distance_m'))
        if seg:
            by_seg.setdefault(seg['key'], []).append(did)
    return [dict(seg, instruction=(seg_rows.get(seg['key']) or {}).get('instruction') or 'none',
                 device_ids=sorted(by_seg.get(seg['key'], []))) for seg in segments]


@app.route('/api/segment_instructions', methods=['GET', 'POST'])
@login_required
def handle_segment_instructions():
    """GET は区間の一覧（指示・いるウォッチ付き）。POST {segment_key, instruction} で区間に指示を出し、
    その区間に今いるウォッチ全員に個別指示として送る（instruction は DEVICE_INSTRUCTIONS のどれか）"""
    ap_map = load_ap_map()
    segments = ap_segments(ap_map)
    reports = load_wifi_reports()
    positions, _ = estimate_positions(reports, ap_map, load_area_order(), load_area_table())
    if request.method == 'GET':
        return jsonify(segments_with_instructions(segments, load_segment_instructions(), positions))

    data = request.json or {}
    key = str(data.get('segment_key') or '')
    instruction = data.get('instruction')
    seg = next((x for x in segments if x['key'] == key), None)
    if seg is None:
        return jsonify({'error': 'その区間はありません（AP の配置が変わった可能性があります）'}), 400
    if instruction not in DEVICE_INSTRUCTIONS:
        return jsonify({'error': f'instruction は {sorted(DEVICE_INSTRUCTIONS)} のいずれかである必要があります'}), 400
    now = now_iso()
    row = {'segment_key': key, 'start_m': seg['start_m'], 'end_m': seg['end_m'], 'instruction': instruction, 'updated_at': now}
    try:
        supabase.table(TABLE_SEGMENT_INSTRUCTIONS).upsert(row).execute()
        sent = []
        for did, pos in positions.items():
            here = segment_for_distance(segments, pos.get('distance_m'))
            if here and here['key'] == key:
                send_segment_instruction(did, key, row, now)   # 区間に指示を出したときは「なし」も送る
                sent.append(did)
    except Exception as e:
        print(f"Error saving segment instruction {key}: {e}")
        return jsonify({'error': '保存に失敗しました（supabase/segment_instructions.sql は実行済みですか？）'}), 500
    return jsonify({'message': 'saved', 'segment_key': key, 'instruction': instruction, 'sent_device_ids': sorted(sent)})


def positions_method(positions):
    """推定に使った方式（装置がいなくても画面に出すため、設定から読む）"""
    for pos in (positions or {}).values():
        return pos.get('method')
    return load_position_method()


@app.route('/api/position_settings', methods=['GET', 'POST'])
@login_required
def handle_position_settings():
    """位置推定の方式。GET {method, methods: [{key, label}], ...定数}、POST {method}"""
    if request.method == 'GET':
        return jsonify({
            'method': load_position_method(),
            'methods': [{'key': k, 'label': label} for k, label in POSITION_METHODS],
            'path_loss_n': PATH_LOSS_N,
            'source_weight': SOURCE_WEIGHT,
        })
    method = (request.json or {}).get('method')
    if method not in POSITION_METHOD_KEYS:
        return jsonify({'error': f'method は {", ".join(POSITION_METHOD_KEYS)} のどれかにしてください'}), 400
    try:
        supabase.table(TABLE_POSITION_SETTINGS).upsert({'id': 1, 'method': method, 'updated_at': now_iso()}).execute()
    except Exception as e:
        print(f"Error saving position_settings: {e}")
        return jsonify({'error': '保存に失敗しました（supabase/scan_reports.sql は実行済みですか？）'}), 500
    return jsonify({'message': 'saved', 'method': method})


def summarize_position_eval(rows):
    """方式ごとの誤差のまとめ（平均・90% 点・件数）"""
    out = []
    for key, label in POSITION_METHODS:
        errs = sorted(abs(r[key] - r['true_distance_m']) for r in rows
                      if isinstance(r.get(key), (int, float)) and isinstance(r.get('true_distance_m'), (int, float)))
        out.append({
            'key': key, 'label': label, 'count': len(errs),
            'mean_abs_m': round(sum(errs) / len(errs), 1) if errs else None,
            'p90_abs_m': round(errs[min(len(errs) - 1, int(len(errs) * 0.9))], 1) if errs else None,
        })
    return out


@app.route('/api/position_eval', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_position_eval():
    """現地での比較記録。POST {device_id, true_distance_m, note?} で、その時点の ①〜④ の推定を正しい位置と一緒に保存。
    GET は方式ごとの誤差のまとめと直近の記録、DELETE は全記録の削除。"""
    if request.method == 'GET':
        try:
            rows = supabase.table(TABLE_POSITION_EVAL).select("*").order("id", desc=True).limit(2000).execute().data or []
        except Exception as e:
            print(f"Error loading position_eval: {e}")
            rows = []
        return jsonify({'summary': summarize_position_eval(rows), 'recent': rows[:20]})

    if request.method == 'DELETE':
        try:
            supabase.table(TABLE_POSITION_EVAL).delete().gte('id', 0).execute()
        except Exception as e:
            print(f"Error deleting position_eval: {e}")
            return jsonify({'error': '削除に失敗しました'}), 500
        return jsonify({'message': 'deleted'})

    data = request.json or {}
    device_id = str(data.get('device_id') or '')
    try:
        true_m = float(data.get('true_distance_m'))
    except (TypeError, ValueError):
        return jsonify({'error': 'true_distance_m（入口からの正しい距離 m）を数値で指定してください'}), 400
    reports = [r for r in (load_wifi_reports() or []) if r.get('device_id') == device_id]
    if not reports:
        return jsonify({'error': 'その装置のレポートがありません'}), 404
    positions, _ = estimate_positions(reports, load_ap_map(), load_area_order(), load_area_table())
    pos = positions.get(device_id)
    if pos is None:
        return jsonify({'error': '今はこの装置の位置が出せません（AP が見えていない）'}), 409
    row = {'device_id': device_id, 'true_distance_m': true_m, 'method_selected': pos.get('method'),
           'sources': ','.join(pos.get('sources') or []), 'note': str(data.get('note') or '')[:200] or None}
    row.update({k: (pos.get('methods') or {}).get(k) for k in POSITION_METHOD_KEYS})
    try:
        try:
            supabase.table(TABLE_POSITION_EVAL).insert(row).execute()
        except Exception as e:
            # 後から足した方式の列（ALTER TABLE）がまだ無い DB では、その列を外して保存する
            print(f"position_eval insert retry without newer columns: {e}")
            for k in POSITION_EVAL_LATER_COLUMNS:
                row.pop(k, None)
            supabase.table(TABLE_POSITION_EVAL).insert(row).execute()
    except Exception as e:
        print(f"Error saving position_eval: {e}")
        return jsonify({'error': '保存に失敗しました（supabase/scan_reports.sql は実行済みですか？）'}), 500
    return jsonify({'message': 'saved', 'row': row})


@app.route('/api/fire_location', methods=['GET', 'POST', 'DELETE'])
@login_required
def handle_fire_location():
    """管理マップで指定した火災位置。POST {ratio}（マップ横軸 0〜1）か {distance_m}、DELETE で解除。
    保存後すぐに各ウォッチ向けの device_fire_alerts も更新する"""
    if request.method == 'GET':
        return jsonify(load_fire_location())

    ap_map = load_ap_map()
    if request.method == 'POST':
        data = request.json or {}
        try:
            if data.get('distance_m') is not None:
                distance = float(data['distance_m'])
            else:
                distance = ap_map.from_ratio(float(data['ratio']))
        except (KeyError, TypeError, ValueError):
            return jsonify({'error': 'ratio（0〜1）か distance_m を数値で指定してください'}), 400
        distance = round(ap_map.clamp(distance))
        payload = {'id': 1, 'active': True, 'distance_m': distance, 'updated_at': now_iso()}
    else:
        payload = {'id': 1, 'active': False, 'distance_m': None, 'updated_at': now_iso()}

    try:
        supabase.table(TABLE_FIRE_LOCATION).upsert(payload).execute()
    except Exception as e:
        # 例外の詳細はサーバーログにだけ出す（画面には返さない）
        print(f"Error saving fire_location: {e}")
        return jsonify({'error': '火災位置の保存に失敗しました（supabase/fire_location.sql は実行済みですか？）'}), 500

    reports = load_wifi_reports()
    positions, _ = estimate_positions(reports, ap_map, load_area_order(), load_area_table())
    update_fire_alerts(reports, positions, load_fire_location(), ap_map)
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
        positions, _ = estimate_positions(dev_info, load_ap_map(), load_area_order(), load_area_table())

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
    ap_map = load_ap_map()
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
        at_entry = bool(ap_map) and (mac1 in ap_map or mac2 in ap_map)

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
            "load_ap_map":        load_ap_map().entries,
            "load_area_order":    area_order,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host="0.0.0.0", port=5000, debug=False)