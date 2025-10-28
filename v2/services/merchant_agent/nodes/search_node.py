"""
v2/services/merchant_agent/nodes/search_node.py

商品検索ノード（MCP経由）
"""

import os
from typing import TYPE_CHECKING

from v2.common.logger import get_logger

if TYPE_CHECKING:
    from v2.services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent, MerchantAgentState

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

    # Langfuseトレーシング（MCPツール呼び出し）
    trace_id = state.get("session_id", "unknown")
    span = None  # スパン初期化

    try:
        # Langfuseスパン開始（可観測性向上）
        if LANGFUSE_ENABLED and langfuse_client:
            span = langfuse_client.start_span(
                name="mcp_search_products",
                input={"keywords": search_keywords, "limit": 20},
                metadata={"tool": "search_products", "mcp_server": "merchant_agent_mcp", "session_id": trace_id}
            )

        # MCP経由で商品検索
        result = await agent.mcp_client.call_tool("search_products", {
            "keywords": search_keywords,
            "limit": 20
        })

        products = result.get("products", [])
        state["available_products"] = products
        logger.info(f"[search_products] MCP returned {len(products)} products")

        # Langfuseスパン終了（成功時）
        if span:
            span.update(output={"products_count": len(products), "products": products[:5]})  # 最初の5件のみ記録
            span.end()

    except Exception as e:
        logger.error(f"[search_products] MCP error: {e}")
        state["available_products"] = []

        # Langfuseスパン終了（エラー時）
        if span:
            span.update(level="ERROR", status_message=str(e))
            span.end()

    return state
