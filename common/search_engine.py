"""
Meilisearch全文検索エンジンクライアント（AP2準拠、MCP準拠）

商品検索用の全文検索インデックスを管理。
MCPサーバーからのみアクセス（LangGraphから直接呼び出しは禁止）。

アーキテクチャ:
- Meilisearch: 全文検索エンジン（商品名、説明、キーワードで検索）
- Product DB: 商品詳細情報（価格、在庫、メタデータ）
- フロー: Meilisearch検索 → 商品ID取得 → Product DB問い合わせ
"""

import os
import httpx
from typing import List, Dict, Any, Optional
from common.logger import get_logger

logger = get_logger(__name__, service_name='search_engine')


class MeilisearchClient:
    """Meilisearch全文検索クライアント（AP2準拠）

    環境変数:
        MEILISEARCH_URL: Meilisearchエンドポイント（デフォルト: http://meilisearch:7700）
        MEILISEARCH_MASTER_KEY: マスターキー（デフォルト: masterKey123）
    """

    def __init__(
        self,
        url: Optional[str] = None,
        master_key: Optional[str] = None
    ):
        self.url = url or os.getenv("MEILISEARCH_URL", "http://meilisearch:7700")
        self.master_key = master_key or os.getenv("MEILISEARCH_MASTER_KEY", "masterKey123")
        self.index_name = "products"  # 商品インデックス名

        logger.info(f"[MeilisearchClient] Initialized: {self.url}, index={self.index_name}")

    async def create_index(self, primary_key: str = "id") -> Dict[str, Any]:
        """商品インデックスを作成

        Args:
            primary_key: プライマリキー（商品ID）

        Returns:
            インデックス作成結果
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.url}/indexes",
                json={
                    "uid": self.index_name,
                    "primaryKey": primary_key
                },
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=30.0
            )

            if response.status_code == 201:
                logger.info(f"[MeilisearchClient] Index created: {self.index_name}")
                return response.json()
            elif response.status_code == 202:
                # 既に作成済み
                logger.info(f"[MeilisearchClient] Index already exists: {self.index_name}")
                return response.json()
            else:
                logger.error(f"[MeilisearchClient] Failed to create index: {response.text}")
                response.raise_for_status()

    async def configure_index(self) -> None:
        """インデックス設定（検索可能フィールド、フィルタリング等）

        AP2準拠の商品検索設定:
        - searchableAttributes: name, description, keywords, category, brand
        - filterableAttributes: category, brand, price_min, price_max
        - sortableAttributes: price, created_at
        """
        settings = {
            "searchableAttributes": [
                "name",
                "description",
                "keywords",
                "category",
                "brand"
            ],
            "filterableAttributes": [
                "category",
                "brand",
                "price_jpy"
            ],
            "sortableAttributes": [
                "price_jpy",
                "created_at"
            ],
            "rankingRules": [
                "words",
                "typo",
                "proximity",
                "attribute",
                "sort",
                "exactness"
            ]
        }

        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{self.url}/indexes/{self.index_name}/settings",
                json=settings,
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=30.0
            )

            if response.status_code in [200, 202]:
                logger.info(f"[MeilisearchClient] Index configured: {self.index_name}")
            else:
                logger.error(f"[MeilisearchClient] Failed to configure index: {response.text}")
                response.raise_for_status()

    async def add_documents(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """ドキュメント追加（商品データ）

        Args:
            documents: 商品ドキュメントリスト
                例: [{"id": "123", "name": "むぎぼーTシャツ", "description": "...", "keywords": "Tシャツ グッズ", ...}]

        Returns:
            追加タスク情報
        """
        if not documents:
            logger.warning("[MeilisearchClient] No documents to add")
            return {}

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.url}/indexes/{self.index_name}/documents",
                json=documents,
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=60.0
            )

            if response.status_code in [200, 202]:
                result = response.json()
                logger.info(f"[MeilisearchClient] Added {len(documents)} documents, taskUid={result.get('taskUid')}")
                return result
            else:
                logger.error(f"[MeilisearchClient] Failed to add documents: {response.text}")
                response.raise_for_status()

    async def search(
        self,
        query: str,
        limit: int = 20,
        filters: Optional[str] = None
    ) -> List[str]:
        """商品検索（AP2準拠）

        Args:
            query: 検索クエリ（例: "かわいいグッズ"）
            limit: 最大結果数
            filters: フィルタ（例: "category = 'apparel'"）

        Returns:
            商品IDリスト（Product DBで詳細取得するため）
        """
        search_params = {
            "q": query,
            "limit": limit,
            "attributesToRetrieve": ["id"]  # IDのみ取得（詳細はProduct DBから）
        }

        if filters:
            search_params["filter"] = filters

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.url}/indexes/{self.index_name}/search",
                json=search_params,
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=30.0
            )

            if response.status_code == 200:
                result = response.json()
                hits = result.get("hits", [])
                product_ids = [str(hit["id"]) for hit in hits]
                logger.info(f"[MeilisearchClient] Search '{query}' returned {len(product_ids)} products")
                return product_ids
            else:
                logger.error(f"[MeilisearchClient] Search failed: {response.text}")
                return []

    async def delete_document(self, document_id: str) -> Dict[str, Any]:
        """ドキュメント削除

        Args:
            document_id: 商品ID

        Returns:
            削除タスク情報
        """
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.url}/indexes/{self.index_name}/documents/{document_id}",
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=30.0
            )

            if response.status_code in [200, 202]:
                result = response.json()
                logger.info(f"[MeilisearchClient] Deleted document: {document_id}")
                return result
            else:
                logger.error(f"[MeilisearchClient] Failed to delete document: {response.text}")
                response.raise_for_status()

    async def update_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """ドキュメント更新

        Args:
            document: 更新する商品ドキュメント（idフィールド必須）

        Returns:
            更新タスク情報
        """
        return await self.add_documents([document])

    async def clear_index(self) -> Dict[str, Any]:
        """インデックスの全ドキュメント削除（開発用）"""
        async with httpx.AsyncClient() as client:
            response = await client.delete(
                f"{self.url}/indexes/{self.index_name}/documents",
                headers={"Authorization": f"Bearer {self.master_key}"},
                timeout=30.0
            )

            if response.status_code in [200, 202]:
                result = response.json()
                logger.info(f"[MeilisearchClient] Cleared index: {self.index_name}")
                return result
            else:
                logger.error(f"[MeilisearchClient] Failed to clear index: {response.text}")
                response.raise_for_status()
