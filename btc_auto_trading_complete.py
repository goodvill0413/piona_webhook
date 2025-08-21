import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# .env 파일 로드
load_dotenv()

# 환경 변수 불러오기
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# Bybit 테스트넷 클라이언트 생성
client = HTTP(
    testnet=True,
    api_key=API_KEY,
    api_secret=API_SECRET
)

# Flask 앱 생성
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    print("🔔 웹훅 데이터 수신:", data)

    try:
        signal = data['signal']
        quantity = float(data.get('quantity', 0.01))

        if signal == 'buy':
            order = client.place_order(
                category="linear",
                symbol="BTCUSDT",
                side="Buy",
                order_type="Market",
                qty=quantity,
                time_in_force="GoodTillCancel"
            )
        elif signal == 'sell':
            order = client.place_order(
                category="linear",
                symbol="BTCUSDT",
                side="Sell",
                order_type="Market",
                qty=quantity,
                time_in_force="GoodTillCancel"
            )
        else:
            return jsonify({"error": "Invalid signal"}), 400

        print("✅ 주문 성공:", order)
        return jsonify(order)

    except Exception as e:
        print("❌ 오류 발생:", e)
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(port=5000)

