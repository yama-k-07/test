"""デモ用: ウォッチの代わりに、トンネルを歩く作業者のスキャン結果を Supabase に入れ続ける。

本物のウォッチと同じ表（wifi_reports_v2・ble_reports）に書くので、ダッシュボードのマップ・
区間の指示・位置推定の比較がそのまま動く。**api/.env の Supabase（ふつうは本番）に書き込む**。
デモ用の装置 ID は必ず「demo-」で始まり、--cleanup でまとめて消せる。

使い方（リポジトリのいちばん上で。api/.env が必要）:
  python scripts/demo_watch.py --dry-run              書き込まずに、何を入れるかだけ表示（最初に試す）
  python scripts/demo_watch.py                        2人が 10 分間歩く（Ctrl+C で止める）
  python scripts/demo_watch.py --workers 3 --minutes 5 --auto-eval
  python scripts/demo_watch.py --cleanup              demo- の行をすべて消す（デモの後に必ず）

--auto-eval を付けると 15 秒ごとに「本当の位置」と ①〜⑥ の推定を position_eval に記録する
（画面の「位置推定の方式」の表に方式ごとの誤差がたまる）。

電波の作り方（シミュレーション）:
  RSSI = 1m での強さ − 10·n·log10(距離) ＋ ばらつき（正規分布）。距離は高さの差 3m を入れた直線距離。
  BLE ビーコン = 「ESP32 AP」表の行のうち fw が ble- で始まるもの。
  Wi-Fi AP = 「AP位置設定」の行と、「ESP32 AP」表のうち BLE でないもの。
  距離が入っていない AP・使わない AP は使わない（サーバーの load_ap_map と同じ）。
"""
import argparse
import math
import os
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

DEMO_PREFIX = "demo-"
TABLES_WITH_DEVICE = ["wifi_reports", "wifi_reports_v2", "ble_reports", "device_instructions",
                      "device_segment_state", "entry_current", "entry_log", "position_eval"]

# 電波のモデル（値は一般的な目安。現地の電波とは違う）
BLE_P1M, BLE_N, BLE_NOISE, BLE_MIN = -59.0, 2.2, 4.0, -95.0
WIFI_P1M, WIFI_N, WIFI_NOISE, WIFI_MIN = -40.0, 2.0, 4.0, -92.0
HEIGHT_M = 3.0
WALK_MPS = (0.9, 1.4)        # 歩く速さの範囲
PAUSE_SEC = (5, 20)          # 端や途中で立ち止まる時間


def load_app():
    if not (ROOT / "api" / ".env").exists():
        sys.exit("api/.env がありません（AGENTS.md §5）。Supabase の URL とキーを置いてください")
    import app as appmod   # api/app.py。load_dotenv() で api/.env を読む
    return appmod


def ap_layout(appmod):
    """(wifi: [(mac, 距離)], ble: [(mac, 距離)])"""
    wifi, ble = {}, {}
    for row in appmod.load_ap_position_rows():   # 距離は distance_m か位置番号から（サーバーと同じ）
        if row.get('mac') and row.get('distance_m') is not None:
            wifi[appmod.norm_mac(row['mac'])] = row['distance_m']
    for n in appmod.load_ap_nodes():
        if not n.get('mac') or n.get('enabled') is False or n.get('distance_m') is None:
            continue
        mac = appmod.norm_mac(n['mac'])
        if str(n.get('fw') or '').startswith('ble-'):
            ble[mac] = float(n['distance_m'])
            wifi.pop(mac, None)
        else:
            wifi[mac] = float(n['distance_m'])
    return sorted(wifi.items(), key=lambda kv: kv[1]), sorted(ble.items(), key=lambda kv: kv[1])


def rssi_at(x, d, p1m, n, noise):
    r = math.sqrt((x - d) ** 2 + HEIGHT_M ** 2)
    return p1m - 10 * n * math.log10(r) + random.gauss(0, noise)


def scan(x, aps, p1m, n, noise, floor):
    """強い順の上位3つ [(mac, rssi)]"""
    seen = [(mac, round(rssi_at(x, d, p1m, n, noise))) for mac, d in aps]
    seen = [s for s in seen if s[1] >= floor]
    return sorted(seen, key=lambda s: -s[1])[:3]


def scan_row(device_id, top3, now_iso):
    row = {'device_id': device_id, 'scanned_at': now_iso}
    for i in range(3):
        mac, rssi = top3[i] if i < len(top3) else (None, None)
        row[f'mac0{i + 1}'] = mac
        row[f'rssi0{i + 1}'] = rssi
    return row


class Walker:
    """入口側と奥側の間を行ったり来たりする人"""

    def __init__(self, device_id, start_m, end_m):
        self.device_id = device_id
        self.lo, self.hi = start_m, end_m
        self.x = random.uniform(start_m, end_m)
        self.target = random.choice([start_m, end_m])
        self.speed = random.uniform(*WALK_MPS)
        self.pause = 0.0

    def step(self, dt):
        if self.pause > 0:
            self.pause -= dt
            return
        move = self.speed * dt
        if abs(self.target - self.x) <= move:
            self.x = self.target
            self.pause = random.uniform(*PAUSE_SEC)
            # 次の目的地: 反対の端か、途中のどこか
            self.target = random.choice([self.lo, self.hi, random.uniform(self.lo, self.hi)])
            self.speed = random.uniform(*WALK_MPS)
        else:
            self.x += move if self.target > self.x else -move
        if random.random() < 0.01:   # たまに途中で立ち止まる
            self.pause = random.uniform(*PAUSE_SEC)


def insert(appmod, table, row, dry):
    if dry:
        print(f"  [dry-run] {table}: {row}")
        return True
    try:
        appmod.supabase.table(table).insert(row).execute()
        return True
    except Exception as e:
        print(f"  {table} に書けませんでした: {e}")
        return False


def auto_eval(appmod, walkers, dry):
    reports = [r for r in (appmod.load_wifi_reports() or []) if str(r.get('device_id', '')).startswith(DEMO_PREFIX)]
    if not reports:
        return
    positions, _ = appmod.estimate_positions(reports, appmod.load_ap_map(), appmod.load_area_order(), appmod.load_area_table())
    for w in walkers:
        pos = positions.get(w.device_id)
        if not pos:
            continue
        row = {'device_id': w.device_id, 'true_distance_m': round(w.x, 1), 'method_selected': pos.get('method'),
               'sources': ','.join(pos.get('sources') or []), 'note': 'demo_watch.py --auto-eval'}
        row.update({k: (pos.get('methods') or {}).get(k) for k in appmod.POSITION_METHOD_KEYS})
        if not insert(appmod, appmod.TABLE_POSITION_EVAL, row, dry):
            for k in appmod.POSITION_EVAL_LATER_COLUMNS:
                row.pop(k, None)
            insert(appmod, appmod.TABLE_POSITION_EVAL, row, dry)
        shown = ' '.join(f"{k.split('_')[0]}={v}" for k, v in (pos.get('methods') or {}).items())
        print(f"  記録 {w.device_id}: 本当 {w.x:.0f}m / {shown}")


def cleanup(appmod):
    print(f"device_id が「{DEMO_PREFIX}」で始まる行を消します:")
    for table in TABLES_WITH_DEVICE:
        try:
            appmod.supabase.table(table).delete().like('device_id', f'{DEMO_PREFIX}%').execute()
            print(f"  {table}: 削除しました")
        except Exception as e:
            print(f"  {table}: 消せませんでした（表が無い・権限が無い など）: {e}")


def main():
    ap = argparse.ArgumentParser(description="ウォッチの代わりにデモ用のスキャン結果を入れる")
    ap.add_argument('--workers', type=int, default=2, help='歩く人数（既定 2）')
    ap.add_argument('--minutes', type=float, default=10, help='続ける時間（既定 10 分）')
    ap.add_argument('--ble-sec', type=float, default=1.0, help='BLE を送る間隔（既定 1 秒）')
    ap.add_argument('--wifi-sec', type=float, default=5.0, help='Wi-Fi を送る間隔（既定 5 秒）')
    ap.add_argument('--report', action='store_true', help='demo-01 を通報中にする（マップで赤く光る）')
    ap.add_argument('--no-ble', action='store_true', help='BLE を送らない（Wi-Fi だけの場面）')
    ap.add_argument('--auto-eval', action='store_true', help='15 秒ごとに本当の位置と推定を position_eval に記録')
    ap.add_argument('--dry-run', action='store_true', help='書き込まずに表示だけ（20 秒で終わる）')
    ap.add_argument('--cleanup', action='store_true', help='demo- の行をすべて消して終わる')
    args = ap.parse_args()

    appmod = load_app()
    if args.cleanup:
        cleanup(appmod)
        return

    wifi_aps, ble_aps = ap_layout(appmod)
    if args.no_ble:
        ble_aps = []
    if len(wifi_aps) + len(ble_aps) < 2:
        sys.exit("距離の分かる AP が 2 台未満です。「AP位置設定」か「ESP32 AP」表を確かめてください")
    ds = [d for _, d in wifi_aps + ble_aps]
    start_m, end_m = min(ds), max(ds)
    print(f"Wi-Fi AP {len(wifi_aps)} 台、BLE ビーコン {len(ble_aps)} 台、トンネル {start_m:.0f}〜{end_m:.0f}m")
    if not args.dry_run:
        print("api/.env の Supabase に書き込みます（Ctrl+C で止める。終わったら --cleanup）")

    walkers = [Walker(f"{DEMO_PREFIX}{i + 1:02d}", start_m, end_m) for i in range(args.workers)]
    t0 = time.monotonic()
    last_wifi = last_ble = last_eval = -1e9
    last_print = -1e9
    duration = 20 if args.dry_run else args.minutes * 60
    tick = 0.5
    try:
        while time.monotonic() - t0 < duration:
            now = time.monotonic()
            for w in walkers:
                w.step(tick)
            now_iso = datetime.now(timezone.utc).isoformat()
            if ble_aps and now - last_ble >= args.ble_sec:
                last_ble = now
                for w in walkers:
                    top = scan(w.x, ble_aps, BLE_P1M, BLE_N, BLE_NOISE, BLE_MIN)
                    if top:
                        brow = scan_row(w.device_id, top, now_iso)
                        brow['report'] = bool(args.report and w.device_id == f"{DEMO_PREFIX}01")   # 通報は両方の表に送る
                        insert(appmod, appmod.TABLE_BLE_SCAN, brow, args.dry_run)
            if now - last_wifi >= args.wifi_sec:
                last_wifi = now
                for w in walkers:
                    wtop = scan(w.x, wifi_aps, WIFI_P1M, WIFI_N, WIFI_NOISE, WIFI_MIN) if wifi_aps else []
                    # Wi-Fi の行は AP が見えなくても送る（通報 report を運ぶため。docs/WATCH_SCAN_REPORTS.md）
                    row = scan_row(w.device_id, wtop, now_iso)
                    row['report'] = bool(args.report and w.device_id == f"{DEMO_PREFIX}01")
                    insert(appmod, appmod.TABLE_WIFI_SCAN, row, args.dry_run)
            if now - last_print >= 10:
                last_print = now
                print(f"[{int(now - t0):4d}秒] " + "  ".join(f"{w.device_id} {w.x:5.0f}m" for w in walkers))
            if args.auto_eval and now - last_eval >= 15 and now - t0 > 30:
                last_eval = now
                auto_eval(appmod, walkers, args.dry_run)
            time.sleep(tick)
    except KeyboardInterrupt:
        print("止めました")
    if not args.dry_run:
        print("デモが終わったら: python scripts/demo_watch.py --cleanup")


if __name__ == '__main__':
    main()
