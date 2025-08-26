import os
import json
import logging
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify

# ---------------------------
# Configuration & Setup
# ---------------------------

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET") 
IS_TESTNET = os.getenv("TESTNET", "true").lower() in ("1", "true", "yes")

# 로깅 설정
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("piona-webhook")

app = Flask(__name__)

# 전역 변수
client = None
trading_enabled = False

def get_trading_client():
    """거래 클라이언트를 가져옵니다 (지연 로딩)"""
    global client, trading_enabled
    
    if client is not None:
        return client
        
    # 하드코딩된 새 API 키 사용
    API_KEY_NEW = "s50OTiRy6693Rrfjfn"            
    API_SECRET_NEW = "ArlYHlzcr4cTV8Cd8xc8iAe57A3ZMvAe0C2J"
                    
    # 디버깅 정보 출력
    log.info("Initializing trading client...")
    log.info(f"API_KEY length: {len(API_KEY_NEW)}")
    log.info(f"API_SECRET length: {len(API_SECRET_NEW)}")
    log.info(f"TESTNET mode: {IS_TESTNET}")
    log.info("API_KEY starts with: " + API_KEY_NEW[:8] + "...")
    
    try:
        from pybit.unified_trading import HTTP
        client = HTTP(
            testnet=IS_TESTNET, 
            api_key=API_KEY_NEW, 
            api_secret=API_SECRET_NEW,
            recv_window=5000
        )
        
        # 간단한 API 호출로 연결 테스트
        log.info("Testing API connection...")
        test_result = client.get_server_time()
        log.info(f"API connection test successful: {test_result.get('result', {}).get('timeSecond', 'unknown')}")
        
        trading_enabled = True
        log.info(f"Trading client initialized successfully (testnet: {IS_TESTNET})")
        return client
        
    except Exception as e:
        log.error(f"Failed to initialize trading client: {e}")
        return None

# ---------------------------
# Trading Functions
# ---------------------------

def execute_buy_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> Dict[str, Any]:
    """매수 주문 실행"""
    client = get_trading_client()
    if not client:
        return {"status": "error", "message": "Trading client not available"}
    
    log.info(f"Executing BUY: {qty} {symbol}")
    try:
        result = client.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=str(qty),
            timeInForce="IOC"
        )
        
        # 결과 로깅
        if result.get("retCode") == 0:
            order_id = result.get("result", {}).get("orderId", "unknown")
            log.info(f"BUY order successful - Order ID: {order_id}")
        else:
            log.error(f"BUY order failed - Code: {result.get('retCode')}, Msg: {result.get('retMsg')}")
            
        return {"status": "success", "data": result}
        
    except Exception as e:
        log.error(f"BUY order exception: {e}")
        return {"status": "error", "message": str(e)}

def execute_sell_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> Dict[str, Any]:
    """매도 주문 실행"""
    client = get_trading_client()
    if not client:
        return {"status": "error", "message": "Trading client not available"}
    
    log.info(f"Executing SELL: {qty} {symbol}")
    try:
        result = client.place_order(
            category="linear",
            symbol=symbol,
            side="Sell", 
            orderType="Market",
            qty=str(qty),
            timeInForce="IOC"
        )
        
        # 결과 로깅
        if result.get("retCode") == 0:
            order_id = result.get("result", {}).get("orderId", "unknown")
            log.info(f"SELL order successful - Order ID: {order_id}")
        else:
            log.error(f"SELL order failed - Code: {result.get('retCode')}, Msg: {result.get('retMsg')}")
            
        return {"status": "success", "data": result}
        
    except Exception as e:
        log.error(f"SELL order exception: {e}")
        return {"status": "error", "message": str(e)}

def close_positions(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """포지션 종료"""
    client = get_trading_client()
    if not client:
        return {"status": "error", "message": "Trading client not available"}
    
    try:
        log.info(f"Checking positions for {symbol}")
        positions = client.get_positions(category="linear", symbol=symbol)
        
        if positions.get("retCode") != 0:
            log.error(f"Failed to get positions: {positions.get('retMsg')}")
            return {"status": "error", "message": positions.get('retMsg')}
            
        pos_list = positions.get("result", {}).get("list", [])
        
        if not pos_list:
            log.info(f"No positions found for {symbol}")
            return {"status": "no_position", "message": f"No positions for {symbol}"}
        
        pos = pos_list[0]
        size = float(pos.get("size", 0))
        side = pos.get("side")
        
        if size <= 0:
            log.info(f"No open position for {symbol}")
            return {"status": "no_position", "message": f"No open position for {symbol}"}

        close_side = "Sell" if side == "Buy" else "Buy"
        log.info(f"Closing {side} position: {size} {symbol}")
        
        result = client.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(size),
            reduceOnly=True,
            timeInForce="IOC"
        )
        
        # 결과 로깅
        if result.get("retCode") == 0:
            order_id = result.get("result", {}).get("orderId", "unknown")
            log.info(f"Close position successful - Order ID: {order_id}")
        else:
            log.error(f"Close position failed - Code: {result.get('retCode')}, Msg: {result.get('retMsg')}")
            
        return {"status": "success", "data": result}
        
    except Exception as e:
        log.error(f"Close position exception: {e}")
        return {"status": "error", "message": str(e)}

# ---------------------------
# Routes
# ---------------------------

@app.route("/")
def index():
    return {
        "app": "piona-trading-bot",
        "status": "running", 
        "trading_mode": "testnet" if IS_TESTNET else "live",
        "api_configured": True,
        "trading_ready": trading_enabled,
        "version": "1.0.0"
    }

@app.route("/health")
def health():
    return {
        "status": "healthy",
        "trading_client": "ready" if trading_enabled else "not_initialized",
        "testnet": IS_TESTNET
    }

@app.route("/debug")
def debug():
    """디버깅 정보 확인용"""
    return {
        "api_key_set": True,
        "api_secret_set": True,
        "testnet": IS_TESTNET,
        "trading_enabled": trading_enabled,
        "client_initialized": client is not None
    }

@app.route("/webhook", methods=['POST'])
def webhook():
    """웹훅 핸들러"""
    print("=== Webhook received ===")
    print(f"Headers: {dict(request.headers)}")
    print(f"Data: {request.get_data()}")
    
    try:
        data = request.get_json()
        print(f"JSON: {data}")
        
        if not data:
            log.warning("No JSON data received")
            return jsonify({"status": "error", "message": "No JSON data"}), 400
        
        action = data.get("action", "").lower().strip()
        symbol = data.get("symbol", "BTCUSDT").upper().strip()
        qty = float(data.get("qty", 0.001))
        
        log.info(f"Processing: {action} {symbol} {qty}")
        
        # 테스트 액션
        if action == "test":
            log.info("TEST action - no trading")
            return jsonify({
                "status": "success",
                "action": action,
                "message": "Test webhook processed successfully",
                "trading_available": True,
                "trading_ready": trading_enabled
            })
        
        # 거래 실행 (환경변수 체크 제거)
        result = {}
        if action in ["buy", "long"]:
            result = execute_buy_order(symbol, qty)
        elif action in ["sell", "short"]:
            result = execute_sell_order(symbol, qty)
        elif action in ["close", "exit", "stop"]:
            result = close_positions(symbol)
        else:
            log.warning(f"Unknown action: {action}")
            return jsonify({
                "status": "error", 
                "message": f"Unknown action: {action}",
                "supported_actions": ["buy", "long", "sell", "short", "close", "exit", "stop", "test"]
            }), 400
        
        return jsonify({
            "status": "success",
            "action": action,
            "symbol": symbol,
            "qty": qty,
            "result": result,
            "timestamp": data.get("timestamp", "not_provided")
        })
        
    except Exception as e:
        log.error(f"Webhook error: {e}")
        print(f"ERROR: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------------------------
# Startup
# ---------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"Starting Piona Trading Bot...")
    print(f"Server port: {port}")
    print(f"API configured: True")
    print(f"Trading mode: {'TESTNET' if IS_TESTNET else 'LIVE'}")
    print(f"Ready to receive webhooks!")
    
    app.run(host="0.0.0.0", port=port)


