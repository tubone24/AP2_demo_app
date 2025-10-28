"""
v2/services/merchant/utils/inventory_helpers.py

在庫管理関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any
from v2.common.database import ProductCRUD

logger = logging.getLogger(__name__)


class InventoryHelpers:
    """在庫管理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: データベースマネージャーのインスタンス
        """
        self.db_manager = db_manager

    async def check_inventory(self, cart_mandate: Dict[str, Any]):
        """
        在庫を確認（AP2準拠）

        全アイテムの在庫が十分にあるか確認
        _metadata.raw_itemsから元のアイテム情報を取得

        Args:
            cart_mandate: CartMandate

        Raises:
            ValueError: 在庫不足時
        """
        # AP2準拠：_metadata.raw_itemsから商品情報を取得
        metadata = cart_mandate.get("_metadata", {})
        raw_items = metadata.get("raw_items", [])

        if not raw_items:
            # raw_itemsがない場合はスキップ（後方互換性）
            logger.warning("[Merchant] No raw_items in _metadata, skipping inventory check")
            return

        async with self.db_manager.get_session() as session:
            for item in raw_items:
                sku = item.get("sku")
                if not sku:
                    continue

                product = await ProductCRUD.get_by_sku(session, sku)
                if not product:
                    raise ValueError(f"Product not found: {sku}")

                required_quantity = item.get("quantity", 0)
                if product.inventory_count < required_quantity:
                    raise ValueError(
                        f"Insufficient inventory for {product.name}: "
                        f"required={required_quantity}, available={product.inventory_count}"
                    )

        cart_id = cart_mandate.get("contents", {}).get("id")
        logger.info(f"[Merchant] Inventory check passed for CartMandate: {cart_id}")
