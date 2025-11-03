"""
v2/services/shopping_agent/utils/payment_helpers.py

支払い関連のヘルパーメソッド
"""

import os
import uuid
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

from common.user_authorization import create_user_authorization_vp

logger = logging.getLogger(__name__)


class PaymentHelpers:
    """支払い処理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, risk_engine):
        """
        Args:
            risk_engine: リスク評価エンジンのインスタンス
        """
        self.risk_engine = risk_engine

    @staticmethod
    def validate_cart_and_payment_method(session: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """
        カート情報とトークン化された支払い方法を検証

        Returns:
            tuple: (cart_mandate, tokenized_payment_method)

        Raises:
            ValueError: カート情報または支払い方法が存在しない場合
        """
        cart_mandate = session.get("cart_mandate", {})
        if not cart_mandate:
            logger.error("[ShoppingAgent] No cart mandate available")
            raise ValueError("No cart mandate available")

        tokenized_payment_method = session.get("tokenized_payment_method", {})
        if not tokenized_payment_method or not tokenized_payment_method.get("token"):
            logger.error("[ShoppingAgent] No tokenized payment method available")
            raise ValueError("No tokenized payment method available")

        return cart_mandate, tokenized_payment_method

    @staticmethod
    def extract_payment_amount_from_cart(cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """
        CartMandateから金額情報を抽出

        AP2仕様準拠：金額はCartMandate.contents.payment_request.details.totalから取得

        Args:
            cart_mandate: CartMandate

        Returns:
            Dict: 金額情報 {"value": "1000.00", "currency": "JPY"}
        """
        contents = cart_mandate.get("contents", {})
        payment_request = contents.get("payment_request", {})
        details = payment_request.get("details", {})
        total_item = details.get("total", {})
        total_amount = total_item.get("amount", {})

        # デバッグログ：CartMandateの構造を確認
        logger.info(
            f"[_extract_payment_amount_from_cart] CartMandate structure: "
            f"has_contents={bool(contents)}, "
            f"has_payment_request={bool(payment_request)}, "
            f"has_details={bool(details)}, "
            f"has_total={bool(total_item)}, "
            f"total_amount={total_amount}"
        )

        return total_amount

    @staticmethod
    def build_payment_response(tokenized_payment_method: Dict[str, Any]) -> Dict[str, Any]:
        """
        PaymentResponseを構築（AP2完全準拠 & PCI DSS準拠）

        Args:
            tokenized_payment_method: トークン化された支払い方法

        Returns:
            Dict: PaymentResponse

        AP2完全準拠 & PCI DSS準拠:
        - tokenized=trueの場合、カード番号とCVVを含めない（PCI DSS 3.2.2項準拠）
        - トークンで決済を実行（Credential Providerが内部で保持）
        - A2A通信では「認証済みトークンベース決済」を想定

        PCI DSS コンプライアンス:
        - cardSecurityCode（CVV/CVC）: 認証後の保持・送信は禁止（PCI DSS 3.2.2項）
        - cardNumber: マスクしていても、トークン化済みなら不要（AP2仕様）
        - token: ✅ 安全（tokenized=trueにより、カード情報は削除済みと見なされる）

        W3C Payment Request API準拠:
        - methodName: AP2公式のpayment method URL（basic-cardは非推奨）
        - https://a2a-protocol.org/payment-methods/ap2-payment
        """
        return {
            "methodName": "https://a2a-protocol.org/payment-methods/ap2-payment",
            "details": {
                # AP2完全準拠 & PCI DSS準拠:
                # - cardNumber: マスク済みでも、トークン化済みなら不要（削除）
                # - cardSecurityCode: PCI DSS 3.2.2項により禁止（削除）
                "cardBrand": tokenized_payment_method.get("brand", "unknown"),
                # AP2拡張：トークン（Credential Providerで実際のカード情報と紐付け）
                "token": tokenized_payment_method["token"],
                "tokenized": True
                # PCI DSS準拠により除外:
                # - cardholderName: 除外（PCI機密データ）
                # - expiryMonth/Year: 除外（トークン化により内部管理）
            }
        }

    @staticmethod
    def build_payment_mandate_contents(
        cart_mandate: Dict[str, Any],
        total_amount: Dict[str, Any],
        payment_response: Dict[str, Any]
    ) -> Tuple[str, Dict[str, Any]]:
        """
        PaymentMandateContentsを構築（AP2公式型定義準拠）

        Args:
            cart_mandate: CartMandate
            total_amount: 金額情報
            payment_response: PaymentResponse

        Returns:
            tuple: (payment_mandate_id, payment_mandate_contents)
        """
        now = datetime.now(timezone.utc)
        payment_mandate_id = f"payment_{uuid.uuid4().hex[:8]}"
        payment_details_id = cart_mandate.get("id", f"order_{uuid.uuid4().hex[:8]}")

        # PaymentItem（payment_details_total）
        payment_details_total = {
            "label": "Total",
            "amount": {
                "value": total_amount.get("value", "0.00"),
                "currency": total_amount.get("currency", "JPY")
            }
        }

        # AP2公式型定義準拠：PaymentMandate構造
        payment_mandate_contents = {
            "payment_mandate_id": payment_mandate_id,
            "payment_details_id": payment_details_id,
            "payment_details_total": payment_details_total,
            "payment_response": payment_response,
            "merchant_agent": cart_mandate.get("merchant_id", "did:ap2:merchant:mugibo_merchant"),
            "timestamp": now.isoformat().replace('+00:00', 'Z')
        }

        return payment_mandate_id, payment_mandate_contents

    @staticmethod
    def generate_user_authorization_for_payment(
        session: Dict[str, Any],
        cart_mandate: Dict[str, Any],
        payment_mandate_contents: Dict[str, Any],
        public_key_cose: str
    ) -> Optional[str]:
        """
        user_authorizationを生成（WebAuthn assertionからSD-JWT-VC形式）

        Args:
            session: セッション情報
            cart_mandate: CartMandate
            payment_mandate_contents: PaymentMandateContents
            public_key_cose: COSE形式の公開鍵（base64エンコード済み、DB保存済みの値）

        Returns:
            Optional[str]: user_authorization（生成失敗時はNone）
        """
        cart_webauthn_assertion = session.get("cart_webauthn_assertion")
        if not cart_webauthn_assertion:
            return None

        try:
            user_authorization = create_user_authorization_vp(
                webauthn_assertion=cart_webauthn_assertion,
                cart_mandate=cart_mandate,
                payment_mandate_contents=payment_mandate_contents,
                user_id=session.get("user_id", "user_demo_001"),
                public_key_cose=public_key_cose,
                payment_processor_id="did:ap2:agent:payment_processor"
            )
            logger.info(
                f"[_generate_user_authorization_for_payment] Generated user_authorization VP: "
                f"length={len(user_authorization)}"
            )
            return user_authorization
        except Exception as e:
            logger.error(f"[_generate_user_authorization_for_payment] Failed to generate user_authorization: {e}", exc_info=True)
            return None

    def perform_risk_assessment(
        self,
        payment_mandate: Dict[str, Any],
        cart_mandate: Dict[str, Any],
        intent_mandate: Optional[Dict[str, Any]]
    ) -> Tuple[int, list]:
        """
        リスク評価を実施してリスクスコアと不正指標を返す

        Args:
            payment_mandate: PaymentMandate
            cart_mandate: CartMandate
            intent_mandate: IntentMandate（オプション）

        Returns:
            tuple: (risk_score, fraud_indicators)
        """
        try:
            logger.info("[ShoppingAgent] Performing risk assessment...")
            risk_result = self.risk_engine.assess_payment_mandate(
                payment_mandate=payment_mandate,
                cart_mandate=cart_mandate,
                intent_mandate=intent_mandate
            )

            logger.info(
                f"[ShoppingAgent] Risk assessment completed: "
                f"score={risk_result.risk_score}, "
                f"recommendation={risk_result.recommendation}, "
                f"indicators={risk_result.fraud_indicators}"
            )

            # 高リスクの場合は警告ログ
            if risk_result.recommendation == "decline":
                logger.warning(
                    f"[ShoppingAgent] High-risk transaction detected! "
                    f"score={risk_result.risk_score}, "
                    f"recommendation={risk_result.recommendation}"
                )

            return risk_result.risk_score, risk_result.fraud_indicators

        except Exception as e:
            logger.error(f"[ShoppingAgent] Risk assessment failed: {e}", exc_info=True)
            # リスク評価失敗時はデフォルト値を返す
            return 50, ["risk_assessment_failed"]  # 中リスク
