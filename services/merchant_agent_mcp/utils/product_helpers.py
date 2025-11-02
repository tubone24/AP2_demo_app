"""
v2/services/merchant_agent_mcp/utils/product_helpers.py

商品データマッピング関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class ProductHelpers:
    """商品データマッピングに関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    def map_product_to_dict(product) -> Dict[str, Any]:
        """
        商品オブジェクトを辞書形式にマッピング

        Args:
            product: Product オブジェクト

        Returns:
            Dict[str, Any]: 商品情報の辞書
        """
        # metadataがSQLAlchemyのMetaDataオブジェクトの場合は空辞書に
        if hasattr(product.metadata, '__class__') and product.metadata.__class__.__name__ == 'MetaData':
            metadata = {}
        else:
            metadata = product.metadata or {}

        return {
            "id": product.id,
            "sku": product.sku,
            "name": product.name,
            "description": product.description,
            "price_cents": product.price,  # データベースはcents単位
            "price_jpy": product.price / 100.0,  # AP2準拠: float, 円単位
            "inventory_count": product.inventory_count,
            "category": metadata.get("category"),
            "brand": metadata.get("brand"),
            "image_url": product.image_url,  # 修正: DBカラムから直接取得
            "refund_period_days": metadata.get("refund_period_days", 30)
        }

    @staticmethod
    def map_products_to_list(products: List) -> List[Dict[str, Any]]:
        """
        商品オブジェクトリストを辞書リストにマッピング

        Args:
            products: Product オブジェクトのリスト

        Returns:
            List[Dict[str, Any]]: 商品情報の辞書リスト
        """
        products_list = []
        for product in products:
            if product.inventory_count <= 0:
                # 在庫なしはスキップ
                continue
            products_list.append(ProductHelpers.map_product_to_dict(product))

        return products_list
