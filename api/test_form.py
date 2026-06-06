import os
from flask import Flask,render_template, jsonify, request
from supabase import create_client, Client

app = Flask(__name__)

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
supabase: Client = create_client(url, key)

@app.route('/api/test-form', methods=['GET', 'POST'])
def test_form():
    msg = None
    
    # ユーザーがボタンを押してデータを送ってきたとき (POST)
    if request.method == 'POST':
        data = request.form.get("name")
        
        try:
            # データを追加（インサート）
            supabase.table("testing_table").insert({"value": data}).execute()
            msg = f"成功：【{data}】をSupabaseに追加しました！"
            
        except Exception as e:
            msg = f"失敗：理由: {str(e)}"
            
    # 画面を表示する（GETのとき、およびPOSTのデータ追加が終わったあと）
    # api/templates/form.html を読み込んで、msgの文字を画面に渡します
    return render_template("sql_test.html", msg=msg)