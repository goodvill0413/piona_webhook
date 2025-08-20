import os
from dotenv import load_dotenv
import ccxt
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

# CCXT Binance 클라이언트 생성
if API_KEY and API_SECRET:
    try:
        exchange = ccxt.binance({
            'apiKey': API_KEY,
            'secret': API_SECRET,
            'sandbox': True,  # 테스트넷 사용
            'enableRateLimit': True,
        })
        logger.info("✅ CCXT Binance 클라이언트 초기화 완료")
        client_connected = True
    except Exception as e:
        logger.error(f"❌ CCXT 초기화 실패: {e}")
        exchange = None
        client_connected = False
else:
    exchange = None
    client_connected = False
    logger.warning("⚠️ Binance API 키가 설정되지 않음")

# Flask 앱 생성
app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "success", 
        "message": "PIONA 자동매매 서버가 실행 중입니다!",
        "timestamp": datetime.now().isoformat(),
        "binance_connected": client_connected
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logger.info(f"🔔 웹훅 데이터 수신: {data}")
        print(f"[{datetime.now()}] 웹훅 데이터: {data}")

        if not exchange:
            logger.error("❌ Binance 클라이언트가 초기화되지 않음")
            return jsonify({"error": "Binance API 키가 설정되지 않았습니다"}), 500

        # 신호와 수량 추출
        signal = data.get('signal', data.get('side'))
        quantity = float(data.get('quantity', 0.001))
        symbol = data.get('symbol', 'BTC/USDT')

        logger.info(f"📊 거래 신호: {signal}, 수량: {quantity}, 심볼: {symbol}")

        if signal == 'buy' or signal == 'BUY':
            order = exchange.create_market_buy_order(symbol, quantity)
        elif signal == 'sell' or signal == 'SELL':
            order = exchange.create_market_sell_order(symbol, quantity)
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

    except Exception as e:
        error_msg = f"주문 실행 오류: {str(e)}"
        logger.error(f"❌ {error_msg}")
        return jsonify({"error": error_msg}), 500

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy", 
        "timestamp": datetime.now().isoformat(),
        "binance_connected": client_connected
    })

@app.route('/balance')
def balance():
    try:
        if not exchange:
            return jsonify({"error": "Binance 클라이언트가 초기화되지 않음"}), 500
            
        balance = exchange.fetch_balance()
        return jsonify({"balance": balance})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
