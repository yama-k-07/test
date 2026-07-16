from flask import Flask, jsonify
app = Flask(__name__)

# あらゆる /api/xxx のアクセスをここでキャッチします
@app.route('/api/<path:path>')
def catch_all(path):
    return jsonify(message=f"Hello from Flask! You accessed: /api/{path}")

# テスト用に、/api/hello ぴったりでアクセスされた場合
@app.route('/api/hello')
def hello():
    return jsonify(message="Hello from Flask!")