"""
v2/services/credential_provider/main.py

Credential Provider - FastAPIエントリーポイント
"""

import logging
import uvicorn
from provider import CredentialProviderService

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Credential Providerインスタンス作成
credential_provider = CredentialProviderService()
app = credential_provider.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=False,
        log_level="info"
    )
