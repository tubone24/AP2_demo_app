"""
v2/services/merchant/main.py

Merchant - FastAPIエントリーポイント
"""

import os
import sys
from pathlib import Path
import logging
import uvicorn
from services.merchant.service import MerchantService

# OpenTelemetry統合
from common.telemetry import setup_telemetry, instrument_fastapi_app

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# OpenTelemetryセットアップ（Jaegerトレーシング）
service_name = os.getenv("OTEL_SERVICE_NAME", "merchant")
setup_telemetry(service_name)

# Merchantインスタンス作成
merchant = MerchantService()
app = merchant.app

# FastAPI計装（AP2完全準拠：A2A/MCP通信の可視化）
instrument_fastapi_app(app)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info"
    )
