"""
v2/services/shopping_agent/main.py

Shopping Agent - FastAPIエントリーポイント
"""

import logging
import uvicorn
from services.shopping_agent.agent import ShoppingAgent

# ロギング設定
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s in %(name)s: %(message)s'
)

# Shopping Agentインスタンス作成
shopping_agent = ShoppingAgent()
app = shopping_agent.app

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Docker環境ではreloadは無効
        log_level="info"
    )
