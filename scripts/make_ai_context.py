"""チャット型の生成 AI（ChatGPT・Gemini など）に渡す「まとめファイル」を作る。

AGENTS.md（説明書）・SPEC.md（仕様）・主要なソースを1つの Markdown にまとめて
dist/ai_context.md に書き出す。これを AI にアップロード（または貼り付け）すれば、
AI はどのファイルのどこを直せばよいかを答えられる。

使い方（リポジトリのどこからでも可）:
    python scripts/make_ai_context.py              # 全部入り
    python scripts/make_ai_context.py --no-css     # style.css を除く（容量を減らしたいとき）
    python scripts/make_ai_context.py path/to/file # 指定したファイルだけを追加で入れる

秘密情報（.env、firmware の config.h）は入れない。
"""

import argparse
import datetime
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "ai_context.md"

# 入れる順番が大事: 説明書 → 仕様 → サーバー → 画面 → DB → ファームウェア
FILES = [
    "AGENTS.md",
    "SPEC.md",
    "api/app.py",
    "api/templates/index.html",
    "api/static/admin.js",
    "api/static/style.css",
    "api/templates/login.html",
    "api/vercel.json",
    "requirements.txt",
    "supabase/fire_location.sql",
    "supabase/ap_nodes.sql",
    "firmware/esp32s3_ap/README.md",
    "firmware/esp32s3_ap/esp32s3_ap.ino",
    "firmware/esp32s3_ap/config.example.h",
]

# 絶対に入れないもの（パスワードやキーを含む）
NEVER = {".env", "config.h"}

LANG = {".py": "python", ".js": "javascript", ".html": "html", ".css": "css", ".sql": "sql",
        ".ino": "cpp", ".h": "cpp", ".json": "json", ".md": "markdown", ".txt": "text"}


def git_revision():
    try:
        rev = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%h %ad %s", "--date=short"],
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain", "--untracked-files=no"],
                               capture_output=True, text=True, check=True).stdout.strip()
        return rev + ("（未コミットの変更あり）" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "不明（git が使えない）"


def main():
    parser = argparse.ArgumentParser(description="生成 AI に渡すまとめファイルを作る")
    parser.add_argument("extra", nargs="*", help="追加で入れるファイル（リポジトリからの相対パス）")
    parser.add_argument("--no-css", action="store_true", help="style.css を入れない")
    args = parser.parse_args()

    files = [f for f in FILES if not (args.no_css and f.endswith(".css"))]
    files += [f.replace("\\", "/") for f in args.extra if f.replace("\\", "/") not in files]

    parts = []
    missing = []
    for rel in files:
        path = ROOT / rel
        if path.name in NEVER:
            print(f"スキップ（秘密情報を含むため）: {rel}", file=sys.stderr)
            continue
        if not path.is_file():
            missing.append(rel)
            continue
        text = path.read_text(encoding="utf-8")
        fence = "````" if "```" in text else "```"
        lang = LANG.get(path.suffix, "")
        parts.append(f"## ファイル: `{rel}`\n\n{fence}{lang}\n{text.rstrip()}\n{fence}\n")

    header = (
        "# まもっち プロジェクト まとめ（生成 AI 用）\n\n"
        f"- 作成: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"- 元にしたコミット: {git_revision()}\n"
        f"- 収録ファイル: {len(parts)} 件\n\n"
        "AI へ: 最初の `AGENTS.md` が説明書です。§3「やりたいこと → 編集する場所」で対象を探し、"
        "§4 のルールを守り、§6 の形式で答えてください。以下の各ファイルは `## ファイル: パス` の見出しで区切られています。\n\n"
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(header + "\n".join(parts), encoding="utf-8")

    size_kb = OUT.stat().st_size / 1024
    print(f"書き出しました: {OUT}（{len(parts)} ファイル、{size_kb:.0f} KB）")
    if missing:
        print("見つからなかったファイル: " + ", ".join(missing), file=sys.stderr)


if __name__ == "__main__":
    main()
