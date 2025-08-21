import os
import json
import logging
from typing import Dict, Any

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

def place_new_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    """신규 시장가 주문을 실행합니다."""
    side = "Buy" if str(payload.get("side")).lower() in ("long", "buy") else "Sell"
    symbol = str(payload.get("symbol", "BTCUSDT")).upper()
    qty = float(payload.get("qty", 0.0))
    
    if qty <= 0:
        raise ValueError("Quantity must be positive for a new order.")
        
    log.info(f"🚀 Placing NEW order: {side} {qty} {symbol}")
    return client.place_order(
        category="linear", symbol=symbol, side=side, order_type="Market", qty=qty
    )

def close_position(payload: Dict[str, Any]) -> Dict[str, Any]:
    """기존 포지션을 시장가로 종료합니다."""
    symbol = str(payload.get("symbol", "BTCUSDT")).upper()
    # Bybit API에서 포지션 종료는 반대 사이드로 주문을 넣어야 합니다.
    # 현재 포지션 정보를 조회하여 수량과 사이드를 결정해야 합니다.
    # 이 부분은 실제 구현 시 매우 중요합니다. 아래는 예시 로직입니다.
    
    # 1. 현재 포지션 정보 조회
    positions = client.get_positions(category="linear", symbol=symbol)
    pos = positions.get("result", {}).get("list", [{}])[0]
    
    pos_size = float(pos.get("size", 0))
    pos_side = pos.get("side") # "Buy" or "Sell"
    
    if pos_size <= 0:
        log.warning(f"⚠️ No open position found for {symbol} to close.")
        return {"status": "no_position", "message": f"No open position for {symbol}."}

    # 2. 포지션 종료를 위한 반대 주문 생성
    close_side = "Sell" if pos_side == "Buy" else "Buy"
    log.info(f"🛑 Closing {pos_side} position for {symbol} with a {close_side} order of {pos_size}.")
    return client.place_order(
        category="linear", symbol=symbol, side=close_side, order_type="Market", qty=pos_size, reduce_only=True
    )

def modify_trailing_stop(payload: Dict[str, Any]) -> Dict[str, Any]:
    """기존 포지션의 트레일링 스탑을 수정합니다."""
    symbol = str(payload.get("symbol", "BTCUSDT")).upper()
    new_stop_price = float(payload.get("new_stop", 0.0))
    
    if new_stop_price <= 0:
        raise ValueError("Invalid new_stop price for trailing stop.")
        
    log.info(f"🔄 Modifying TRAILING STOP for {symbol} to new price: {new_stop_price}")
    # Bybit에서는 trailingStop을 설정할 수 있습니다.
    return client.set_trading_stop(
        category="linear", symbol=symbol, trailingStop=str(new_stop_price)
    )

# ---------------------------
# Routes
# ---------------------------

@app.get("/")
def index():
    return { "app": "piona-webhook-v2", "status": "ok", "env": "testnet" if IS_TESTNET else "live" }

@app.post("/webhook")
def webhook():
    """메인 웹훅 핸들러: 모든 트레이딩뷰 알림을 받아 처리합니다."""
    try:
        payload = request.get_json()
        if not payload or not isinstance(payload, dict):
            return {"status": "error", "message": "Invalid or empty JSON payload."}, 400
        
        log.info(f"🔔 Webhook received: {payload}")
        action = str(payload.get("action", "unknown")).lower()
        
        response_data = {}

        if action == "entry":
            response_data = place_new_order(payload)
        elif action in ["time_exit", "emergency_close"]:
            response_data = close_position(payload)
        elif action == "trail_update":
            response_data = modify_trailing_stop(payload)
        else:
            # Pine Script의 strategy.exit()에 의한 기본 익절/손절 처리 등
            # action이 명확하지 않은 경우를 처리합니다.
            log.warning(f"⚠️ Received unhandled or generic action: '{action}'. Payload: {payload}")
            # 필요에 따라 여기서도 포지션을 종료하는 로직을 추가할 수 있습니다.
            # response_data = close_position(payload)
            return {"status": "ok", "message": "Generic alert received and logged."}, 200

        log.info(f"✅ Action '{action}' processed successfully.")
        return jsonify({"status": "ok", "action": action, "response": response_data})

    except Exception as e:
        log.exception(f"❌ Error processing webhook: {e}")
        return {"status": "error", "message": str(e)}, 500

# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)