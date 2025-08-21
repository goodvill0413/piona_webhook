import os
import json
import logging
from typing import Tuple, Dict, Any

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
BASE_URL = os.getenv("BASE_URL", "https://piona.kr").rstrip("/")  # for docs

if not API_KEY or not API_SECRET:
    raise RuntimeError("API_KEY / API_SECRET not found. Please set them in environment variables or .env.")

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("piona-webhook")

# Bybit client
client = HTTP(testnet=IS_TESTNET, api_key=API_KEY, api_secret=API_SECRET)

app = Flask(__name__)

# ---------------------------
# Helpers
# ---------------------------
def get_json_from_request() -> Dict[str, Any]:
    """Robustly parse JSON from TradingView webhook which may send text/plain JSON."""
    data = request.get_json(silent=True)
    if data is not None:
        return data
    try:
        text = request.data.decode("utf-8").strip()
        return json.loads(text) if text else {}
    except Exception:
        return {}

def parse_payload(data: Any) -> Tuple[str, float, str]:
    """
    Accepts two common formats from TradingView/Pine:
      A) {"signal": "buy"|"sell", "quantity": 0.01, "symbol": "BTCUSDT"}
      B) {"action": "entry", "side": "long"|"short", "qty": 0.01, "symbol": "BTCUSDT"}
    Returns: (side, qty, symbol) where side is "Buy" or "Sell".
    Raises ValueError on invalid payload.
    """
    if not isinstance(data, dict):
        raise ValueError("Payload must be a JSON object.")

    symbol = str(data.get("symbol", "BTCUSDT")).upper().strip()
    if not symbol or not symbol.isalnum():
        raise ValueError("Invalid symbol.")

    # Format A
    if "signal" in data:
        sig = str(data.get("signal", "")).lower()
        qty = float(data.get("quantity", 0.01))
        if sig not in ("buy", "sell"):
            raise ValueError("Invalid 'signal' value; expected 'buy' or 'sell'.")
        side = "Buy" if sig == "buy" else "Sell"
        return side, qty, symbol

    # Format B
    if "action" in data or "side" in data or "qty" in data:
        action = str(data.get("action", "")).lower()
        side_raw = str(data.get("side", "")).lower()
        qty = float(data.get("qty", data.get("quantity", 0.01)))

        if action and action != "entry":
            raise ValueError("Unsupported action. Only 'entry' is allowed here.")
        if side_raw not in ("long", "short", "buy", "sell"):
            raise ValueError("Invalid 'side' value; expected long/short or buy/sell.")
        side = "Buy" if side_raw in ("long", "buy") else "Sell"
        return side, qty, symbol

    raise ValueError("Unsupported payload shape. Expected keys like 'signal' or 'action/side/qty'.")

def place_market_order(side: str, qty: float, symbol: str) -> Dict[str, Any]:
    """Places a linear USDT perpetual market order on Bybit."""
    if qty <= 0:
        raise ValueError("Quantity must be positive.")
    log.info("Placing order: %s %s %s", side, qty, symbol)
    resp = client.place_order(
        category="linear",
        symbol=symbol,
        side=side,
        order_type="Market",
        qty=qty,
        time_in_force="GoodTillCancel"
    )
    return resp

def extract_wallet_snapshot() -> Dict[str, Any]:
    """Returns a compact snapshot of wallet/equity."""
    resp = client.get_wallet_balance(accountType="UNIFIED")
    item = resp.get("result", {}).get("list", [{}])[0]
    coin_list = item.get("coin") or []
    coin_row = next((c for c in coin_list if c.get("coin") == "USDT"), coin_list[0] if coin_list else {})
    snapshot = {
        "equity": item.get("totalEquity"),
        "wallet_balance": item.get("totalWalletBalance"),
        "unrealized_pnl": item.get("totalPerpUPL"),
        "account_type": "testnet" if IS_TESTNET else "live",
        "coin": coin_row.get("coin", "USDT"),
        "coin_wallet_balance": coin_row.get("walletBalance"),
        "raw": resp  # remove if you don't want to expose raw
    }
    return snapshot

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
            "balance": f"{BASE_URL}/balance",
            "health": f"{BASE_URL}/health",
            "docs": f"{BASE_URL}/docs"
        }
    }

@app.get("/docs")
def docs():
    return {
        "message": "PIONA Webhook Bot endpoints",
        "base_url": BASE_URL,
        "endpoints": {
            "POST /webhook": f"{BASE_URL}/webhook",
            "GET  /balance": f"{BASE_URL}/balance",
            "GET  /health": f"{BASE_URL}/health"
        },
        "payload_examples": {
            "A_signal": {"signal": "buy", "quantity": 0.01, "symbol": "BTCUSDT"},
            "B_action": {"action": "entry", "side": "long", "qty": 0.01, "symbol": "BTCUSDT"}
        },
        "curl_example": f'curl -X POST {BASE_URL}/webhook -H "Content-Type: application/json" -d "{{\\"signal\\":\\"buy\\",\\"quantity\\":0.01,\\"symbol\\":\\"BTCUSDT\\"}}"'
    }

@app.get("/health")
def health():
    try:
        client.get_wallet_balance(accountType="UNIFIED")
        return {"status": "ok", "env": "testnet" if IS_TESTNET else "live"}
    except Exception as e:
        log.exception("Health check failed: %s", e)
        return {"status": "error", "message": str(e)}, 500

@app.get("/balance")
def balance():
    try:
        snapshot = extract_wallet_snapshot()
        return jsonify(snapshot)
    except Exception as e:
        log.exception("Balance failed: %s", e)
        return {"error": str(e)}, 500

@app.post("/webhook")
def webhook():
    payload = get_json_from_request()
    log.info("🔔 Webhook received: %s", payload)

    if not payload:
        return {"error": "Empty or invalid JSON payload."}, 400

    try:
        side, qty, symbol = parse_payload(payload)
        order_resp = place_market_order(side, qty, symbol)
        log.info("✅ Order placed: %s", order_resp)

        try:
            snapshot = extract_wallet_snapshot()
        except Exception:
            snapshot = {}

        return jsonify({"status": "ok", "order": order_resp, "balance": snapshot})
    except Exception as e:
        log.exception("Order failed: %s", e)
        return {"status": "error", "message": str(e)}, 500

# ---------------------------
# Entrypoint
# ---------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
