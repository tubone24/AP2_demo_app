"""
v2/services/payment_processor/main.py

Payment Processor - FastAPIエントリーポイント
"""

import logging
import uvicorn
from processor import PaymentProcessorService

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Payment Processorインスタンス作成
payment_processor = PaymentProcessorService()
app = payment_processor.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=False,
        log_level="info"
    )
