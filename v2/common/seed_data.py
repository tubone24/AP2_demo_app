"""
v2/common/seed_data.py

サンプルデータ投入スクリプト
商品、ユーザーの初期データを作成
"""

import asyncio
import sys
from pathlib import Path

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from v2.common.database import DatabaseManager, ProductCRUD, User


# ========================================
# Sample Data
# ========================================

SAMPLE_PRODUCTS = [
    {
        "sku": "MUGI-KEYCHAIN-001",
        "name": "むぎぼーアクリルキーホルダー",
        "description": "かわいいむぎぼーのアクリルキーホルダー。バッグやポーチに付けて持ち歩けます。",
        "price": 80000,  # 800円 (in cents)
        "inventory_count": 100,
        "metadata": {
            "category": "Keychains",
            "brand": "Mugibow Official",
            "color": "Multicolor",
            "size": "約5cm",
            "material": "アクリル",
            "image_url": "/assets/むぎぼーアクリルキーホルダー.png"
        }
    },
    {
        "sku": "MUGI-CLOCK-001",
        "name": "むぎぼー時計",
        "description": "むぎぼーデザインのかわいい壁掛け時計。お部屋を明るく彩ります。",
        "price": 350000,  # 3,500円
        "inventory_count": 30,
        "metadata": {
            "category": "Clocks",
            "brand": "Mugibow Official",
            "color": "White/Yellow",
            "size": "直径25cm",
            "type": "壁掛け時計",
            "image_url": "/assets/むぎぼー時計.png"
        }
    },
    {
        "sku": "MUGI-CALENDAR-001",
        "name": "むぎぼーカレンダー",
        "description": "むぎぼーの1年カレンダー。毎月違うむぎぼーのイラストが楽しめます。",
        "price": 150000,  # 1,500円
        "inventory_count": 50,
        "metadata": {
            "category": "Calendars",
            "brand": "Mugibow Official",
            "color": "Full Color",
            "size": "A4サイズ",
            "year": "2025",
            "image_url": "/assets/むぎぼーカレンダー.png"
        }
    },
    {
        "sku": "MUGI-MUG-001",
        "name": "むぎぼーマグカップ",
        "description": "むぎぼーがプリントされたかわいいマグカップ。毎日のティータイムが楽しくなります。",
        "price": 120000,  # 1,200円
        "inventory_count": 80,
        "metadata": {
            "category": "Mug Cups",
            "brand": "Mugibow Official",
            "color": "White",
            "capacity": "350ml",
            "material": "陶器",
            "image_url": "/assets/むぎぼーマグカップ.png"
        }
    },
    {
        "sku": "MUGI-STICKER-001",
        "name": "むぎぼーステッカー",
        "description": "むぎぼーのステッカーセット（5枚入り）。ノートやスマホケースに貼れます。",
        "price": 50000,  # 500円
        "inventory_count": 200,
        "metadata": {
            "category": "Stickers",
            "brand": "Mugibow Official",
            "color": "Multicolor",
            "pack_size": 5,
            "size": "各約5cm",
            "material": "耐水ステッカー",
            "image_url": "/assets/むぎぼーステッカー.png"
        }
    },
    {
        "sku": "MUGI-TSHIRT-001",
        "name": "むぎぼーTシャツ",
        "description": "むぎぼーがプリントされたコットンTシャツ。普段着にぴったり。",
        "price": 280000,  # 2,800円
        "inventory_count": 60,
        "metadata": {
            "category": "Mugibow Apparel",
            "brand": "Mugibow Official",
            "color": "White",
            "sizes": ["S", "M", "L", "XL"],
            "material": "コットン100%",
            "image_url": "/assets/むぎぼーTシャツ.png"
        }
    },
    {
        "sku": "MUGI-TOTE-001",
        "name": "むぎぼートートバッグ",
        "description": "むぎぼーがプリントされた大きめトートバッグ。お買い物やお出かけに便利。",
        "price": 180000,  # 1,800円
        "inventory_count": 70,
        "metadata": {
            "category": "Mugibow Bags",
            "brand": "Mugibow Official",
            "color": "Natural",
            "size": "縦40cm×横35cm",
            "material": "キャンバス",
            "image_url": "/assets/むぎぼートート.png"
        }
    },
    {
        "sku": "MUGI-POUCH-001",
        "name": "むぎぼーポーチ",
        "description": "むぎぼー柄のかわいいポーチ。小物入れやペンケースとして使えます。",
        "price": 95000,  # 950円
        "inventory_count": 120,
        "metadata": {
            "category": "Mugibow Pouches",
            "brand": "Mugibow Official",
            "color": "Yellow/White",
            "size": "幅20cm×高さ12cm",
            "material": "ポリエステル",
            "image_url": "/assets/むぎぼーポーチ.png"
        }
    },
]

SAMPLE_USERS = [
    {
        "id": "user_demo_001",
        "display_name": "山田太郎",
        "email": "yamada@example.com"
    },
    {
        "id": "user_demo_002",
        "display_name": "佐藤花子",
        "email": "sato@example.com"
    }
]


# ========================================
# Seed Functions
# ========================================

async def seed_products(db_manager: DatabaseManager):
    """商品データを投入"""
    print("\n" + "=" * 60)
    print("商品データ投入中...")
    print("=" * 60)

    async with db_manager.get_session() as session:
        for product_data in SAMPLE_PRODUCTS:
            # 既存チェック
            existing = await ProductCRUD.get_by_sku(session, product_data["sku"])
            if existing:
                print(f"  ⏭️  スキップ: {product_data['name']} (既存)")
                continue

            # 作成
            product = await ProductCRUD.create(session, product_data)
            print(f"  ✅ 作成: {product.name} (¥{product.price // 100:,})")

    print(f"\n✅ 商品データ投入完了 ({len(SAMPLE_PRODUCTS)}件)")


async def seed_users(db_manager: DatabaseManager):
    """ユーザーデータを投入"""
    print("\n" + "=" * 60)
    print("ユーザーデータ投入中...")
    print("=" * 60)

    async with db_manager.get_session() as session:
        for user_data in SAMPLE_USERS:
            # 既存チェック（メールアドレスでチェック）
            from sqlalchemy.future import select
            result = await session.execute(
                select(User).where(User.email == user_data["email"])
            )
            existing = result.scalar_one_or_none()

            if existing:
                print(f"  ⏭️  スキップ: {user_data['display_name']} (既存)")
                continue

            # 作成
            user = User(**user_data)
            session.add(user)
            await session.commit()
            print(f"  ✅ 作成: {user.display_name} ({user.email})")

    print(f"\n✅ ユーザーデータ投入完了 ({len(SAMPLE_USERS)}件)")


async def main():
    """メイン処理"""
    print("\n" + "=" * 60)
    print("AP2 Demo v2 - サンプルデータ投入")
    print("=" * 60)

    # データベースマネージャー初期化
    db_manager = DatabaseManager()

    # テーブル作成
    print("\nデータベース初期化中...")
    await db_manager.init_db()
    print("✅ データベース初期化完了")

    # データ投入
    await seed_products(db_manager)
    await seed_users(db_manager)

    print("\n" + "=" * 60)
    print("🎉 すべてのサンプルデータ投入が完了しました！")
    print("=" * 60)
    print(f"\nデータベース: {db_manager.database_url}")
    print(f"商品数: {len(SAMPLE_PRODUCTS)}")
    print(f"ユーザー数: {len(SAMPLE_USERS)}")


if __name__ == "__main__":
    asyncio.run(main())
