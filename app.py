import os
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/")
def index():
    return {"status": "ok", "message": "Server is running"}

@app.route("/health")
def health():
    return {"status": "healthy"}

@app.route("/webhook", methods=['POST'])
def webhook():
    print("=== Webhook received ===")
    print(f"Headers: {dict(request.headers)}")
    print(f"Data: {request.get_data()}")
    
    try:
        json_data = request.get_json()
        print(f"JSON: {json_data}")
        
        return jsonify({
            "status": "success", 
            "message": "Webhook received successfully",
            "data": json_data
        })
    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error", "message": str(e)}, 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
