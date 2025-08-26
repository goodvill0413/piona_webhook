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
        
    if not API_KEY or not API_SECRET:
        log.warning("API credentials not found")
        return None
    
    try:
        from pybit.unified_trading import HTTP
        client = HTTP(testnet=IS_TESTNET, api_key=API_KEY, api_secret=API_SECRET)
        trading_enabled = True
        log.info(f"Trading client initialized (testnet: {IS_TESTNET})")
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
            qty=str(qty)
        )
        log.info(f"BUY order successful: {result}")
        return {"status": "success", "data": result}
    except Exception as e:
        log.error(f"BUY order failed: {e}")
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
            qty=str(qty)
        )
        log.info(f"SELL order successful: {result}")
        return {"status": "success", "data": result}
    except Exception as e:
        log.error(f"SELL order failed: {e}")
        return {"status": "error", "message": str(e)}

def close_positions(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """포지션 종료"""
    client = get_trading_client()
    if not client:
        return {"status": "error", "message": "Trading client not available"}
    
    try:
        positions = client.get_positions(category="linear", symbol=symbol)
        pos_list = positions.get("result", {}).get("list", [])
        
        if not pos_list:
            return {"status": "no_position", "message": f"No positions for {symbol}"}
        
        pos = pos_list[0]
        size = float(pos.get("size", 0))
        side = pos.get("side")
        
        if size <= 0:
            return {"status": "no_position", "message": f"No open position for {symbol}"}

        close_side = "Sell" if side == "Buy" else "Buy"
        log.info(f"Closing {side} position: {size} {symbol}")
        
        result = client.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(size),
            reduceOnly=True
        )
        log.info(f"Close position successful: {result}")
        return {"status": "success", "data": result}
        
    except Exception as e:
        log.error(f"Close position failed: {e}")
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
        "api_configured": bool(API_KEY and API_SECRET),
        "trading_ready": trading_enabled
    }

@app.route("/health")
def health():
    return {
        "status": "healthy",
        "trading_client": "ready" if trading_enabled else "not_initialized"
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
            return jsonify({"status": "error", "message": "No JSON data"}), 400
        
        action = data.get("action", "").lower()
        symbol = data.get("symbol", "BTCUSDT").upper()
        qty = float(data.get("qty", 0.001))
        
        log.info(f"Processing: {action} {symbol} {qty}")
        
        # 테스트 액션
        if action == "test":
            log.info("TEST action - no trading")
            return jsonify({
                "status": "success",
                "action": action,
                "message": "Test webhook processed successfully",
                "trading_available": bool(API_KEY and API_SECRET)
            })
        
        # API 자격증명 확인
        if not API_KEY or not API_SECRET:
            log.warning("No API credentials - test mode only")
            return jsonify({
                "status": "success",
                "action": action,
                "message": "Webhook received but trading disabled (no API credentials)",
                "data": {"test_mode": True}
            })
        
        # 거래 실행
        result = {}
        if action in ["buy", "long"]:
            result = execute_buy_order(symbol, qty)
        elif action in ["sell", "short"]:
            result = execute_sell_order(symbol, qty)
        elif action in ["close", "exit"]:
            result = close_positions(symbol)
        else:
            log.warning(f"Unknown action: {action}")
            return jsonify({"status": "error", "message": f"Unknown action: {action}"}), 400
        
        return jsonify({
            "status": "success",
            "action": action,
            "symbol": symbol,
            "qty": qty,
            "result": result
        })
        
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------------------------
# Startup
# ---------------------------

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    print(f"Starting server on port {port}")
    print(f"API configured: {bool(API_KEY and API_SECRET)}")
    print(f"Trading mode: {'TESTNET' if IS_TESTNET else 'LIVE'}")
    
    app.run(host="0.0.0.0", port=port)
