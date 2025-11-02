"""
v2/services/merchant_agent/handlers/cart_handler.py

カート関連リクエスト処理ハンドラー
"""

import uuid
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from services.merchant_agent.agent import MerchantAgent

import httpx
from common.models import A2AMessage
from common.logger import get_logger

logger = get_logger(__name__, service_name='merchant_agent')


async def handle_cart_selection(agent: 'MerchantAgent', message: A2AMessage) -> Dict[str, Any]:
    """
    カート選択通知を受信（Shopping Agentから） - AI化で追加

    ユーザーが複数のカート候補から1つを選択したことを通知。
    選択されたカートをMerchantに署名依頼して返却。

    Args:
        message: A2AMessage
            - payload.selected_cart_id: 選択されたカートID
            - payload.cart_mandate: 選択されたCartMandate（未署名）
            - payload.user_id: ユーザーID

    Returns:
        署名済みCartMandateまたはエラー
    """
    logger.info("[MerchantAgent] Received CartSelectionRequest")
    payload = message.dataPart.payload

    selected_cart_id = payload.get("selected_cart_id")
    cart_mandate = payload.get("cart_mandate")
    user_id = payload.get("user_id")

    if not cart_mandate:
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "invalid_cart_selection",
                "error_message": "cart_mandate is required"
            }
        }

    logger.info(f"[MerchantAgent] User {user_id} selected cart: {selected_cart_id}")

    try:
        # MerchantにCartMandateの署名を依頼（HTTP）
        response = await agent.http_client.post(
            f"{agent.merchant_url}/sign/cart",
            json={"cart_mandate": cart_mandate},
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()

        # 署名済みCartMandateを取得
        signed_cart_mandate = result.get("signed_cart_mandate")
        if signed_cart_mandate:
            logger.info(f"[MerchantAgent] CartMandate signed: {selected_cart_id}")

            # 署名済みCartMandateを返却
            return {
                "type": "ap2.responses.SignedCartMandate",
                "id": str(uuid.uuid4()),
                "payload": {
                    "cart_mandate": signed_cart_mandate,
                    "cart_id": selected_cart_id
                }
            }

        # 手動署名待ち
        if result.get("status") == "pending_merchant_signature":
            logger.info(f"[MerchantAgent] CartMandate pending manual approval: {selected_cart_id}")
            return {
                "type": "ap2.responses.CartMandatePending",
                "id": str(uuid.uuid4()),
                "payload": {
                    "cart_mandate_id": result.get("cart_mandate_id"),
                    "status": "pending_merchant_signature",
                    "message": result.get("message", "Manual merchant approval required")
                }
            }

        raise ValueError(f"Unexpected response from Merchant: {result}")

    except Exception as e:
        logger.error(f"[handle_cart_selection] Error: {e}", exc_info=True)
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "cart_signature_failed",
                "error_message": str(e)
            }
        }


async def handle_cart_request(agent: 'MerchantAgent', message: A2AMessage) -> Dict[str, Any]:
    """
    CartRequestを受信（Shopping Agentから）- 従来フロー

    AP2仕様準拠（Steps 10-12）：
    1. Merchant Agentが商品選択情報を受信
    2. Merchant AgentがCartMandateを作成（未署名）
    3. Merchant AgentがMerchantに署名依頼（HTTP）
    4. Merchant Agentが署名済みCartMandateを返却
    """
    logger.info("[MerchantAgent] Received CartRequest")
    cart_request = message.dataPart.payload

    try:
        # CartMandateを作成（未署名）
        cart_mandate = await agent._create_cart_mandate(cart_request)

        logger.info(f"[MerchantAgent] Created CartMandate: {cart_mandate['id']}")

        # MerchantにCartMandateの署名を依頼（HTTP）
        try:
            response = await agent.http_client.post(
                f"{agent.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 自動署名モードの場合
            signed_cart_mandate = result.get("signed_cart_mandate")
            if signed_cart_mandate:
                logger.info(f"[MerchantAgent] CartMandate signed by Merchant: {cart_mandate['id']}")

                # 署名済みCartMandateをArtifactとして返却
                # AP2/A2A仕様準拠：a2a-extension.md:144-229
                return {
                    "is_artifact": True,
                    "artifact_name": "CartMandate",
                    "artifact_data": signed_cart_mandate,
                    "data_type_key": "CartMandate"
                }

            # 手動署名モードの場合（pending_merchant_signature）
            if result.get("status") == "pending_merchant_signature":
                logger.info(f"[MerchantAgent] CartMandate pending manual approval: {cart_mandate['id']}")
                return {
                    "type": "ap2.responses.CartMandatePending",
                    "id": cart_mandate["id"],
                    "payload": {
                        "cart_mandate_id": result.get("cart_mandate_id"),
                        "status": "pending_merchant_signature",
                        "message": result.get("message", "Manual merchant approval required"),
                        "cart_mandate": cart_mandate  # 未署名のCartMandateも含める
                    }
                }

            # 予期しないレスポンス
            raise ValueError(f"Unexpected response from Merchant: {result}")

        except httpx.HTTPError as e:
            logger.error(f"[handle_cart_request] Failed to get Merchant signature: {e}")
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "merchant_signature_failed",
                    "error_message": f"Failed to get Merchant signature: {str(e)}"
                }
            }

    except Exception as e:
        logger.error(f"[handle_cart_request] Error: {e}", exc_info=True)
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "cart_creation_failed",
                "error_message": str(e)
            }
        }
