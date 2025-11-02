"""
v2/services/shopping_agent/utils/cart_helpers.py

カート関連のヘルパーメソッド
"""

import uuid
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class CartHelpers:
    """カート処理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, signature_manager):
        """
        Args:
            signature_manager: 署名管理のインスタンス
        """
        self.signature_manager = signature_manager

    @staticmethod
    def create_cart_mandate(product: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
        """
        CartMandateを作成

        Args:
            product: 商品情報
            session: セッションデータ

        Returns:
            Dict[str, Any]: CartMandate
        """
        now = datetime.now(timezone.utc)

        cart_mandate = {
            "id": f"cart_{uuid.uuid4().hex[:8]}",
            "type": "CartMandate",
            "version": "0.2",
            "merchant_id": "did:ap2:merchant:mugibo_merchant",
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "items": [
                {
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "name": product["name"],
                    "quantity": 1,
                    "unit_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    },
                    "total_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    }
                }
            ],
            "total_amount": {
                "value": f"{product['price']}.00",
                "currency": "JPY"
            },
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[ShoppingAgent] CartMandate created: product={product['name']}, total={product['price']}")

        return cart_mandate

    @staticmethod
    def build_cart_request(
        selected_product: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        CartRequestを構築

        Args:
            selected_product: 選択された商品
            session: セッションデータ

        Returns:
            Dict[str, Any]: CartRequest
        """
        cart_request = {
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "intent_message_id": session.get("intent_message_id"),  # A2AメッセージID参照
            "items": [
                {
                    "product_id": selected_product.get("id"),
                    "quantity": 1
                }
            ],
            "shipping_address": {
                "recipient": "山田太郎",
                "postal_code": "150-0001",
                "address_line1": "東京都渋谷区神宮前1-1-1",
                "address_line2": "サンプルマンション101",
                "country": "JP"
            }
        }

        logger.info(
            f"[ShoppingAgent] CartRequest created: "
            f"intent_mandate_id={cart_request['intent_mandate_id']}, "
            f"intent_message_id={cart_request['intent_message_id']}"
        )

        return cart_request

    @staticmethod
    async def extract_cart_mandate_from_a2a_response(
        result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        A2AレスポンスからCartMandateを抽出

        Note: このメソッドは_wait_for_merchant_approvalへの依存があるため、
        実際の実装では親クラスのメソッドを参照する必要があります。

        Args:
            result: A2Aレスポンス

        Returns:
            Optional[Dict[str, Any]]: 署名済みCartMandate、またはNone

        Raises:
            ValueError: レスポンス形式が不正な場合
        """
        if not isinstance(result, dict) or "dataPart" not in result:
            raise ValueError("Invalid response format from Merchant Agent")

        data_part = result["dataPart"]

        # AP2/A2A仕様準拠：Artifact形式のCartMandateを処理
        signed_cart_mandate = None

        if data_part.get("kind") == "artifact" and data_part.get("artifact"):
            # Artifact形式（新仕様）
            artifact = data_part["artifact"]
            logger.info(f"[ShoppingAgent] Received A2A Artifact: {artifact.get('name')}, ID={artifact.get('artifactId')}")

            # Artifactから実データを抽出
            if artifact.get("parts") and len(artifact["parts"]) > 0:
                first_part = artifact["parts"][0]
                if first_part.get("kind") == "data" and first_part.get("data"):
                    data_obj = first_part["data"]
                    signed_cart_mandate = data_obj.get("CartMandate")
                    if signed_cart_mandate:
                        logger.info(f"[ShoppingAgent] Extracted CartMandate from Artifact: {signed_cart_mandate.get('id')}")

        # 後方互換性：従来のメッセージ形式もサポート
        if not signed_cart_mandate:
            response_type = data_part.get("@type") or data_part.get("type")
            if response_type == "ap2.mandates.CartMandate":
                signed_cart_mandate = data_part["payload"]
                logger.info(f"[ShoppingAgent] Received signed CartMandate (legacy format) from Merchant Agent: {signed_cart_mandate.get('id')}")
            elif response_type == "ap2.responses.CartMandatePending":
                # 手動署名モード：Merchantの承認待ち
                # NOTE: この処理は親クラスの_wait_for_merchant_approvalメソッドを必要とします
                pending_info = data_part["payload"]
                cart_mandate_id = pending_info.get("cart_mandate_id")
                logger.info(f"[ShoppingAgent] CartMandate is pending merchant approval: {cart_mandate_id}. Polling required...")
                # この部分は親クラスで処理する必要があります
                return None
            elif response_type == "ap2.errors.Error":
                error_payload = data_part["payload"]
                raise ValueError(f"Merchant Agent error: {error_payload.get('error_message')}")
            else:
                raise ValueError(f"Unexpected response type: {response_type}")

        return signed_cart_mandate

    def verify_merchant_cart_signature(
        self,
        signed_cart_mandate: Dict[str, Any]
    ) -> None:
        """
        CartMandateのMerchant Authorization JWT署名を検証（AP2完全準拠）

        Args:
            signed_cart_mandate: 署名済みCartMandate

        Raises:
            ValueError: 署名検証失敗時
        """
        # AP2完全準拠：merchant_authorization JWTを検証
        merchant_authorization = signed_cart_mandate.get("merchant_authorization")
        if not merchant_authorization:
            raise ValueError("CartMandate does not contain merchant_authorization JWT")

        # CartContentsを取得（JWT検証に必要）
        cart_contents = signed_cart_mandate.get("contents")
        if not cart_contents:
            raise ValueError("CartMandate does not contain contents")

        # MerchantAuthorizationJWTを使用して検証
        from common.jwt_utils import MerchantAuthorizationJWT
        jwt_verifier = MerchantAuthorizationJWT(
            signature_manager=self.signature_manager,
            key_manager=self.key_manager
        )

        try:
            # AP2完全準拠: CartMandate全体を渡す
            payload = jwt_verifier.verify(
                jwt=merchant_authorization,
                expected_cart_mandate=signed_cart_mandate
            )
            logger.info(
                f"[ShoppingAgent] Merchant authorization JWT verified for CartMandate: "
                f"merchant={payload.get('iss')}, cart_hash={payload.get('cart_hash')[:16]}..."
            )
        except Exception as e:
            logger.error(f"[ShoppingAgent] Merchant authorization JWT verification failed: {e}")
            raise ValueError(f"Merchant authorization JWT verification failed: {e}")
