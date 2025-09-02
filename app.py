import os
import json
import time
import hmac
import base64
import hashlib
import requests
import random
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

# 무료 프록시 리스트 (주기적으로 업데이트 필요)
FREE_PROXIES = [
    "103.152.112.234:80",
    "185.162.231.106:80", 
    "103.145.45.6:55443",
    "194.233.73.104:443",
    "103.149.162.195:80",
    "47.74.152.29:8888"
]

def get_working_proxy():
    """작동하는 프록시를 찾아 반환"""
    proxies_to_try = random.sample(FREE_PROXIES, min(3, len(FREE_PROXIES)))
    
    for proxy in proxies_to_try:
        try:
            proxies = {
                'http': f'http://{proxy}',
                'https': f'http://{proxy}'
            }
            # 빠른 테스트
            response = requests.get('http://httpbin.org/ip', proxies=proxies, timeout=5)
            if response.status_code == 200:
                logger.info(f"✅ 작동하는 프록시 발견: {proxy}")
                return proxies
        except:
            continue
    
    logger.warning("⚠️ 작동하는 프록시를 찾지 못함. 직접 연결 시도")
    return None

def make_request_with_proxy(method, url, **kwargs):
    """프록시를 사용해서 요청을 보내는 함수"""
    # 먼저 프록시로 시도
    proxy = get_working_proxy()
    if proxy:
        try:
            kwargs['proxies'] = proxy
            kwargs['timeout'] = kwargs.get('timeout', 15)
            
            if method.upper() == 'GET':
                response = requests.get(url, **kwargs)
            else:
                response = requests.post(url, **kwargs)
            
            logger.info(f"✅ 프록시로 요청 성공: {response.status_code}")
            return response
        except Exception as e:
            logger.warning(f"⚠️ 프록시 요청 실패: {e}")
    
    # 프록시 실패시 직접 연결
    try:
        kwargs.pop('proxies', None)  # 프록시 설정 제거
        kwargs['timeout'] = kwargs.get('timeout', 10)
        
        # User-Agent 추가로 봇 탐지 회피
        if 'headers' not in kwargs:
            kwargs['headers'] = {}
        kwargs['headers'].update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # 랜덤 지연 추가
        time.sleep(random.uniform(1, 3))
        
        if method.upper() == 'GET':
            response = requests.get(url, **kwargs)
        else:
            response = requests.post(url, **kwargs)
        
        logger.info(f"✅ 직접 연결로 요청 성공: {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"❌ 직접 연결도 실패: {e}")
        raise

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
            response = make_request_with_proxy(
                'GET',
                f"{self.base_url}/api/v5/public/instruments?instType=SWAP&instId={symbol}",
                verify=False
            )
            
            # 디버그: 실제 응답 확인
            logger.info(f"OKX API 응답 코드: {response.status_code}")
            logger.info(f"OKX API 응답 내용: {response.text[:300]}")
            
            if response.text.strip() == "":
                logger.warning(f"⚠️ 빈 응답 받음: {symbol}. 기본 규칙 사용!")
                return {'minSz': '0.001', 'lotSz': '0.001'}
            
            data = response.json()
            if data['code'] == '0' and data.get('data'):
                logger.info(f"✅ 심볼 정보 조회 성공: {symbol}")
                return data['data'][0]
            
            logger.warning(f"⚠️ 조회 실패로 기본 규칙 사용: {symbol}")
            return {'minSz': '0.001', 'lotSz': '0.001'}
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ JSON 파싱 오류: {e}")
            return {'minSz': '0.001', 'lotSz': '0.001'}
        except Exception as e:
            logger.error(f"❌ 심볼 정보 조회 오류: {e}")
            return {'minSz': '0.001', 'lotSz': '0.001'}

    def get_ticker(self, symbol):
        """현재가 조회"""
        try:
            response = make_request_with_proxy(
                'GET',
                f"{self.base_url}/api/v5/market/ticker?instId={symbol}",
                verify=False
            )
            data = response.json()
            if data['code'] == '0' and data.get('data'):
                price = float(data['data'][0]['last'])
                logger.info(f"💰 {symbol} 현재가: {price}")
                return price
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
            response = make_request_with_proxy(
                'GET',
                self.base_url + path,
                headers=headers,
                verify=False
            )
            result = response.json()
            logger.info(f"📊 포지션 조회 완료")
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
        
        return {"code": "0", "data": closed_orders}

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
            logger.error(f"❌ 주문 수량({amount})이 최소 수량({min_size}) 미만")
            return {"code": "error", "msg": f"주문 수량은 {min_size} 이상이어야 합니다"}
        
        if amount % lot_size != 0:
            adjusted_amount = round(amount / lot_size) * lot_size
            logger.warning(f"⚠️ 수량 조정: {amount} → {adjusted_amount}")
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
        logger.info(f"📤 주문 전송: {side} {amount} {symbol}")
        
        try:
            response = make_request_with_proxy(
                'POST',
                self.base_url + path,
                headers=headers,
                data=body_str,
                verify=False
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
    return token == expected_token

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
        
        return {
            'action': webhook_data['action'].lower(),
            'symbol': webhook_data['symbol'],
            'quantity': float(webhook_data.get('quantity', 0.001)),
            'price': webhook_data.get('price'),
            'order_type': webhook_data.get('order_type', 'market'),
            'message': webhook_data.get('message', ''),
            'token': webhook_data.get('token', '')
        }
        
    except Exception as e:
        logger.error(f"❌ 웹훅 파싱 오류: {e}")
        return None

@app.route('/', methods=['GET'])
def home():
    """홈페이지"""
    return jsonify({
        "message": "🚀 TradingView → OKX 자동거래 봇 (프록시 적용)",
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
        
        letter = request.get_data(as_text=True)
        if not letter or letter.strip() == "":
            return jsonify({"status": "error", "message": "빈 요청"}), 400
        
        webhook_data = json.loads(letter)
        logger.info(f"📨 웹훅 데이터: {webhook_data}")
        
        parsed_data = parse_tradingview_webhook(webhook_data)
        if not parsed_data:
            return jsonify({"status": "error", "message": "잘못된 데이터"}), 400
        
        if not validate_webhook_token(parsed_data['token']):
            return jsonify({"status": "error", "message": "토큰 오류"}), 403
        
        action = parsed_data['action']
        symbol = parsed_data['symbol']
        quantity = parsed_data['quantity']
        price = parsed_data.get('price')
        order_type = parsed_data['order_type']
        
        logger.info(f"🎯 거래 실행: {action.upper()} {quantity} {symbol}")
        
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
            return jsonify({"status": "error", "message": f"알 수 없는 액션: {action}"}), 400
        
        if result['code'] == '0':
            logger.info(f"✅ 거래 성공!")
            return jsonify({
                "status": "success",
                "message": f"{action.upper()} 완료!",
                "data": result
            })
        else:
            return jsonify({
                "status": "error",
                "message": f"거래 실패: {result.get('msg', '오류')}"
            }), 500
            
    except Exception as e:
        logger.error(f"❌ 웹훅 처리 오류: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    """서버 상태 확인"""
    return jsonify({
        "status": "🟢 RUNNING (프록시 적용)",
        "timestamp": datetime.now().isoformat(),
        "message": "프록시 기능이 적용된 자동거래 봇"
    })

@app.route('/positions', methods=['GET'])
def get_positions():
    """포지션 조회"""
    try:
        trader = OKXTrader()
        symbol = request.args.get('symbol')
        positions = trader.get_positions(symbol)
        return jsonify(positions)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/balance', methods=['GET'])
def get_balance():
    """잔고 조회"""
    try:
        trader = OKXTrader()
        method = "GET"
        path = "/api/v5/account/balance"
        headers = trader.sign_request(method, path)
        response = make_request_with_proxy(
            'GET',
            trader.base_url + path,
            headers=headers,
            verify=False
        )
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """헬스체크"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    
    print("=" * 60)
    print("🚀 프록시 적용된 자동거래 시스템 시작!")
    print("=" * 60)
    print(f"🌐 포트: {port}")
    print(f"🛡️ Cloudflare 우회: 프록시 + 헤더 변조")
    print("=" * 60)
    
    app.run(host='0.0.0.0', port=port, debug=False)



