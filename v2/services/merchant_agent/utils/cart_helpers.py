"""
v2/services/merchant_agent/utils/cart_helpers.py

カート関連のヘルパーメソッド
"""

import uuid
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class CartHelpers:
    """カート処理に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def build_cart_items_from_products(
        products: List[Any],
        quantities: List[int]
    ) -> tuple[List[Dict[str, Any]], int]:
        """
        商品リストからCartItemを作成し、小計を計算

        Args:
            products: 商品リスト
            quantities: 数量リスト

        Returns:
            tuple: (cart_items, subtotal_cents)
        """
        cart_items = []
        subtotal_cents = 0

        for product, quantity in zip(products, quantities):
            unit_price_cents = product.price
            total_price_cents = unit_price_cents * quantity

            metadata_dict = json.loads(product.product_metadata) if product.product_metadata else {}

            # AP2準拠: PaymentCurrencyAmount型（value: float、円単位）
            cart_items.append({
                "id": f"item_{uuid.uuid4().hex[:8]}",
                "name": product.name,
                "description": product.description,
                "quantity": quantity,
                "unit_price": {
                    "value": unit_price_cents / 100,  # AP2準拠: float型、円単位
                    "currency": "JPY"
                },
                "total_price": {
                    "value": total_price_cents / 100,  # AP2準拠: float型、円単位
                    "currency": "JPY"
                },
                "image_url": metadata_dict.get("image_url"),
                "sku": product.sku,
                "category": metadata_dict.get("category"),
                "brand": metadata_dict.get("brand")
            })

            subtotal_cents += total_price_cents

        return cart_items, subtotal_cents

    @staticmethod
    def calculate_cart_costs(subtotal_cents: int) -> Dict[str, int]:
        """
        税金、送料、合計を計算

        Args:
            subtotal_cents: 小計（セント単位）

        Returns:
            Dict[str, int]: tax_cents, shipping_cost_cents, total_cents
        """
        # 税金計算（10%）
        tax_cents = int(subtotal_cents * 0.1)

        # 送料計算（固定500円）
        shipping_cost_cents = 50000

        # 合計
        total_cents = subtotal_cents + tax_cents + shipping_cost_cents

        return {
            "tax_cents": tax_cents,
            "shipping_cost_cents": shipping_cost_cents,
            "total_cents": total_cents
        }
