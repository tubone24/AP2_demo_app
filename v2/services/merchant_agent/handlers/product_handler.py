"""
v2/services/merchant_agent/handlers/product_handler.py

商品検索リクエスト処理ハンドラー
"""

import uuid
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from v2.services.merchant_agent.agent import MerchantAgent

from v2.common.models import A2AMessage
from v2.common.database import ProductCRUD
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='merchant_agent')


async def handle_product_search_request(agent: 'MerchantAgent', message: A2AMessage) -> Dict[str, Any]:
    """
    商品検索リクエストを受信（AI化対応）

    AI Modeの場合:
    - IntentMandateを含むリクエストからLangGraphで複数カート候補を生成
    - ap2.responses.CartCandidates として返却（Shopping Agent対応済み）

    従来Mode:
    - 単純な商品リストを返却（ap2.responses.ProductList）
    """
    logger.info(f"[MerchantAgent] Received ProductSearchRequest (AI Mode: {agent.ai_mode_enabled})")
    search_params = message.dataPart.payload

    # AI Mode: IntentMandateが含まれている場合、複数カート候補を生成
    if agent.ai_mode_enabled and "intent_mandate" in search_params:
        logger.info("[MerchantAgent] AI Mode: Generating cart candidates with LangGraph")

        intent_mandate = search_params["intent_mandate"]
        user_id = search_params.get("user_id", "unknown")
        session_id = search_params.get("session_id", str(uuid.uuid4()))

        try:
            # LangGraphで複数カート候補を生成
            cart_candidates = await agent.langgraph_agent.create_cart_candidates(
                intent_mandate=intent_mandate,
                user_id=user_id,
                session_id=session_id
            )

            logger.info(f"[MerchantAgent] Generated {len(cart_candidates)} cart candidates")

            # ap2.responses.CartCandidates として返却（Shopping Agent対応済み）
            return {
                "type": "ap2.responses.CartCandidates",
                "id": str(uuid.uuid4()),
                "payload": {
                    "cart_candidates": cart_candidates,
                    "intent_mandate_id": intent_mandate.get("id"),
                    "merchant_id": agent.merchant_id,
                    "merchant_name": agent.merchant_name
                }
            }

        except Exception as e:
            logger.error(f"[handle_product_search_request] LangGraph error: {e}", exc_info=True)
            # フォールバック: 従来の商品リスト返却
            pass

    # 従来Mode: 単純な商品検索
    query = search_params.get("query", "")
    limit = search_params.get("max_results", 10)

    async with agent.db_manager.get_session() as session:
        products = await ProductCRUD.search(session, query, limit)

    return {
        "type": "ap2.responses.ProductList",
        "id": str(uuid.uuid4()),
        "payload": {
            "products": [p.to_dict() for p in products],
            "total": len(products)
        }
    }
