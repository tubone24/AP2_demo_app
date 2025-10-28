"""
v2/services/merchant_agent/utils/product_helpers.py

商品検索関連のヘルパーメソッド
"""

import logging
from typing import List

logger = logging.getLogger(__name__)


class ProductHelpers:
    """商品検索に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: データベースマネージャーのインスタンス
        """
        self.db_manager = db_manager

    async def sync_products_to_meilisearch(self, search_client):
        """
        ProductDBからMeilisearchへ全商品を同期（AP2準拠）

        Args:
            search_client: MeilisearchClientのインスタンス
        """
        try:
            from v2.common.database import ProductCRUD

            # Meilisearchインデックス作成
            await search_client.create_index(primary_key="id")
            await search_client.configure_index()

            # 既存のインデックスをクリア
            await search_client.clear_index()

            # ProductDBから全商品取得
            async with self.db_manager.get_session() as session:
                products = await ProductCRUD.list_all(session, limit=1000)

                # Meilisearch用のドキュメント作成
                documents = []
                for product in products:
                    # metadataがSQLAlchemyのMetaDataオブジェクトの場合は空辞書に
                    if hasattr(product.metadata, '__class__') and product.metadata.__class__.__name__ == 'MetaData':
                        metadata = {}
                    else:
                        metadata = product.metadata or {}

                    # 検索用キーワード生成（商品名 + 説明）
                    keywords = product.name
                    if product.description:
                        keywords += " " + product.description

                    doc = {
                        "id": product.id,
                        "name": product.name,
                        "description": product.description or "",
                        "keywords": keywords,
                        "category": metadata.get("category", ""),
                        "brand": metadata.get("brand", ""),
                        "price_jpy": product.price / 100.0,  # AP2準拠: float, 円単位
                        "created_at": product.created_at.isoformat() if product.created_at else ""
                    }
                    documents.append(doc)

                # Meilisearchに一括追加
                if documents:
                    await search_client.add_documents(documents)
                    logger.info(f"[_sync_products_to_meilisearch] Synced {len(documents)} products to Meilisearch")

        except Exception as e:
            logger.error(f"[_sync_products_to_meilisearch] Failed to sync: {e}", exc_info=True)
