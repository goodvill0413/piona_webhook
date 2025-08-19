from flask import Flask, request, jsonify
import json
import logging
from datetime import datetime
import os

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "PIONA Webhook Server is running!",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # 트레이딩뷰에서 오는 데이터 받기
        data = request.get_json()
        
        # 로그 출력
        logger.info(f"Webhook received: {data}")
        print(f"[{datetime.now()}] Webhook Data: {json.dumps(data, indent=2)}")
        
        # 나중에 여기서 바이낸스 봇 실행할 예정
        # TODO: Binance Testnet 봇 실행 로직 추가
        
        return jsonify({
            "status": "success",
            "message": "Webhook received successfully",
            "received_data": data,
            "timestamp": datetime.now().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({
            "status": "error",
            "message": str(e),
            "timestamp": datetime.now().isoformat()
        }), 400

@app.route('/health')
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
