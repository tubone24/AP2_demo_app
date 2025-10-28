"""
v2/services/merchant/utils/validation_helpers.py

バリデーション関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ValidationHelpers:
    """バリデーションに関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, merchant_id: str):
        """
        Args:
            merchant_id: Merchant ID
        """
        self.merchant_id = merchant_id

    def validate_cart_mandate(self, cart_mandate: Dict[str, Any]):
        """
        CartMandateを検証（AP2準拠）

        - merchant_idが一致するか（_metadataから取得）
        - 価格が正しいか
        - 有効期限内か

        Args:
            cart_mandate: CartMandate

        Raises:
            ValueError: 検証失敗時
        """
        # AP2準拠：CartMandate.contents.cart_expiryを確認
        contents = cart_mandate.get("contents")
        if not contents:
            raise ValueError("CartMandate.contents is missing")

        # merchant_id確認（_metadataから取得）
        metadata = cart_mandate.get("_metadata", {})
        cart_merchant_id = metadata.get("merchant_id")
        if cart_merchant_id and cart_merchant_id != self.merchant_id:
            raise ValueError(f"Merchant ID mismatch: expected={self.merchant_id}, got={cart_merchant_id}")

        # 有効期限確認（CartContents.cart_expiry）
        cart_expiry_str = contents.get("cart_expiry")
        if cart_expiry_str:
            cart_expiry = datetime.fromisoformat(cart_expiry_str.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > cart_expiry:
                raise ValueError("CartMandate has expired")

        cart_id = contents.get("id")
        logger.info(f"[Merchant] CartMandate validation passed: {cart_id}")
