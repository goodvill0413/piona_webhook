import os
from dotenv import load_dotenv
from binance.client import Client
from binance.error import ClientError
from flask import Flask, request, jsonify
from datetime import datetime
import logging

# .env 파일 로드
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수 불러오기
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

# Binance Futures Testnet 클라이언트 생성
if API_KEY and API_SECRET:
    client = Client(API_KEY, API_SECRET)
    client.API_URL = 'https://testnet.binancefuture.com'
    logger.info("✅ Binance Testnet 클라이언트 초기화 완료")
else:
    client = None
    logger.warning("⚠️ Binance API 키가 설정되지 않음")

# Flask 앱 생성
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "PIONA 자동매매 서버가 실행 중입니다!",
        "timestamp": datetime.now().isoformat(),
        "binance_connected": client is not None
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"🔔 웹훅 데이터 수신: {data}")
        print(f"[{datetime.now()}] 웹훅 데이터: {data}")

        if not client:
            logger.error("❌ Binance 클라이언트가 초기화되지 않음")
            return jsonify({"error": "Binance API 키가 설정되지 않았습니다"}), 500

        # 신호와 수량 추출
        signal = data.get('signal', data.get('side'))
        quantity = float(data.get('quantity', 0.001))
        symbol = data.get('symbol', 'BTCUSDT')

        logger.info(f"📊 거래 신호: {signal}, 수량: {quantity}, 심볼: {symbol}")

        if signal == 'buy' or signal == 'BUY':
            order = client.futures_create_order(
                symbol=symbol,
                side='BUY',
                type='MARKET',
                quantity=quantity
            )
        elif signal == 'sell' or signal == 'SELL':
            order = client.futures_create_order(
                symbol=symbol,
                side='SELL',
                type='MARKET',
                quantity=quantity
            )
        else:
            logger.error(f"❌ 잘못된 신호: {signal}")
            return jsonify({"error": "잘못된 신호입니다. 'buy' 또는 'sell'이어야 합니다."}), 400

        logger.info(f"✅ 주문 성공: {order}")
        print(f"✅ [{datetime.now()}] 주문 성공: {order}")
        
        return jsonify({
            "status": "success",
            "message": "주문이 성공적으로 실행되었습니다",
            "order": order,
            "timestamp": datetime.now().isoformat()
        })

    except ClientError as e:
        error_msg = f"Binance ClientError: {e.error_code} - {e.message}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 500

    except Exception as e:
        error_msg = f"알 수 없는 오류: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 500

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "binance_connected": client is not None
    })

@app.route('/balance')
def balance():
    try:
        if not client:
            return jsonify({"error": "Binance 클라이언트가 초기화되지 않음"}), 500
            
        balance = client.futures_account_balance()
        return jsonify({"balance": balance})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
