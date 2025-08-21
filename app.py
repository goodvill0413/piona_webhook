import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import logging

# .env 파일에서 환경 변수를 로드합니다.
load_dotenv()

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# 환경 변수에서 API 키와 시크릿을 불러옵니다.
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")

# API 키가 설정되지 않았을 경우 오류를 발생시킵니다.
if not API_KEY or not API_SECRET:
    raise ValueError("API_KEY와 API_SECRET 환경 변수를 설정해야 합니다.")

# Bybit 테스트넷 클라이언트를 생성합니다. (실제 거래 시 testnet=False로 변경)
try:
    client = HTTP(
        testnet=True,
        api_key=API_KEY,
        api_secret=API_SECRET
    )
    logging.info("Bybit 클라이언트가 성공적으로 생성되었습니다.")
except Exception as e:
    logging.error(f"Bybit 클라이언트 생성 실패: {e}")
    raise

# Flask 웹 애플리케이션을 생성합니다.
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """
    트레이딩뷰 웹훅 신호를 받아 Bybit에 주문을 실행하는 함수
    """
    try:
        # 웹훅으로 들어온 JSON 데이터를 파싱합니다.
        data = request.get_json()
        if not data:
            logging.warning("수신된 데이터가 없습니다.")
            return jsonify({"status": "error", "message": "No data received"}), 400

        logging.info(f"� 웹훅 데이터 수신: {data}")

        # Pine Script에서 보낸 데이터 키를 파싱합니다.
        action = data.get('action')
        side = data.get('side')
        quantity = data.get('qty')
        symbol = data.get('symbol', 'BTCUSDT') # 기본값으로 BTCUSDT 사용

        # 필수 데이터가 있는지 확인합니다.
        if not all([action, side, quantity]):
            logging.error(f"필수 데이터 누락: action={action}, side={side}, qty={quantity}")
            return jsonify({"status": "error", "message": "Missing required fields: action, side, qty"}), 400
        
        # 수량을 float 형태로 변환합니다.
        try:
            quantity = float(quantity)
        except ValueError:
            logging.error(f"잘못된 수량 값: {quantity}")
            return jsonify({"status": "error", "message": "Invalid quantity value"}), 400

        order_side = ""
        if side == 'long':
            order_side = "Buy"
        elif side == 'short':
            order_side = "Sell"
        else:
            # 'long' 또는 'short'가 아닌 다른 side 값은 무시하거나 로깅합니다.
            logging.info(f"처리할 수 없는 side 값 수신: {side}")
            return jsonify({"status": "ignored", "message": f"Side '{side}' is not a trading action"}), 200

        # 'entry' 액션일 때만 주문을 실행합니다.
        if action == 'entry':
            logging.info(f"🚀 주문 실행 준비: {symbol} | {order_side} | {quantity}")
            
            # Bybit에 시장가 주문을 넣습니다.
            order = client.place_order(
                category="linear",
                symbol=symbol,
                side=order_side,
                order_type="Market",
                qty=str(quantity), # qty는 문자열 형태로 전달해야 합니다.
                time_in_force="GoodTillCancel"
            )
            
            logging.info(f"✅ 주문 성공: {order}")
            return jsonify({"status": "success", "order_result": order}), 200
        else:
            # 'entry'가 아닌 다른 action(예: trail_update, time_exit)은 무시합니다.
            logging.info(f"'{action}' 액션은 무시합니다.")
            return jsonify({"status": "ignored", "message": f"Action '{action}' was ignored"}), 200

    except Exception as e:
        logging.error(f"❌ 웹훅 처리 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/balance', methods=['GET'])
def get_balance():
    """
    Bybit 계정의 잔액 정보를 조회하는 함수 (여러 지갑 종류 확인)
    """
    try:
        logging.info("💰 잔액 조회 요청 수신")
        
        account_types_to_check = ["UNIFIED", "CONTRACT"] # 확인할 지갑 종류 목록
        all_balances = {}

        for acc_type in account_types_to_check:
            balance_info = client.get_wallet_balance(accountType=acc_type)
            if balance_info and balance_info['retCode'] == 0:
                coin_list = balance_info['result']['list']
                if coin_list and coin_list[0]['totalWalletBalance'] != '0':
                    logging.info(f"✅ '{acc_type}' 지갑에서 잔액 발견!")
                    all_balances[acc_type] = coin_list
                    break # 잔액을 찾으면 중단
        
        if not all_balances:
            logging.warning("모든 지갑 종류에서 잔액을 찾을 수 없습니다.")
            return jsonify({
                "status": "warning", 
                "message": "Could not find balance in UNIFIED or CONTRACT accounts.",
                "raw_response_unified": client.get_wallet_balance(accountType="UNIFIED")
            }), 404

        return jsonify({"status": "success", "balances": all_balances}), 200

    except Exception as e:
        logging.error(f"❌ 잔액 조회 중 오류 발생: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Render와 같은 배포 환경에서는 Gunicorn과 같은 WSGI 서버를 사용하므로,
    # 이 부분은 로컬 테스트용으로만 사용됩니다.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
