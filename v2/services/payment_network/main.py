"""
v2/services/payment_network/main.py

Payment Network Service - FastAPIエントリーポイント
"""

import logging
import uvicorn
from network import PaymentNetworkService

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Payment Network Serviceインスタンス作成
payment_network = PaymentNetworkService(network_name="DemoPaymentNetwork")
app = payment_network.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8005,
        reload=False,
        log_level="info"
    )
