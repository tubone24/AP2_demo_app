"""
v2/services/payment_processor/utils/mandate_helpers.py

Mandate検証関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class MandateHelpers:
    """Mandate検証に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def validate_payment_mandate(payment_mandate: Dict[str, Any]) -> None:
        """
        PaymentMandateを検証

        AP2仕様準拠：
        - 必須フィールドの存在チェック
        - user_authorizationフィールドの検証（AP2仕様で必須）

        Args:
            payment_mandate: PaymentMandate

        Raises:
            ValueError: 検証失敗時
        """
        required_fields = ["id", "amount", "payment_method", "payer_id", "payee_id"]
        for field in required_fields:
            if field not in payment_mandate:
                raise ValueError(f"Missing required field: {field}")

        # AP2仕様準拠：user_authorizationフィールドの検証
        # user_authorizationはCartMandateとPaymentMandateのハッシュに基づくユーザー承認トークン
        # 取引の正当性を保証する重要なフィールド
        user_authorization = payment_mandate.get("user_authorization")
        if user_authorization is None:
            raise ValueError(
                "AP2 specification violation: user_authorization field is required in PaymentMandate. "
                "This field contains the user's authorization token binding CartMandate and PaymentMandate."
            )

        logger.info(
            f"[PaymentProcessor] PaymentMandate validation passed: {payment_mandate['id']}, "
            f"user_authorization present: {user_authorization[:20] if user_authorization else 'None'}..."
        )
