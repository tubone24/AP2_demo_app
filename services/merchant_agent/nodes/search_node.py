"""
v2/services/merchant_agent/nodes/search_node.py

商品検索ノード（MCP経由）
"""

import os
from typing import TYPE_CHECKING

from common.logger import get_logger

if TYPE_CHECKING:
    from services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent, MerchantAgentState

logger = get_logger(__name__, service_name='langgraph_merchant')

# Langfuseトレーシング設定
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
langfuse_client = None

if LANGFUSE_ENABLED:
    try:
        from langfuse import Langfuse

        langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
    except Exception as e:
        logger.warning(f"[Langfuse] Failed to initialize in search_node: {e}")
        LANGFUSE_ENABLED = False


async def search_products(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
    """データベースから商品検索（MCP経由）

    AP2準拠のIntentMandate構造を使用:
    - skus: 特定のSKUリスト（オプション）
    - merchants: 許可されたMerchantリスト（オプション）
    - natural_language_description: 検索に使用
    """
    preferences = state["user_preferences"]

    # キーワード抽出（AP2準拠）
    search_keywords = preferences.get("search_keywords", [])

    # Langfuseトレーシング: LangChain Tool経由で呼び出すことで、
    # CallbackHandlerが自動的に「tool」observation typeとして記録
    try:
        # LangChain Tool経由で商品検索（Langfuse observation type用）
        result = await agent.call_mcp_tool_as_langchain("search_products", {
            "keywords": search_keywords,
            "limit": 20
        })

        products = result.get("products", [])
        state["available_products"] = products
        logger.info(f"[search_products] MCP returned {len(products)} products")

    except Exception as e:
        logger.error(f"[search_products] MCP error: {e}")
        state["available_products"] = []

    return state
