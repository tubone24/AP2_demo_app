"""
v2/services/credential_provider/main.py

Credential Provider - FastAPIエントリーポイント
"""

import os
import sys
from pathlib import Path

# パス設定
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import logging
import uvicorn
from provider import CredentialProviderService

# OpenTelemetry統合
from common.telemetry import setup_telemetry, instrument_fastapi_app

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# OpenTelemetryセットアップ（Jaegerトレーシング）
service_name = os.getenv("OTEL_SERVICE_NAME", "credential_provider")
setup_telemetry(service_name)

# Credential Providerインスタンス作成
credential_provider = CredentialProviderService()
app = credential_provider.app

# FastAPI計装（AP2完全準拠：A2A/MCP通信の可視化）
instrument_fastapi_app(app)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=False,
        log_level="info"
    )
