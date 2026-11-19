"""ESP32 カメラを、カメラごとの設定ファイルでコンパイル・書き込みする。

使い方:
  python scripts/flash_camera.py --list                 設定ファイルの一覧と、つながっている ESP32
  python scripts/flash_camera.py cam-02 COM11           cam-02 の設定で書き込む
  python scripts/flash_camera.py cam-02 --compile-only  書き込まずにコンパイルだけ

設定ファイル（Git に入らない）:
  firmware/esp32cam_uplink/configs/common.h       全カメラ共通（Wi-Fi・サーバー・トークン・画質）
  firmware/esp32cam_uplink/configs/<カメラID>.h   1台ごと（CAMERA_ID・名前・距離・近くで見る Wi-Fi 名）
ひな形は同じフォルダの *.example.h。

スケッチ一式を作業用フォルダにコピーし、そこで config.h を「#include "<カメラID>.h"」にして
arduino-cli でコンパイルする（元のフォルダの config.h は使わない・書き換えない）。
arduino-cli は PATH、環境変数 ARDUINO_CLI、Arduino IDE 2 の同梱版の順に探す。
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH = ROOT / "firmware" / "esp32cam_uplink"
CONFIGS = SKETCH / "configs"
# ESP32S3 Dev Module・OPI PSRAM・Custom パーティション・QIO・USB CDC On Boot Enabled（README と同じ）
FQBN = "esp32:esp32:esp32s3:PSRAM=opi,PartitionScheme=custom,FlashMode=qio,CDCOnBoot=cdc"
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,17}$")


def find_cli():
    for cand in (shutil.which("arduino-cli"), os.environ.get("ARDUINO_CLI")):
        if cand and Path(cand).exists():
            return cand
    local = os.environ.get("LOCALAPPDATA")
    if local:
        p = Path(local) / "Programs" / "Arduino IDE" / "resources" / "app" / "lib" / "backend" / "resources" / "arduino-cli.exe"
        if p.exists():
            return str(p)
    sys.exit("arduino-cli が見つかりません。PATH に入れるか、環境変数 ARDUINO_CLI にパスを入れてください")


def camera_files():
    return sorted(p for p in CONFIGS.glob("*.h") if not p.name.endswith(".example.h") and p.name != "common.h")


def check_config(camera_id):
    path = CONFIGS / f"{camera_id}.h"
    if not path.exists():
        sys.exit(f"{path.relative_to(ROOT)} がありません。configs/camera.example.h をコピーして作ってください")
    if not (CONFIGS / "common.h").exists():
        sys.exit("configs/common.h がありません。configs/common.example.h をコピーして作ってください")
    text = path.read_text(encoding="utf-8")
    m = re.search(r'^\s*#define\s+CAMERA_ID\s+"([^"]*)"', text, re.M)
    if not m:
        sys.exit(f"{path.name} に CAMERA_ID がありません")
    if m.group(1) != camera_id:
        sys.exit(f"{path.name} の CAMERA_ID が \"{m.group(1)}\" です。ファイル名と同じにしてください")
    return path


def check_duplicates():
    """CAMERA_ID と LOCAL_AP_SSID が他のカメラと重なっていないか（重なると混線・上書きになる）"""
    seen = {}
    for p in camera_files():
        text = p.read_text(encoding="utf-8")
        for key in ("CAMERA_ID", "LOCAL_AP_SSID"):
            m = re.search(rf'^\s*#define\s+{key}\s+"([^"]*)"', text, re.M)
            if m:
                other = seen.get((key, m.group(1)))
                if other:
                    sys.exit(f"{p.name} と {other} の {key} が同じ（\"{m.group(1)}\"）です。カメラごとに変えてください")
                seen[(key, m.group(1))] = p.name


def list_all(cli):
    print("設定ファイル（configs/）:")
    files = camera_files()
    for p in files:
        m = re.search(r'^\s*#define\s+CAMERA_LABEL\s+"([^"]*)"', p.read_text(encoding="utf-8"), re.M)
        print(f"  {p.stem:<18} {m.group(1) if m else ''}")
    if not files:
        print("  （まだありません。configs/camera.example.h をコピーして作る）")
    print("common.h:", "あり" if (CONFIGS / "common.h").exists() else "なし（configs/common.example.h をコピーして作る）")
    print("\nつながっている ESP32:")
    out = subprocess.run([cli, "board", "list"], capture_output=True, text=True, encoding="utf-8", errors="replace").stdout
    ports = [line.split()[0] for line in out.splitlines() if "ESP32" in line and line.split()[0].upper().startswith(("COM", "/DEV"))]
    print("  " + (", ".join(ports) if ports else "見つかりません（UART 側の USB 口だと Unknown と出ることがあります）"))


def main():
    ap = argparse.ArgumentParser(description="ESP32 カメラをカメラごとの設定で書き込む")
    ap.add_argument("camera_id", nargs="?", help="configs/<カメラID>.h のカメラID")
    ap.add_argument("port", nargs="?", help="書き込むポート（例 COM9）")
    ap.add_argument("--list", action="store_true", help="設定ファイルとポートの一覧")
    ap.add_argument("--compile-only", action="store_true", help="書き込まずにコンパイルだけ")
    args = ap.parse_args()
    cli = find_cli()

    if args.list or not args.camera_id:
        list_all(cli)
        return
    if not ID_RE.match(args.camera_id):
        sys.exit("カメラID は英数字・_・- で 17 文字までにしてください")
    if not args.port and not args.compile_only:
        sys.exit("ポートを指定してください（例 COM9）。一覧は --list")
    check_config(args.camera_id)
    check_duplicates()

    # 作業用フォルダは毎回同じ場所にする。arduino-cli はフォルダの場所ごとに組み立て結果を取っておくので、
    # 2回目からはライブラリ（BLE など）を組み立て直さずに済む（初回は 10 分ほどかかる）
    work = Path(tempfile.gettempdir()) / "mamotchi-cam-build"
    build = work / "esp32cam_uplink"   # フォルダ名は .ino と同じにする（Arduino の決まり）
    if build.exists():
        shutil.rmtree(build)
    build.mkdir(parents=True)
    try:
        for p in SKETCH.iterdir():
            if p.is_file() and p.name != "config.h" and p.suffix in (".ino", ".h", ".cpp", ".c", ".csv"):
                shutil.copy2(p, build / p.name)
        for p in CONFIGS.glob("*.h"):
            if not p.name.endswith(".example.h"):
                shutil.copy2(p, build / p.name)
        (build / "config.h").write_text(f'#pragma once\n#include "{args.camera_id}.h"\n', encoding="utf-8")

        cmd = [cli, "compile", "--fqbn", FQBN]
        if not args.compile_only:
            cmd += ["--upload", "-p", args.port]
        cmd.append(str(build))
        print(f"== {args.camera_id} を{'コンパイル' if args.compile_only else f' {args.port} に書き込み'}", flush=True)
        rc = subprocess.run(cmd).returncode
    finally:
        # パスワード・トークン入りの設定は作業用フォルダに残さない（組み立て結果は arduino-cli 側に残る）
        for p in build.glob("*.h"):
            p.unlink()
    if rc != 0:
        sys.exit(rc)
    if not args.compile_only:
        print("書き込み完了。ダッシュボードの「カメラ」と「ESP32 AP」表に 30 秒ほどで出ます。距離を入れてください")


if __name__ == "__main__":
    main()
