# app.py
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
import os
import time
import logging

# ---------------------------
# Logging
# ---------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("piona-webhook")

# ---------------------------
# Flask
# ---------------------------
app = Flask(__name__)

# ---------------------------
# Env
# ---------------------------
API_KEY = os.getenv("API_KEY")
API_SECRET = os.getenv("API_SECRET")
IS_TESTNET = os.getenv("TESTNET", "true").lower() in ("1", "true", "yes")

# ---------------------------
# Globals
# ---------------------------
client = None
trading_enabled = False


# ---------------------------
# Utils
# ---------------------------
def _fmt_qty(q) -> str:
    """Qty formatted to 0.001 step (safe default for BTCUSDT)."""
    try:
        qf = float(q)
    except Exception:
        qf = 0.001
    qf = max(round(qf, 3), 0.001)
    return f"{qf:.3f}"


def get_trading_client():
    """Lazy-init Bybit client."""
    global client, trading_enabled

    if client is not None:
        return client

    if not API_KEY or not API_SECRET:
        log.error("API key/secret not set in environment variables")
        return None

    log.info("Initializing trading client...")
    log.info(f"TESTNET: {IS_TESTNET}")
    log.info(f"API_KEY starts with: {API_KEY[:8]}...")

    try:
        # Basic time sanity check (no auth)
        tmp = HTTP(testnet=IS_TESTNET)
        st = tmp.get_server_time()
        server_ms = int(st.get("result", {}).get("timeNano", 0) / 1_000_000)
        local_ms = int(time.time() * 1000)
        if server_ms and abs(server_ms - local_ms) > 5000:
            log.warning(f"Time difference with server: {abs(server_ms - local_ms)}ms")

        # Authenticated session
        c = HTTP(
            testnet=IS_TESTNET,
            api_key=API_KEY,
            api_secret=API_SECRET,
            recv_window=10_000,
        )

        # Connection test (auth not strictly required, but ensures headers ok)
        test = c.get_server_time()
        log.info(f"API connection OK. server time (s): {test.get('result', {}).get('timeSecond', 'unknown')}")

        client = c
        trading_enabled = True
        log.info(f"Trading client ready. (testnet={IS_TESTNET})")
        return client

    except Exception as e:
        log.error(f"Client init failed: {e}")
        return None


@app.before_request
def _ensure_client():
    """Make sure client exists before any request handling."""
    global client, trading_enabled
    if client is None:
        c = get_trading_client()
        trading_enabled = c is not None


# ---------------------------
# Trading ops
# ---------------------------
def execute_buy_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> dict:
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "Trading client not available"}

    q = _fmt_qty(qty)
    log.info(f"BUY {symbol} {q}")
    try:
        r = c.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=q,  # Market 주문은 timeInForce 불필요
        )
        if r.get("retCode") == 0:
            oid = r.get("result", {}).get("orderId", "unknown")
            log.info(f"BUY success - orderId={oid}")
            return {"status": "success", "data": r}
        else:
            log.error(f"BUY failed - code={r.get('retCode')} msg={r.get('retMsg')}")
            return {"status": "error", "data": r, "message": r.get("retMsg")}
    except Exception as e:
        log.error(f"BUY exception: {e}")
        return {"status": "error", "message": str(e)}


def execute_sell_order(symbol: str = "BTCUSDT", qty: float = 0.001) -> dict:
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "Trading client not available"}

    q = _fmt_qty(qty)
    log.info(f"SELL {symbol} {q}")
    try:
        r = c.place_order(
            category="linear",
            symbol=symbol,
            side="Sell",
            orderType="Market",
            qty=q,
        )
        if r.get("retCode") == 0:
            oid = r.get("result", {}).get("orderId", "unknown")
            log.info(f"SELL success - orderId={oid}")
            return {"status": "success", "data": r}
        else:
            log.error(f"SELL failed - code={r.get('retCode')} msg={r.get('retMsg')}")
            return {"status": "error", "data": r, "message": r.get("retMsg")}
    except Exception as e:
        log.error(f"SELL exception: {e}")
        return {"status": "error", "message": str(e)}


def close_positions(symbol: str = "BTCUSDT") -> dict:
    """Close all open positions (hedge or one-way)."""
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "Trading client not available"}

    try:
        log.info(f"Closing positions for {symbol}")
        pos = c.get_positions(category="linear", symbol=symbol)
        if pos.get("retCode") != 0:
            msg = pos.get("retMsg")
            log.error(f"Get positions failed: {msg}")
            return {"status": "error", "message": msg}

        lst = pos.get("result", {}).get("list", []) or []
        if not lst:
            log.info("No open positions")
            return {"status": "no_position", "message": f"No open position for {symbol}"}

        results = []
        for p in lst:
            size = float(p.get("size") or 0)
            if size <= 0:
                continue

            side = p.get("side")  # "Buy" or "Sell"
            close_side = "Sell" if side == "Buy" else "Buy"
            position_idx = p.get("positionIdx", 1)  # 1=one-way, 2=long, 3=short

            log.info(f"Close {side} {symbol} size={size} positionIdx={position_idx}")
            r = c.place_order(
                category="linear",
                symbol=symbol,
                side=close_side,
                orderType="Market",
                qty=_fmt_qty(size),
                reduceOnly=True,
                positionIdx=position_idx,
            )
            results.append(r)

        if not results:
            return {"status": "no_position", "message": f"No open position for {symbol}"}
        return {"status": "success", "data": results}

    except Exception as e:
        log.error(f"Close exception: {e}")
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
        "trading_ready": trading_enabled,
        "version": "1.1.0",
    }


@app.route("/health")
def health():
    return {
        "status": "healthy" if trading_enabled else "degraded",
        "trading_client": "ready" if trading_enabled else "not_initialized",
        "testnet": IS_TESTNET,
    }


@app.route("/debug")
def debug():
    return {
        "api_key_set": bool(API_KEY),
        "api_secret_set": bool(API_SECRET),
        "testnet": IS_TESTNET,
        "trading_enabled": trading_enabled,
        "client_initialized": client is not None,
    }


@app.route("/balance")
def balance():
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "client not ready"}, 500
    try:
        # Unified account is default on Bybit now
        return c.get_wallet_balance(accountType="UNIFIED")
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/positions")
def positions():
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "client not ready"}, 500
    try:
        symbol = request.args.get("symbol", "BTCUSDT").upper().strip()
        return c.get_positions(category="linear", symbol=symbol)
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500


@app.route("/webhook", methods=["POST"])
def webhook():
    log.info("=== Webhook received ===")
    try:
        data = request.get_json(silent=True) or {}
        action = str(data.get("action", "")).lower().strip()
        symbol = str(data.get("symbol", "BTCUSDT")).upper().strip()
        qty = data.get("qty", 0.001)

        log.info(f"Headers: {dict(request.headers)}")
        log.info(f"JSON: {data}")
        log.info(f"Process: action={action} symbol={symbol} qty={qty}")

        if action == "test":
            return jsonify({
                "status": "success",
                "message": "test ok",
                "trading_ready": trading_enabled
            }), 200

        if action in ("buy", "long"):
            result = execute_buy_order(symbol, qty)
        elif action in ("sell", "short"):
            result = execute_sell_order(symbol, qty)
        elif action in ("close", "exit", "stop"):
            result = close_positions(symbol)
        else:
            return jsonify({
                "status": "error",
                "message": f"Unknown action: {action}",
                "supported": ["buy","long","sell","short","close","exit","stop","test"]
            }), 400

        ok = isinstance(result, dict) and result.get("status") == "success"
        resp = {
            "status": "success" if ok else "error",
            "action": action,
            "symbol": symbol,
            "qty": _fmt_qty(qty),
            "result": result,
            "timestamp": data.get("timestamp", "not_provided"),
        }
        return (jsonify(resp), 200) if ok else (jsonify(resp), 500)

    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


# ---------------------------
# Main
# ---------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    log.info("Starting Piona Trading Bot...")
    log.info(f"Server port: {port}")
    log.info(f"API configured: {bool(API_KEY and API_SECRET)}")
    log.info(f"Trading mode: {'TESTNET' if IS_TESTNET else 'LIVE'}")
    client = get_trading_client()
    log.info("Ready to receive webhooks!")
    app.run(host="0.0.0.0", port=port)



