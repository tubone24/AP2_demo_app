"""
v2/services/merchant/utils/signature_helpers.py

CartMandate署名関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any
from v2.common.user_authorization import compute_mandate_hash

logger = logging.getLogger(__name__)


class SignatureHelpers:
    """CartMandate署名に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def compute_cart_hash(cart_mandate: Dict[str, Any]) -> str:
        """
        Cart Contentsのハッシュを計算

        Args:
            cart_mandate: CartMandate

        Returns:
            str: cart_hash
        """
        return compute_mandate_hash(cart_mandate)
