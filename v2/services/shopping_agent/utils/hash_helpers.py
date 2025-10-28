"""
v2/services/shopping_agent/utils/hash_helpers.py

ハッシュ生成ユーティリティ
"""

from typing import Dict, Any


class HashHelpers:
    """CartMandateおよびPaymentMandateのハッシュ生成を担当するクラス"""

    @staticmethod
    def generate_cart_mandate_hash(cart_mandate: Dict[str, Any]) -> str:
        """
        CartMandateのハッシュを生成

        AP2仕様準拠：user_authorizationフィールドの生成に使用
        CartMandateの正規化されたJSONからSHA256ハッシュを計算

        署名フィールド（merchant_signature, merchant_authorization, user_signature）を除外して
        ハッシュを計算します。これにより、署名が追加される前後で同じハッシュ値が得られます。

        Args:
            cart_mandate: CartMandate辞書

        Returns:
            str: SHA256ハッシュの16進数表現
        """
        # RFC 8785準拠のcompute_mandate_hash関数を使用（署名フィールドを自動除外）
        from v2.common.user_authorization import compute_mandate_hash
        return compute_mandate_hash(cart_mandate)

    @staticmethod
    def generate_payment_mandate_hash(payment_mandate: Dict[str, Any]) -> str:
        """
        PaymentMandateのハッシュを生成

        AP2仕様準拠：user_authorizationフィールドの生成に使用
        PaymentMandateの正規化されたJSONからSHA256ハッシュを計算

        user_authorizationフィールドを除外してハッシュを計算します。

        Args:
            payment_mandate: PaymentMandate辞書

        Returns:
            str: SHA256ハッシュの16進数表現
        """
        # PaymentMandateからuser_authorizationフィールドを除外してコピー
        payment_mandate_copy = {
            k: v for k, v in payment_mandate.items() if k != 'user_authorization'
        }
        # RFC 8785準拠のcompute_mandate_hash関数を使用（より堅牢なハッシュ計算）
        from v2.common.user_authorization import compute_mandate_hash
        return compute_mandate_hash(payment_mandate_copy)
