"""
v2/services/shopping_agent_mcp/utils/a2a_helpers.py

A2Aメッセージペイロード作成関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class A2AHelpers:
    """A2Aメッセージペイロード作成に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def build_cart_request_payload(
        intent_mandate: Dict[str, Any],
        shipping_address: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        カート候補リクエスト用A2Aペイロード作成

        Args:
            intent_mandate: IntentMandate
            shipping_address: 配送先住所

        Returns:
            Dict[str, Any]: A2Aメッセージペイロード
        """
        payload = {
            "intent_mandate": intent_mandate,
            "shipping_address": shipping_address
        }

        logger.info(f"[build_cart_request_payload] Built payload for intent_id: {intent_mandate.get('id')}")
        return payload

    @staticmethod
    def add_user_signature_to_cart(
        cart_mandate: Dict[str, Any],
        user_signature: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        CartMandateにユーザー署名を追加

        Args:
            cart_mandate: CartMandate
            user_signature: ユーザー署名

        Returns:
            Dict[str, Any]: 署名済みCartMandate
        """
        signed_cart_mandate = cart_mandate.copy()
        signed_cart_mandate["user_authorization"] = user_signature

        cart_id = cart_mandate.get("contents", {}).get("id", "unknown")
        logger.info(f"[add_user_signature_to_cart] Cart signed: {cart_id}")
        return signed_cart_mandate
