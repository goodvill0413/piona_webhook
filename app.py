# app.py
from flask import Flask, request, jsonify
from pybit.unified_trading import HTTP
from dotenv import load_dotenv
import os, time, logging

# --------------------------- init ---------------------------
load_dotenv()  # .env 있으면 우선 사용

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("piona-webhook")

app = Flask(__name__)

# ---------------------- config (env + fallback) ----------------------
# .env/환경변수 없으면 하드코피 값 사용. 배포 전엔 하드코피 제거 권장.
API_KEY    = (os.getenv("API_KEY")    or "pCCbKfm7qjeGYVVWVq").strip()
API_SECRET = (os.getenv("API_SECRET") or "A0AAWLqkaArA3f41g8hJ1pdWG2o7w0DqwlqQ").strip()
IS_TESTNET = (os.getenv("TESTNET", "true")).lower().strip() in ("1", "true", "yes")

client = None
trading_enabled = False

def _mask(s: str, n=8) -> str:
    return (s[:n] + "…") if s else ""

def _fmt_qty(q) -> str:
    try:
        qf = float(q)
    except Exception:
        qf = 0.001
    qf = max(round(qf, 3), 0.001)
    return f"{qf:.3f}"

# ---------------------- client init ----------------------
def get_trading_client():
    global client, trading_enabled
    if client is not None:
        return client

    if not API_KEY or not API_SECRET:
        log.error("API key/secret missing")
        return None

    log.info(f"Initializing Bybit client (testnet={IS_TESTNET})")
    log.info(f"API_KEY starts with: {_mask(API_KEY)}")

    try:
        # server time (string/number 모두 안전 파싱)
        tmp = HTTP(testnet=IS_TESTNET)
        st = tmp.get_server_time()
        r = st.get("result", {}) if isinstance(st, dict) else {}

        def _to_int_ms(val, scale=1):
            try:
                return int(float(val) * scale)
            except Exception:
                return 0

        if "timeNano" in r:
            server_ms = _to_int_ms(r.get("timeNano"), 1/1_000_000)  # ns->ms
        elif "timeSecond" in r:
            server_ms = _to_int_ms(r.get("timeSecond"), 1000)        # s->ms
        else:
            server_ms = 0

        local_ms = int(time.time() * 1000)
        if server_ms and abs(server_ms - local_ms) > 5000:
            log.warning(f"Time diff: {abs(server_ms - local_ms)}ms")

        c = HTTP(
            testnet=IS_TESTNET,
            api_key=API_KEY,
            api_secret=API_SECRET,
            recv_window=10_000,
        )
        test = c.get_server_time()
        log.info(f"API connection OK. serverTime(s)={test.get('result', {}).get('timeSecond', 'unknown')}")

        client = c
        trading_enabled = True
        log.info("Bybit client ready")
        return client

    except Exception as e:
        log.error(f"Client init failed: {e}")
        return None

@app.before_request
def _ensure_client():
    global client, trading_enabled
    if client is None:
        c = get_trading_client()
        trading_enabled = c is not None

# ---------------------- trading ops ----------------------
def execute_buy_order(symbol="BTCUSDT", qty=0.001):
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "client not available"}
    q = _fmt_qty(qty)
    log.info(f"BUY {symbol} {q}")
    try:
        r = c.place_order(
            category="linear",
            symbol=symbol,
            side="Buy",
            orderType="Market",
            qty=q,
        )
        if r.get("retCode") == 0:
            log.info(f"BUY success orderId={r.get('result', {}).get('orderId','?')}")
            return {"status": "success", "data": r}
        log.error(f"BUY failed code={r.get('retCode')} msg={r.get('retMsg')}")
        return {"status": "error", "data": r, "message": r.get("retMsg")}
    except Exception as e:
        log.error(f"BUY exception: {e}")
        return {"status": "error", "message": str(e)}

def execute_sell_order(symbol="BTCUSDT", qty=0.001):
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "client not available"}
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
            log.info(f"SELL success orderId={r.get('result', {}).get('orderId','?')}")
            return {"status": "success", "data": r}
        log.error(f"SELL failed code={r.get('retCode')} msg={r.get('retMsg')}")
        return {"status": "error", "data": r, "message": r.get("retMsg")}
    except Exception as e:
        log.error(f"SELL exception: {e}")
        return {"status": "error", "message": str(e)}

def close_positions(symbol="BTCUSDT"):
    c = get_trading_client()
    if not c:
        return {"status": "error", "message": "client not available"}
    try:
        pos = c.get_positions(category="linear", symbol=symbol)
        if pos.get("retCode") != 0:
            return {"status": "error", "message": pos.get("retMsg")}
        lst = pos.get("result", {}).get("list", []) or []
        if not lst:
            return {"status": "no_position", "message": f"No open position for {symbol}"}

        results = []
        for p in lst:
            size = float(p.get("size") or 0)
            if size <= 0: 
                continue
            side = p.get("side")
            close_side = "Sell" if side == "Buy" else "Buy"
            position_idx = p.get("positionIdx", 1)  # 1=oneway, 2=long, 3=short
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
        return {"status": "error", "message": str(e)}

# ---------------------- routes ----------------------
@app.route("/")
def index():
    return {
        "app": "piona-trading-bot",
        "status": "running",
        "trading_mode": "testnet" if IS_TESTNET else "live",
        "api_configured": bool(API_KEY and API_SECRET),
        "trading_ready": trading_enabled,
        "version": "1.2.0",
    }

@app.route("/health")
def health():
    return {
        "status": "healthy" if trading_enabled else "degraded",
        "testnet": IS_TESTNET,
        "trading_client": "ready" if trading_enabled else "not_initialized",
    }

@app.route("/debug")
def debug():
    return {
        "api_key_set": bool(API_KEY),
        "api_secret_set": bool(API_SECRET),
        "api_key_prefix": _mask(API_KEY),
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
        return c.get_wallet_balance(accountType="UNIFIED")
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/positions")
def positions():
    c = get_trading_client()
    if not c: 
        return {"status": "error", "message": "client not ready"}, 500
    try:
        symbol = request.args.get("symbol","BTCUSDT").upper().strip()
        return c.get_positions(category="linear", symbol=symbol)
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500

@app.route("/webhook", methods=["POST"])
def webhook():
    log.info("=== Webhook received ===")
    try:
        data = request.get_json(silent=True) or {}
        action = str(data.get("action","")).lower().strip()
        symbol = str(data.get("symbol","BTCUSDT")).upper().strip()
        qty = data.get("qty", 0.001)

        log.info(f"JSON: {data}")
        if action == "test":
            return jsonify({"status":"success","message":"test ok","trading_ready":trading_enabled}), 200

        if action in ("buy","long"):
            result = execute_buy_order(symbol, qty)
        elif action in ("sell","short"):
            result = execute_sell_order(symbol, qty)
        elif action in ("close","exit","stop"):
            result = close_positions(symbol)
        else:
            return jsonify({"status":"error","message":f"Unknown action: {action}","supported":["buy","long","sell","short","close","exit","stop","test"]}), 400

        ok = isinstance(result, dict) and result.get("status") == "success"
        resp = {
            "status": "success" if ok else "error",
            "action": action,
            "symbol": symbol,
            "qty": _fmt_qty(qty),
            "result": result,
            "timestamp": data.get("timestamp","not_provided"),
        }
        return (jsonify(resp), 200) if ok else (jsonify(resp), 500)
    except Exception as e:
        log.error(f"Webhook error: {e}")
        return jsonify({"status":"error","message":str(e)}), 500

# ---------------------- main ----------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    log.info(f"Starting on {port} (testnet={IS_TESTNET})  key={_mask(API_KEY)}")
    client = get_trading_client()
    log.info("Ready for webhooks")
    app.run(host="0.0.0.0", port=port)




