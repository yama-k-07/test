import os
from flask import Flask, request, jsonify, render_template_string
from supabase import create_client, Client
from dotenv import load_dotenv

# ローカル開発用（.envファイルがある場合のみ読み込み）
load_dotenv()

app = Flask(__name__)

# Supabaseクライアントの初期化
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

# データを追加するAPIエンドポイント
@app.route('/add', methods=['POST'])
def add_data():
    try:
        # JSONリクエスト、またはフォームデータから値を取得
        data = request.get_json() if request.is_json else request.form
        name_value = data.get('name')

        if not name_value:
            return jsonify({"error": "Name is required"}), 400

        # Supabaseのテーブルにデータを挿入
        # 'your_table_name' を実際のテーブル名に、'name' を実際のカラム名に変更してください
        response = supabase.table("your_table_name").insert({"name": name_value}).execute()

        return jsonify({"message": "Success", "data": response.data}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 簡易的なテスト用画面（ブラウザ確認用）
@app.route('/')
def index():
    return render_template_string('''
        <form action="/add" method="POST">
            <input type="text" name="name" placeholder="名前を入力" required>
            <button type="submit">追加</button>
        </form>
    ''')