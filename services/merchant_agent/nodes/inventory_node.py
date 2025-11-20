"""
v2/services/merchant_agent/nodes/inventory_node.py

在庫確認ノード（MCP経由）
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
        logger.warning(f"[Langfuse] Failed to initialize in inventory_node: {e}")
        LANGFUSE_ENABLED = False


async def check_inventory(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
    """在庫確認（MCP経由）"""
    products = state["available_products"]

    # 商品IDリスト抽出
    product_ids = [p["id"] for p in products]

    # Langfuseトレーシング: LangChain Tool経由で呼び出すことで、
    # CallbackHandlerが自動的に「tool」observation typeとして記録
    try:
        # LangChain Tool経由で在庫確認（Langfuse observation type用）
        result = await agent.call_mcp_tool_as_langchain("check_inventory", {
            "product_ids": product_ids
        })

        inventory_status = result.get("inventory", {})
        state["inventory_status"] = inventory_status
        logger.info(f"[check_inventory] MCP checked {len(inventory_status)} products")

    except Exception as e:
        logger.error(f"[check_inventory] MCP error: {e}")
        # フォールバック: 商品データから在庫情報取得
        inventory_status = {}
        for product in products:
            inventory_status[product["id"]] = product.get("stock", 0)
        state["inventory_status"] = inventory_status

    return state
