import os
import json
import time
import hmac
import base64
import hashlib
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import logging

# SSL 경고 숨기기
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 환경변수 로드
load_dotenv()

# 로깅 설정 - Render용
logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class OKXTrader:
    def __init__(self):
        self.api_key = os.getenv('OKX_API_KEY')
        self.secret_key = os.getenv('OKX_API_SECRET')
        self.passphrase = os.getenv('OKX_API_PASSPHRASE')
        self.base_url = os.getenv('OKX_BASE_URL', 'https://www.okx.com')
        self.simulated = os.getenv('OKX_SIMULATED', '1')
        self.default_tdmode = os.getenv('DEFAULT_TDMODE', 'isolated')
        self.default_market = os.getenv('DEFAULT_MARKET', 'swap')
        
        logger.info(f"🚀 OKXTrader 초기화 - 시뮬레이션 모드: {'ON' if self.simulated == '1' else 'OFF'}")
        logger.info(f"📊 마켓: {self.default_market}, 거래모드: {self.default_tdmode}")

    def get_timestamp(self):
        return datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3] + 'Z'

    def sign_request(self, method, path, body=""):
        timestamp = self.get_timestamp()
        message = timestamp + method + path + body
        signature = base64.b64encode(
            hmac.new(self.secret_key.encode(), message.encode(), hashlib.sha256).digest()
        ).decode()
        return {
            'OK-ACCESS-KEY': self.api_key,
            'OK-ACCESS-SIGN': signature,
            'OK-ACCESS-TIMESTAMP': timestamp,
            'OK-ACCESS-PASSPHRASE': self.passphrase,
            'Content-Type': 'application/json',
            'x-simulated-trading': self.simulated
        }

    def get_instrument_info(self, symbol):
        """코인의 주문 규칙을 알아내는 함수"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v5/public/instruments?instType=SWAP&instId={symbol}",
                verify=False,
                timeout=10
            )
            
            # 디버그: 실제 응답 확인
            logger.info(f"OKX API 응답 코드: {response.status_code}")
            logger.info(f"OKX API 응답 헤더: {dict(response.headers)}")
            logger.info(f"OKX API 응답 내용: {response.text[:500]}")
            
            # 빈 응답이나 오류 체크 추가!
            if response.text.strip() == "":
                logger.warning(f"⚠️ 빈 응답 받음: {symbol}. 기본 규칙 사용!")
                return {
                    'minSz': '0.001',  # 기본 최소 수량 (BTC-SWAP 기준)
                    'lotSz': '0.001'   # 기본 단위
                }
            data = response.json()
            if data['code'] == '0' and data.get('data'):
                logger.info(f"✅ 심볼 정보 조회 성공: {symbol}, minSz={data['data'][0]['minSz']}, lotSz={data['data'][0]['lotSz']}")
                return data['data'][0]
            logger.error(f"❌ 심볼 정보 조회 실패: {data}")
            # 실패해도 기본값 반환 (주문 계속 진행)
            logger.warning(f"⚠️ 조회 실패로 기본 규칙 사용: {symbol}")
            return {
                'minSz': '0.001',
                'lotSz': '0.001'
            }
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 파싱 오류 (빈 응답?): {e}")
            return {
                'minSz': '0.001',
                'lotSz': '0.001'
            }
        except Exception as e:
            logger.error(f"❌ 심볼 정보 조회 오류: {e}")
            return {
                'minSz': '0.001',
                'lotSz': '0.001'
            }

    def get_ticker(self, symbol):
        """현재가 조회"""
        try:
            response = requests.get(
                f"{self.base_url}/api/v5/market/ticker?instId={symbol}",
                verify=False,
                timeout=10
            )
            data = response.json()
            if data['code'] == '0' and data.get('data'):
                price = float(data['data'][0]['last'])
                logger.info(f"💰 {symbol} 현재가: {price}")
                return price
            logger.error(f"❌ 가격 조회 실패: {data}")
            return None
        except Exception as e:
            logger.error(f"❌ 가격 조회 오류: {e}")
            return None

    def get_positions(self, symbol=None):
        """포지션 조회"""
        method = "GET"
        path = "/api/v5/account/positions"
        if symbol:
            path += f"?instId={symbol}"
        headers = self.sign_request(method, path)
        try:
            response = requests.get(
                self.base_url + path,
                headers=headers,
                verify=False,
                timeout=10
            )
            result = response.json()
            logger.info(f"📊 포지션 조회 완료: {len(result.get('data', []))}개")
            return result
        except Exception as e:
            logger.error(f"❌ 포지션 조회 오류: {e}")
            return {"code": "error", "msg": str(e)}

    def close_position(self, symbol, side):
        """포지션 청산"""
        positions = self.get_positions(symbol)
        logger.info(f"📋 포지션 조회 결과: {positions}")
        if positions['code'] != '0':
            return positions
        
        closed_orders = []
        for pos in positions.get('data', []):
            if pos['instId'] == symbol and float(pos['pos']) != 0:
                pos_side = pos['posSide']
                pos_size = abs(float(pos['pos']))
                close_side = "sell" if pos_side == "long" else "buy"
                logger.info(f"🔄 포지션 청산 시도: {pos_side} {pos_size} → {close_side}")
                
                result = self.place_order(
                    symbol=symbol,
                    side=close_side,
                    amount=pos_size,
                    order_type="market",
                    td_mode=pos.get('mgnMode', self.default_tdmode)
                )
                closed_orders.append(result)
        
        if not closed_orders:
            logger.info("ℹ️ 청산할 포지션이 없습니다")
            return {"code": "0", "msg": "청산할 포지션이 없습니다"}
        
        return {"code": "0", "data": closed_orders, "msg": f"{len(closed_orders)}개 포지션 청산 완료"}

    def place_order(self, symbol, side, amount, price=None, order_type="market", td_mode=None):
        """주문 실행"""
        logger.info(f"🎯 주문 시작: {side.upper()} {amount} {symbol}")
        
        # 심볼 정보 조회
        instrument_info = self.get_instrument_info(symbol)
        if not instrument_info:
            logger.error(f"❌ 주문 실패: {symbol} 심볼 정보 조회 실패")
            return {"code": "error", "msg": "심볼 정보 조회 실패"}
        
        lot_size = float(instrument_info['lotSz'])
        min_size = float(instrument_info['minSz'])
        
        # 수량 검증
        if amount < min_size:
            logger.error(f"❌ 주문 수량({amount})이 최소 수량({min_size}) 미만입니다")
            return {"code": "error", "msg": f"주문 수량은 {min_size} 이상이어야 합니다"}
        
        if amount % lot_size != 0:
            adjusted_amount = round(amount / lot_size) * lot_size
            logger.warning(f"⚠️ 수량({amount})이 lot size({lot_size})의 배수가 아님. 조정된 수량: {adjusted_amount}")
            amount = adjusted_amount
        
        method = "POST"
        path = "/api/v5/trade/order"
        if td_mode is None:
            td_mode = "cash" if self.default_market == "spot" else self.default_tdmode
        
        body = {
            "instId": symbol,
            "tdMode": td_mode,
            "side": side,
            "ordType": order_type,
            "sz": str(amount)
        }
        if price and order_type == "limit":
            body["px"] = str(price)
        
        body_str = json.dumps(body)
        headers = self.sign_request(method, path, body_str)
        logger.info(f"📤 주문 전송: 심볼={symbol}, 방향={side}, 수량={amount}, 타입={order_type}")
        
        try:
            response = requests.post(
                self.base_url + path,
                headers=headers,
                data=body_str,
                verify=False,
                timeout=10
            )
            result = response.json()
            
            if result.get('code') == '0':
                logger.info(f"✅ 주문 성공! {result}")
            else:
                logger.error(f"❌ 주문 실패: {result}")
            
            return result
        except Exception as e:
            logger.error(f"❌ 주문 실행 오류: {e}")
            return {"code": "error", "msg": str(e)}

def validate_webhook_token(token):
    """웹훅 토큰 검증"""
    expected_token = os.getenv('WEBHOOK_TOKEN', 'piona0413')
    is_valid = token == expected_token
    if not is_valid:
        logger.warning(f"🚫 잘못된 토큰: {token}")
    else:
        logger.info("🔐 토큰 검증 성공")
    return is_valid

def parse_tradingview_webhook(data):
    """TradingView 웹훅 데이터 파싱"""
    try:
        if isinstance(data, dict):
            webhook_data = data
        else:
            webhook_data = json.loads(data)
        
        required_fields = ['action', 'symbol']
        for field in required_fields:
            if field not in webhook_data:
                raise ValueError(f"필수 필드 누락: {field}")
        
        # 수량 검증 및 조정
        trader = OKXTrader()
        instrument_info = trader.get_instrument_info(webhook_data['symbol'])
        if instrument_info:
            lot_size = float(instrument_info['lotSz'])
            quantity = float(webhook_data.get('quantity', 0.001))
            if quantity % lot_size != 0:
                adjusted_quantity = round(quantity / lot_size) * lot_size
                logger.warning(f"⚠️ 웹훅 수량({quantity})이 lot size({lot_size})의 배수가 아님. 조정된 수량: {adjusted_quantity}")
                webhook_data['quantity'] = adjusted_quantity
        
        parsed = {
            'action': webhook_data['action'].lower(),
            'symbol': webhook_data['symbol'],
            'quantity': webhook_data.get('quantity', 0.001),
            'price': webhook_data.get('price'),
            'order_type': webhook_data.get('order_type', 'market'),
            'message': webhook_data.get('message', ''),
            'token': webhook_data.get('token', '')
        }
        
        logger.info(f"📨 웹훅 파싱 완료: {parsed['action']} {parsed['quantity']} {parsed['symbol']}")
        return parsed
        
    except Exception as e:
        logger.error(f"❌ 웹훅 데이터 파싱 오류: {e}")
        return None

@app.route('/', methods=['GET'])
def home():
    """홈페이지"""
    return jsonify({
        "message": "🚀 TradingView → OKX 자동거래 봇 실행 중!",
        "endpoints": {
            "webhook": "/webhook",
            "status": "/status", 
            "positions": "/positions",
            "balance": "/balance"
        },
        "timestamp": datetime.now().isoformat()
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    """TradingView 웹훅 엔드포인트"""
    try:
        logger.info("📨 웹훅 요청 수신!")
        
        # 편지를 열어보기
        letter = request.get_data(as_text=True)
        if not letter or letter.strip() == "":
            logger.warning("⚠️ 빈 편지 받음!")
            return jsonify({"status": "error", "message": "빈 편지"}), 400
        
        # 편지를 제대로 읽기
        webhook_data = json.loads(letter)
        logger.info(f"📨 받은 편지 내용: {webhook_data}")
        
        parsed_data = parse_tradingview_webhook(webhook_data)
        if not parsed_data:
            return jsonify({"status": "error", "message": "잘못된 편지 형식"}), 400
        
        # 토큰 확인
        if not validate_webhook_token(parsed_data['token']):
            return jsonify({"status": "error", "message": "토큰이 틀렸어요"}), 403
        
        # 거래 실행
        action = parsed_data['action']
        symbol = parsed_data['symbol']
        quantity = float(parsed_data['quantity'])
        price = parsed_data.get('price')
        order_type = parsed_data['order_type']
        
        logger.info(f"🎯 실행할 작업: {action.upper()} {quantity} {symbol}")
        
        trader = OKXTrader()
        
        if action in ['buy', 'sell']:
            result = trader.place_order(
                symbol=symbol,
                side=action,
                amount=quantity,
                price=price,
                order_type=order_type
            )
        elif action == 'close':
            result = trader.close_position(symbol, 'both')
        else:
            return jsonify({"status": "error", "message": f"알 수 없는 명령: {action}"}), 400
        
        if result['code'] == '0':
            logger.info(f"✅ 거래 성공! {result}")
            return jsonify({
                "status": "success",
                "message": f"{action.upper()} 주문 완료! 🎉",
                "data": result
            })
        else:
            logger.error(f"❌ 거래 실패: {result}")
            return jsonify({
                "status": "error",
                "message": f"거래 실패: {result.get('msg', '알 수 없는 오류')}"
            }), 500
            
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON 파싱 오류: {e}")
        return jsonify({"status": "error", "message": "JSON 형식이 잘못됨"}), 400
    except Exception as e:
        logger.error(f"❌ 웹훅 처리 오류: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """서버 상태 확인"""
    trader = OKXTrader()
    return jsonify({
        "status": "🟢 RUNNING",
        "timestamp": datetime.now().isoformat(),
        "market": trader.default_market,
        "trading_mode": trader.default_tdmode,
        "simulated": trader.simulated == '1',
        "message": "자동거래 봇이 정상 작동 중입니다! 🚀"
    })

@app.route('/positions', methods=['GET'])
def get_positions():
    """현재 포지션 조회"""
    try:
        trader = OKXTrader()
        symbol = request.args.get('symbol')  # ?symbol=BTC-USDT-SWAP 옵션
        positions = trader.get_positions(symbol)
        return jsonify(positions)
    except Exception as e:
        logger.error(f"❌ 포지션 조회 오류: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/balance', methods=['GET'])
def get_balance():
    """잔고 조회"""
    try:
        trader = OKXTrader()
        method = "GET"
        path = "/api/v5/account/balance"
        headers = trader.sign_request(method, path)
        response = requests.get(
            trader.base_url + path,
            headers=headers,
            verify=False,
            timeout=10
        )
        return jsonify(response.json())
    except Exception as e:
        logger.error(f"❌ 잔고 조회 오류: {e}")
        return jsonify({"error": str(e)}), 500

# Render용 헬스체크
@app.route('/health', methods=['GET'])
def health():
    """헬스체크 (Render 모니터링용)"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    # Render에서는 PORT 환경변수를 자동으로 할당해줌
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("🚀 TradingView → OKX 자동거래 시스템 시작!")
    print("=" * 60)
    print(f"🌐 포트: {port}")
    print(f"📊 시뮬레이션 모드: ON")
    print(f"🎯 웹훅 URL: https://your-app-name.onrender.com/webhook")
    print(f"📋 상태 확인: https://your-app-name.onrender.com/status")
    print(f"💰 잔고 확인: https://your-app-name.onrender.com/balance")
    print(f"📊 포지션 확인: https://your-app-name.onrender.com/positions")
    print("=" * 60)
    print("✅ 준비 완료! TradingView 신호를 기다리는 중...")
    print("=" * 60)
    
    # 웹서버 시작 - Render 배포용 설정
    app.run(host='0.0.0.0', port=port, debug=False)


