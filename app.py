import os
import json
import logging
from typing import Dict, Any, Union

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP

# ---------------------------
# Configuration & Setup
# ---------------------------
load_dotenv()

API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
IS_TESTNET = os.getenv("TESTNET", "true").lower() in ("1", "true", "yes")
BASE_URL = os.getenv("BASE_URL", "https://piona.kr").rstrip("/")

if not API_KEY or not API_SECRET:
    raise RuntimeError("API_KEY / API_SECRET not found. Please set them in environment variables or .env.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("piona-webhook")

client = HTTP(testnet=IS_TESTNET, api_key=API_KEY, api_secret=API_SECRET)
app = Flask(__name__)

# ---------------------------
# Trading Logic Functions
# ---------------------------

def place_buy_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> Dict[str, Any]:
    """매수 주문을 실행합니다."""
    log.info(f"🚀 Placing BUY order: {qty} {symbol}")
    
    # 현재가 조회
    try:
        ticker = client.get_tickers(category="linear", symbol=symbol)
        current_price = float(ticker["result"]["list"][0]["lastPrice"])
        log.info(f"Current price: {current_price}")
        
        return client.place_order(
            category="linear", 
            symbol=symbol, 
            side="Buy", 
            orderType="Limit",
            qty=str(qty),
            price=str(current_price)
        )
    except Exception as e:
        log.error(f"Failed to get current price, falling back to Market order: {e}")
        return client.place_order(
            category="linear", 
            symbol=symbol, 
            side="Buy", 
            orderType="Market",
            qty=str(qty)
        )

def place_sell_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> Dict[str, Any]:
    """매도 주문을 실행합니다."""
    log.info(f"🛑 Placing SELL order: {qty} {symbol}")
    
    # 현재가 조회
    try:
        ticker = client.get_tickers(category="linear", symbol=symbol)
        current_price = float(ticker["result"]["list"][0]["lastPrice"])
        log.info(f"Current price: {current_price}")
        
        return client.place_order(
            category="linear", 
            symbol=symbol, 
            side="Sell", 
            orderType="Limit",
            qty=str(qty),
            price=str(current_price)
        )
    except Exception as e:
        log.error(f"Failed to get current price, falling back to Market order: {e}")
        return client.place_order(
            category="linear", 
            symbol=symbol, 
            side="Sell", 
            orderType="Market",
            qty=str(qty)
        )

def close_all_positions(symbol: str = "BTCUSDT") -> Dict[str, Any]:
    """모든 포지션을 종료합니다."""
    try:
        positions = client.get_positions(category="linear", symbol=symbol)
        pos_list = positions.get("result", {}).get("list", [])
        
        if not pos_list:
            log.warning(f"⚠️ No positions found for {symbol}")
            return {"status": "no_position", "message": f"No positions for {symbol}"}
        
        pos = pos_list[0]
        pos_size = float(pos.get("size", 0))
        pos_side = pos.get("side")  # "Buy" or "Sell"
        
        if pos_size <= 0:
            log.warning(f"⚠️ No open position found for {symbol}")
            return {"status": "no_position", "message": f"No open position for {symbol}"}

        # 반대 사이드로 포지션 종료
        close_side = "Sell" if pos_side == "Buy" else "Buy"
        log.info(f"🛑 Closing {pos_side} position: {pos_size} {symbol}")
        
        return client.place_order(
            category="linear", 
            symbol=symbol, 
            side=close_side, 
            orderType="Market",  # 수정: order_type -> orderType
            qty=str(pos_size), 
            reduceOnly=True  # 수정: reduce_only -> reduceOnly
        )
        
    except Exception as e:
        log.error(f"Error closing position: {e}")
        return {"status": "error", "message": str(e)}

def place_new_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    """기존 복합 주문 로직 (하위 호환성)"""
    side = "Buy" if str(payload.get("side")).lower() in ("long", "buy") else "Sell"
    symbol = str(payload.get("symbol", "BTCUSDT")).upper()
    qty = float(payload.get("qty", 0.001))
    
    if qty <= 0:
        qty = 0.001  # 기본값
        
    log.info(f"🚀 Placing NEW order: {side} {qty} {symbol}")
    return client.place_order(
        category="linear", 
        symbol=symbol, 
        side=side, 
        orderType="Market",  # 수정: order_type -> orderType
        qty=str(qty)
    )

def close_position(payload: Dict[str, Any]) -> Dict[str, Any]:
    """기존 포지션 종료 로직 (하위 호환성)"""
    symbol = str(payload.get("symbol", "BTCUSDT")).upper()
    return close_all_positions(symbol)

# ---------------------------
# Routes
# ---------------------------

@app.get("/")
def index():
    return { 
        "app": "piona-webhook", 
        "status": "ok", 
        "env": "testnet" if IS_TESTNET else "live",
        "endpoints": {
            "webhook": f"{BASE_URL}/webhook",
            "health": f"{BASE_URL}/health",
            "balance": f"{BASE_URL}/balance",
            "docs": f"{BASE_URL}/docs"
        }
    }

@app.get("/health")
def health():
    return {"status": "healthy", "testnet": IS_TESTNET}

@app.route("/webhook", methods=['POST'])
def webhook():
    """메인 웹훅 핸들러: 모든 TradingView 알림을 받아 처리합니다."""
    try:
        # JSON과 텍스트 데이터 모두 처리
        payload = None
        raw_data = None
        
        try:
            # JSON 데이터 시도
            payload = request.get_json()
            if payload:
                log.info(f"📊 Webhook received (JSON): {payload}")
        except:
            pass
        
        if not payload:
            # 텍스트 데이터 처리
            raw_data = request.get_data(as_text=True).strip()
            log.info(f"📊 Webhook received (TEXT): '{raw_data}'")
            
            if not raw_data:
                log.warning("⚠️ Empty webhook data received")
                return {"status": "error", "message": "Empty data received"}, 400
        
        # 데이터 파싱 및 처리
        action = None
        symbol = "BTCUSDT"
        qty = 0.001
        
        if payload and isinstance(payload, dict):
            # JSON 형식 처리
            action = str(payload.get("action", "unknown")).lower()
            symbol = str(payload.get("symbol", "BTCUSDT")).upper()
            qty = float(payload.get("qty", 0.001))
        elif raw_data:
            # 텍스트 형식 처리
            action = raw_data.lower()
            
        log.info(f"🎯 Processing action: '{action}'")
        
        response_data = {}
        
        # 액션별 처리
        if action in ["buy", "long", "entry"]:
            response_data = place_buy_order(symbol, qty)
            
        elif action in ["sell", "short", "exit", "close"]:
            response_data = place_sell_order(symbol, qty)
            
        elif action in ["time_exit", "emergency_close", "stop"]:
            response_data = close_all_positions(symbol)
            
        elif payload and action == "entry":
            # 기존 복합 JSON 처리
            response_data = place_new_order(payload)
            
        elif payload and action in ["time_exit", "emergency_close"]:
            # 기존 복합 JSON 처리
            response_data = close_position(payload)
            
        else:
            log.warning(f"⚠️ Unhandled action: '{action}'. Data: {payload or raw_data}")
            return {"status": "ok", "message": f"Action '{action}' logged but not processed"}, 200

        log.info(f"✅ Action '{action}' processed successfully")
        return jsonify({
            "status": "success", 
            "action": action, 
            "symbol": symbol,
            "response": response_data
        })

    except Exception as e:
        log.exception(f"❌ Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}, 500

# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
