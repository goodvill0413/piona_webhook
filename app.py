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
    """
    매수 시장가 주문을 실행합니다.
    - 지정가 주문의 시간차 문제를 해결하기 위해 시장가 주문을 사용합니다.
    """
    log.info(f"🚀 Placing MARKET BUY order: {qty} {symbol}")
    try:
        return client.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market", # 지정가(Limit) -> 시장가(Market)로 변경
            qty=str(qty)
            # 가격(price) 파라미터는 시장가 주문 시 필요 없으므로 제거
        )
    except Exception as e:
        log.error(f"❌ Failed to place buy order: {e}")
        return {"status": "error", "message": str(e)}

def place_sell_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> Dict[str, Any]:
    """
    매도 시장가 주문을 실행합니다.
    - 지정가 주문의 시간차 문제를 해결하기 위해 시장가 주문을 사용합니다.
    """
    log.info(f"🛑 Placing MARKET SELL order: {qty} {symbol}")
    try:
        return client.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market", # 지정가(Limit) -> 시장가(Market)로 변경
            qty=str(qty)
            # 가격(price) 파라미터는 시장가 주문 시 필요 없으므로 제거
        )
    except Exception as e:
        log.error(f"❌ Failed to place sell order: {e}")
        return {"status": "error", "message": str(e)}

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
        log.info(f"🛑 Closing {pos_side} position with MARKET order: {pos_size} {symbol}")
        
        return client.place_order(
            category="linear",
            symbol=symbol,
            side=close_side,
            orderType="Market",
            qty=str(pos_size),
            reduceOnly=True
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
        orderType="Market",
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
        }
    }

@app.get("/health")
def health():
    return {"status": "healthy", "testnet": IS_TESTNET}

@app.route("/webhook", methods=['POST'])
def webhook():
    """메인 웹훅 핸들러: 모든 TradingView 알림을 받아 처리합니다."""
    try:
        payload = None
        raw_data = None
        
        try:
            payload = request.get_json()
            if payload:
                log.info(f"📊 Webhook received (JSON): {payload}")
        except Exception:
            pass
        
        if not payload:
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
            action = str(payload.get("action", "unknown")).lower()
            symbol = str(payload.get("symbol", "BTCUSDT")).upper()
            qty = float(payload.get("qty", 0.001))
        elif raw_data:
            action = raw_data.lower()
            
        log.info(f"🎯 Processing action: '{action}'")
        
        response_data = {}
        
        # 액션별 처리
        # 'entry'는 하위 호환성을 위해 남겨두되, 명확한 'buy'/'long'을 우선 처리
        if action in ["buy", "long"]:
            response_data = place_buy_order(symbol, qty)
            
        elif action in ["sell", "short"]:
            response_data = place_sell_order(symbol, qty)
            
        elif action in ["close", "exit", "time_exit", "emergency_close", "stop"]:
            response_data = close_all_positions(symbol)
            
        # 하위 호환성을 위한 JSON 처리
        elif payload and action == "entry":
            response_data = place_new_order(payload)
            
        elif payload and action in ["time_exit", "emergency_close"]:
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
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
