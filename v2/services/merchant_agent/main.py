"""
v2/services/merchant_agent/main.py

Merchant Agent - FastAPIエントリーポイント
"""

import logging
import uvicorn
from agent import MerchantAgent

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Merchant Agentインスタンス作成
merchant_agent = MerchantAgent()
app = merchant_agent.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )
