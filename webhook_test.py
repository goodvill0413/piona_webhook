import requests
import json

# 테스트용 웹훅 데이터 (가짜 TradingView 신호)
webhook_data = {
    "action": "buy",           # 매수 주문
    "symbol": "BTC-USDT-SWAP", # 비트코인 선물
    "quantity": 0.01,          # 0.01 BTC
    "order_type": "market",    # 시장가 주문
    "token": "test123",        # 보안 토큰 (.env 파일과 같게!)
    "message": "테스트 매수 신호"
}

print("🚀 웹훅 테스트 시작...")
print(f"테스트 데이터: {webhook_data}")

try:
    # localhost:5000/webhook으로 POST 요청 보내기
    response = requests.post(
        "http://localhost:5000/webhook",
        json=webhook_data,
        timeout=10
    )
    
    print(f"\n📨 응답 상태: {response.status_code}")
    print(f"📨 응답 내용: {response.text}")
    
    if response.status_code == 200:
        print("✅ 성공! 주문이 실행되었습니다!")
    else:
        print("❌ 실패! 뭔가 문제가 있어요.")
        
except Exception as e:
    print(f"❌ 에러 발생: {e}")
    print("💡 app.py가 실행 중인지 확인해주세요!")