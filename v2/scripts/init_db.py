"""
v2/scripts/init_db.py

データベース初期化スクリプト
- データベース作成
- サンプルデータ投入
"""

import sys
import asyncio
from pathlib import Path

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from v2.common.database import DatabaseManager, ProductCRUD
from v2.common.search_engine import MeilisearchClient
from v2.common.seed_data import seed_products, seed_users


async def sync_products_to_meilisearch(db_manager: DatabaseManager, search_client: MeilisearchClient):
    """ProductDBからMeilisearchへ全商品を同期（AP2準拠）"""
    print("\n🔍 Syncing products to Meilisearch...")

    try:
        # Meilisearchインデックス作成
        await search_client.create_index(primary_key="id")
        await search_client.configure_index()
        print("✅ Meilisearch index created and configured")

        # 既存のインデックスをクリア
        await search_client.clear_index()
        print("✅ Meilisearch index cleared")

        # ProductDBから全商品取得
        async with db_manager.get_session() as session:
            products = await ProductCRUD.list_all(session, limit=1000)

            # Meilisearch用のドキュメント作成
            documents = []
            for product in products:
                # metadataがSQLAlchemyのMetaDataオブジェクトの場合は空辞書に
                if hasattr(product.metadata, '__class__') and product.metadata.__class__.__name__ == 'MetaData':
                    metadata = {}
                else:
                    metadata = product.metadata or {}

                # 検索用キーワード生成（商品名から抽出）
                # 例: "むぎぼーTシャツ" → "むぎぼー Tシャツ グッズ 衣類"
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
                print(f"✅ Synced {len(documents)} products to Meilisearch")
            else:
                print("⚠️  No products to sync")

    except Exception as e:
        print(f"❌ Failed to sync to Meilisearch: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """データベースを初期化してサンプルデータを投入（Meilisearch同期含む）"""
    print("🗄️  Initializing AP2 Demo v2 Database...")

    # データベースディレクトリ作成
    db_dir = Path(__file__).parent.parent / "data"
    db_dir.mkdir(parents=True, exist_ok=True)

    # データベースマネージャー初期化
    db_manager = DatabaseManager()

    # データベース初期化
    print("Creating database schema...")
    await db_manager.init_db()
    print("✅ Database schema created")

    # サンプルデータ投入
    print("\n📦 Seeding sample data...")
    await seed_products(db_manager)
    await seed_users(db_manager)
    print("✅ Sample data seeded successfully")

    # Meilisearch同期
    search_client = MeilisearchClient()
    await sync_products_to_meilisearch(db_manager, search_client)

    print("\n🎉 Database initialization complete!")
    print(f"Database location: {db_dir / 'ap2.db'}")
    print(f"Meilisearch: http://localhost:7700 (master key: masterKey123)")


if __name__ == "__main__":
    asyncio.run(main())
