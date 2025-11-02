"""
v2/services/merchant_agent_mcp/utils/cart_mandate_helpers.py

CartMandate構築関連のヘルパーメソッド
"""

import uuid
import logging
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


class CartMandateHelpers:
    """CartMandate構築に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, merchant_id: str, merchant_name: str, merchant_url: str,
                 shipping_fee: float, free_shipping_threshold: float, tax_rate: float):
        """
        Args:
            merchant_id: Merchant ID
            merchant_name: Merchant名
            merchant_url: Merchant URL
            shipping_fee: 送料
            free_shipping_threshold: 送料無料の閾値
            tax_rate: 税率
        """
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.merchant_url = merchant_url
        self.shipping_fee = shipping_fee
        self.free_shipping_threshold = free_shipping_threshold
        self.tax_rate = tax_rate

    def build_cart_items(
        self,
        cart_plan: Dict[str, Any],
        products_map: Dict[int, Dict[str, Any]]
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
        """
        カートアイテムを構築

        Args:
            cart_plan: カートプラン
            products_map: 商品IDマッピング

        Returns:
            Tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]: (display_items, raw_items, subtotal)
        """
        display_items = []
        raw_items = []
        subtotal = 0.0

        for item in cart_plan.get("items", []):
            product_id = item["product_id"]
            quantity = item["quantity"]

            if product_id not in products_map:
                continue

            product = products_map[product_id]
            unit_price_jpy = product["price_jpy"]
            total_price_jpy = unit_price_jpy * quantity

            # AP2準拠: PaymentItem
            display_items.append({
                "label": product["name"],
                "amount": {
                    "value": total_price_jpy,  # AP2準拠: float, 円単位
                    "currency": "JPY"
                },
                "refund_period": product.get("refund_period_days", 30) * 86400  # 秒単位
            })

            # メタデータ（raw_items）
            raw_items.append({
                "product_id": product_id,
                "name": product["name"],
                "description": product.get("description"),
                "quantity": quantity,
                "unit_price": {"value": unit_price_jpy, "currency": "JPY"},
                "total_price": {"value": total_price_jpy, "currency": "JPY"},
                "image_url": product.get("image_url")
            })

            subtotal += total_price_jpy

        return display_items, raw_items, subtotal

    def calculate_tax(self, subtotal: float) -> Tuple[float, str]:
        """
        税金を計算

        Args:
            subtotal: 小計

        Returns:
            Tuple[float, str]: (税額, 税ラベル)
        """
        tax = round(subtotal * self.tax_rate, 2)
        tax_label = f"消費税（{int(self.tax_rate * 100)}%）"
        return tax, tax_label

    def calculate_shipping_fee(self, subtotal: float) -> float:
        """
        送料を計算

        Args:
            subtotal: 小計

        Returns:
            float: 送料
        """
        return self.shipping_fee if subtotal < self.free_shipping_threshold else 0.0

    def build_cart_mandate_structure(
        self,
        display_items: List[Dict[str, Any]],
        raw_items: List[Dict[str, Any]],
        total: float,
        shipping_address: Dict[str, Any],
        session_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        AP2準拠のCartMandate構造を構築

        Args:
            display_items: 表示アイテムリスト
            raw_items: 生アイテムリスト
            total: 合計金額
            shipping_address: 配送先住所
            session_data: セッションデータ

        Returns:
            Dict[str, Any]: CartMandate
        """
        cart_id = f"cart_{uuid.uuid4().hex[:8]}"
        cart_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace('+00:00', 'Z')

        cart_mandate = {
            "contents": {
                "id": cart_id,
                "user_cart_confirmation_required": True,
                "payment_request": {
                    "method_data": [],
                    "details": {
                        "id": cart_id,
                        "display_items": display_items,
                        "total": {
                            "label": "合計",
                            "amount": {"value": total, "currency": "JPY"}
                        }
                    },
                    "shipping_address": shipping_address
                },
                "cart_expiry": cart_expiry,
                "merchant_name": self.merchant_name
            },
            "merchant_authorization": None,  # 未署名
            "_metadata": {
                "intent_mandate_id": session_data.get("intent_mandate_id"),
                "merchant_id": self.merchant_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
                "cart_name": session_data.get("cart_name", "カート"),
                "cart_description": session_data.get("cart_description", ""),
                "raw_items": raw_items
            }
        }

        logger.info(f"[build_cart_mandates] Built CartMandate: {cart_id}")
        return cart_mandate
