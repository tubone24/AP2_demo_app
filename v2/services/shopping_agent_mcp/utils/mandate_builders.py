"""
v2/services/shopping_agent_mcp/utils/mandate_builders.py

IntentMandate、PaymentMandate構築関連のヘルパーメソッド
"""

import uuid
import logging
from typing import Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class MandateBuilders:
    """IntentMandate、PaymentMandate構築に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def build_intent_mandate_structure(
        intent_data: Dict[str, Any],
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        AP2準拠IntentMandate構築

        Args:
            intent_data: インテントデータ
            session_data: セッションデータ

        Returns:
            Dict[str, Any]: IntentMandate（未署名）
        """
        # IntentMandate ID生成
        intent_id = f"intent_{uuid.uuid4().hex[:16]}"

        # AP2準拠IntentMandate構築
        intent_mandate = {
            "id": intent_id,
            "natural_language_description": intent_data["natural_language_description"],
            "user_cart_confirmation_required": intent_data.get("user_cart_confirmation_required", True),
            "merchants": intent_data.get("merchants"),
            "skus": intent_data.get("skus"),
            "requires_refundability": intent_data.get("requires_refundability", False),
            "intent_expiry": intent_data["intent_expiry"],
            # メタデータ（AP2仕様外、内部管理用）
            "_metadata": {
                "user_id": session_data.get("user_id"),
                "session_id": session_data.get("session_id"),
                "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
            }
        }

        logger.info(f"[build_intent_mandate] Built IntentMandate: {intent_id}")
        return intent_mandate

    @staticmethod
    def build_payment_mandate_structure(
        cart_mandate: Dict[str, Any],
        payment_method: Dict[str, Any],
        risk_assessment: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        AP2準拠PaymentMandate構築

        Args:
            cart_mandate: 署名済みCartMandate
            payment_method: 支払い方法
            risk_assessment: リスク評価結果

        Returns:
            Dict[str, Any]: PaymentMandate
        """
        # PaymentMandate ID生成
        payment_id = f"payment_{uuid.uuid4().hex[:16]}"

        # AP2準拠PaymentMandate構築
        payment_mandate = {
            "id": payment_id,
            "cart_mandate": cart_mandate,
            "payment_method": payment_method,
            "risk_score": risk_assessment.get("risk_score", 0),
            "fraud_indicators": risk_assessment.get("fraud_indicators", []),
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[build_payment_mandate] Built PaymentMandate: {payment_id}")
        return payment_mandate
