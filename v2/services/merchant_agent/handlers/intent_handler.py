"""
v2/services/merchant_agent/handlers/intent_handler.py

IntentMandate処理ハンドラー
"""

import uuid
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from v2.services.merchant_agent.agent import MerchantAgent

from v2.common.models import A2AMessage
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='merchant_agent')


async def handle_intent_mandate(agent: 'MerchantAgent', message: A2AMessage) -> Dict[str, Any]:
    """
    IntentMandateを受信（Shopping Agentから）

    AP2/A2A仕様準拠：
    - IntentMandateから複数のカート候補を生成
    - 各カートをArtifactとして返却
    - a2a-extension.md:144-229

    AP2仕様準拠（v0.1）：
    - ペイロードにはintent_mandateとshipping_addressが含まれる
    - 配送先はCartMandate作成前に確定している必要がある
    """
    logger.info("[MerchantAgent] Received IntentMandate")
    payload = message.dataPart.payload

    # AP2仕様準拠：ペイロードからintent_mandateとshipping_addressを抽出
    if isinstance(payload, dict) and "intent_mandate" in payload:
        # 新しい形式：{intent_mandate: {...}, shipping_address: {...}}
        intent_mandate = payload["intent_mandate"]
        shipping_address = payload.get("shipping_address")
        logger.info("[MerchantAgent] Received IntentMandate with shipping_address (AP2 v0.1 compliant)")
    else:
        # 旧形式（後方互換性のため）：payload自体がintent_mandate
        intent_mandate = payload
        shipping_address = None
        logger.info("[MerchantAgent] Received IntentMandate without shipping_address (legacy format)")

    # AP2準拠：natural_language_descriptionフィールドを使用
    intent_text = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))
    logger.info(f"[MerchantAgent] Searching products with intent: '{intent_text}'")

    try:
        # 配送先住所の決定（AP2仕様準拠）
        if shipping_address:
            # Shopping Agentから提供された配送先を使用
            logger.info(f"[MerchantAgent] Using provided shipping address: {shipping_address.get('recipient', 'N/A')}")
        else:
            # デフォルト配送先住所（デモ用・後方互換性）
            shipping_address = {
                "recipient": "デモユーザー",
                "address_line1": "東京都渋谷区渋谷1-1-1",
                "address_line2": "",
                "city": "渋谷区",
                "state": "東京都",
                "postal_code": "150-0001",
                "country": "JP"
            }
            logger.info("[MerchantAgent] Using default shipping address")

        # 複数のカート候補を生成
        # AI Mode: LangGraphエンジンを使用
        if agent.ai_mode_enabled and agent.langgraph_agent:
            logger.info("[MerchantAgent] Using LangGraph AI engine for cart generation")
            cart_candidates = await agent.langgraph_agent.create_cart_candidates(
                intent_mandate=intent_mandate,
                user_id=intent_mandate.get("user_id", "unknown"),
                session_id=str(uuid.uuid4())
            )
        else:
            # 従来Mode: 固定ロジック
            logger.info("[MerchantAgent] Using legacy cart generation")
            cart_candidates = await agent._create_multiple_cart_candidates(
                intent_mandate_id=intent_mandate["id"],
                intent_text=intent_text,
                shipping_address=shipping_address
            )

        if not cart_candidates:
            logger.warning("[MerchantAgent] No cart candidates generated")
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "no_products_found",
                    "error_message": f"No products found matching intent: {intent_text}"
                }
            }

        logger.info(f"[MerchantAgent] Generated {len(cart_candidates)} cart candidates")

        # 各カート候補をArtifactとして返却
        # A2AハンドラーはこのリストをArtifactsとして処理する
        return {
            "type": "ap2.responses.CartCandidates",
            "id": str(uuid.uuid4()),
            "payload": {
                "intent_mandate_id": intent_mandate["id"],
                "cart_candidates": cart_candidates,
                "merchant_id": agent.merchant_id,
                "merchant_name": agent.merchant_name
            }
        }

    except Exception as e:
        logger.error(f"[handle_intent_mandate] Error: {e}", exc_info=True)
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "intent_processing_failed",
                "error_message": str(e)
            }
        }
