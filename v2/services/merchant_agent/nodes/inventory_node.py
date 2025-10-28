"""
v2/services/merchant_agent/nodes/inventory_node.py

在庫確認ノード（MCP経由）
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
        logger.warning(f"[Langfuse] Failed to initialize in inventory_node: {e}")
        LANGFUSE_ENABLED = False


async def check_inventory(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
    """在庫確認（MCP経由）"""
    products = state["available_products"]

    # 商品IDリスト抽出
    product_ids = [p["id"] for p in products]

    # Langfuseトレーシング（MCPツール呼び出し）
    trace_id = state.get("session_id", "unknown")
    span = None  # スパン初期化

    try:
        # Langfuseスパン開始（可観測性向上）
        if LANGFUSE_ENABLED and langfuse_client:
            span = langfuse_client.start_span(
                name="mcp_check_inventory",
                input={"product_ids": product_ids},
                metadata={"tool": "check_inventory", "mcp_server": "merchant_agent_mcp", "session_id": trace_id}
            )

        # MCP経由で在庫確認
        result = await agent.mcp_client.call_tool("check_inventory", {
            "product_ids": product_ids
        })

        inventory_status = result.get("inventory", {})
        state["inventory_status"] = inventory_status
        logger.info(f"[check_inventory] MCP checked {len(inventory_status)} products")

        # Langfuseスパン終了（成功時）
        if span:
            span.update(output={"inventory_status": inventory_status})
            span.end()

    except Exception as e:
        logger.error(f"[check_inventory] MCP error: {e}")
        # フォールバック: 商品データから在庫情報取得
        inventory_status = {}
        for product in products:
            inventory_status[product["id"]] = product.get("stock", 0)
        state["inventory_status"] = inventory_status

        # Langfuseスパン終了（エラー時）
        if span:
            span.update(level="ERROR", status_message=str(e), output={"fallback_inventory": inventory_status})
            span.end()

    return state
