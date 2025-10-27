"""
v2/services/payment_processor/main.py

Payment Processor - FastAPIエントリーポイント
"""

import os
import sys
from pathlib import Path

# パス設定
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import logging
import uvicorn
from processor import PaymentProcessorService

# OpenTelemetry統合
from common.telemetry import setup_telemetry, instrument_fastapi_app

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# OpenTelemetryセットアップ（Jaegerトレーシング）
service_name = os.getenv("OTEL_SERVICE_NAME", "payment_processor")
setup_telemetry(service_name)

# Payment Processorインスタンス作成
payment_processor = PaymentProcessorService()
app = payment_processor.app

# FastAPI計装（AP2完全準拠：A2A/MCP通信の可視化）
instrument_fastapi_app(app)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=False,
        log_level="info"
    )
