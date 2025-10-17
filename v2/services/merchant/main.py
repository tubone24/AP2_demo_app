"""
v2/services/merchant/main.py

Merchant - FastAPIエントリーポイント
"""

import logging
import uvicorn
from service import MerchantService

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Merchantインスタンス作成
merchant = MerchantService()
app = merchant.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=False,
        log_level="info"
    )
