"""仕様Q&A ページ（dist/spec_qa.html）を作る。

scripts/spec_qa/template.html に、仕様書・開発ガイド・主要なソースを埋め込んで1枚の HTML にする。
できたページは Claude の Artifact として公開し、共同開発者に共有する（docs/AI_WORKFLOW.md §2-C）。
仕様書やコードを変えたら、これを実行し直して同じ Artifact に公開し直す。

使い方（リポジトリのどこからでも可）:
    python scripts/build_spec_qa.py

秘密情報（.env、firmware の config.h、app.py の secret_key の値）は入れない。
"""

import base64
import datetime
import json
import pathlib
import re
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "scripts" / "spec_qa" / "template.html"
OUT = ROOT / "dist" / "spec_qa.html"
BANNER = ROOT / "api" / "static" / "banner.png"

# 先頭2つ（開発ガイドと仕様書）は毎回 Claude に全文を渡す。残りは Claude が道具で必要な所だけ読む
FILES = [
    "AGENTS.md",
    "SPEC.md",
    "api/app.py",
    "api/static/admin.js",
    "api/templates/index.html",
    "api/templates/login.html",
    "api/static/style.css",
    "api/vercel.json",
    "requirements.txt",
    "supabase/fire_location.sql",
    "supabase/ap_nodes.sql",
    "firmware/esp32s3_ap/esp32s3_ap.ino",
    "firmware/esp32s3_ap/config.example.h",
    "firmware/esp32s3_ap/README.md",
    "docs/AI_WORKFLOW.md",
]

NEVER = {".env", "config.h"}

# ページは共有されるので、コードに直書きされた秘密の値は伏せる
REDACTIONS = [
    (re.compile(r"(app\.secret_key\s*=\s*)(['\"]).*?\2"), r"\1'（伏せ字: 本物の値はリポジトリを参照）'"),
]


def git_revision():
    try:
        rev = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %ad", "--date=short"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return rev + ("（未コミットの変更を含む）" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "不明"


def main():
    files = {}
    for rel in FILES:
        path = ROOT / rel
        if path.name in NEVER or not path.is_file():
            print(f"スキップ: {rel}")
            continue
        text = path.read_text(encoding="utf-8")
        for pattern, repl in REDACTIONS:
            text = pattern.sub(repl, text)
        files[rel] = text

    for required in ("AGENTS.md", "SPEC.md"):
        if required not in files:
            raise SystemExit(f"{required} が見つかりません")

    bundle = {
        "generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "revision": git_revision(),
        "files": files,
    }
    # </script> で途中終了しないよう、< をエスケープして埋め込む
    bundle_json = json.dumps(bundle, ensure_ascii=False).replace("<", "\\u003c")
    banner = "data:image/png;base64," + base64.b64encode(BANNER.read_bytes()).decode("ascii")

    html = TEMPLATE.read_text(encoding="utf-8")
    html = html.replace("__BANNER__", banner, 1).replace("__BUNDLE__", bundle_json, 1)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    print(f"書き出しました: {OUT}（{len(files)} ファイル、{OUT.stat().st_size / 1024:.0f} KB）")


if __name__ == "__main__":
    main()
