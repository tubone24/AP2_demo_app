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
        "sku": "SHOE-RUN-001",
        "name": "ナイキ エアズーム ペガサス 40",
        "description": "軽量で反発力のあるランニングシューズ。毎日のトレーニングに最適。",
        "price": 1480000,  # 14,800円 (in cents)
        "inventory_count": 50,
        "metadata": {
            "category": "Running Shoes",
            "brand": "Nike",
            "color": "Black/White",
            "sizes": ["25.0", "25.5", "26.0", "26.5", "27.0", "27.5", "28.0"],
            "image_url": "https://placehold.co/400x400/333/FFF?text=Nike+Pegasus"
        }
    },
    {
        "sku": "SHOE-RUN-002",
        "name": "アディダス ウルトラブースト 22",
        "description": "最高のクッション性とエネルギーリターンを提供する革新的なランニングシューズ。",
        "price": 1980000,  # 19,800円
        "inventory_count": 30,
        "metadata": {
            "category": "Running Shoes",
            "brand": "Adidas",
            "color": "Core Black",
            "sizes": ["25.0", "25.5", "26.0", "26.5", "27.0", "27.5", "28.0"],
            "image_url": "https://placehold.co/400x400/000/FFF?text=Adidas+Ultraboost"
        }
    },
    {
        "sku": "SHOE-TRAIL-001",
        "name": "サロモン スピードクロス 5",
        "description": "過酷なトレイルに対応する強力なグリップとプロテクション。",
        "price": 1650000,  # 16,500円
        "inventory_count": 20,
        "metadata": {
            "category": "Trail Running Shoes",
            "brand": "Salomon",
            "color": "Black/Red",
            "sizes": ["25.5", "26.0", "26.5", "27.0", "27.5", "28.0"],
            "image_url": "https://placehold.co/400x400/C00/FFF?text=Salomon+Speedcross"
        }
    },
    {
        "sku": "WEAR-SHIRT-001",
        "name": "ナイキ ドライフィット ランニングシャツ",
        "description": "速乾性に優れたテクニカルシャツ。長時間のランでも快適。",
        "price": 450000,  # 4,500円
        "inventory_count": 100,
        "metadata": {
            "category": "Running Apparel",
            "brand": "Nike",
            "color": "Navy Blue",
            "sizes": ["S", "M", "L", "XL"],
            "image_url": "https://placehold.co/400x400/00008B/FFF?text=Nike+Shirt"
        }
    },
    {
        "sku": "WEAR-SHORTS-001",
        "name": "アディダス ランニングショーツ",
        "description": "軽量で動きやすいランニングショーツ。リフレクター付き。",
        "price": 380000,  # 3,800円
        "inventory_count": 80,
        "metadata": {
            "category": "Running Apparel",
            "brand": "Adidas",
            "color": "Black",
            "sizes": ["S", "M", "L", "XL"],
            "image_url": "https://placehold.co/400x400/000/FFF?text=Adidas+Shorts"
        }
    },
    {
        "sku": "ACC-WATCH-001",
        "name": "ガーミン Forerunner 255",
        "description": "GPS内蔵ランニングウォッチ。心拍計、トレーニング分析機能搭載。",
        "price": 4980000,  # 49,800円
        "inventory_count": 15,
        "metadata": {
            "category": "Running Accessories",
            "brand": "Garmin",
            "color": "Black",
            "features": ["GPS", "Heart Rate Monitor", "Training Analysis", "Music Storage"],
            "image_url": "https://placehold.co/400x400/008/FFF?text=Garmin+255"
        }
    },
    {
        "sku": "ACC-HYDRATION-001",
        "name": "サロモン ハイドレーションパック",
        "description": "500mlボトル2本付き。長距離ランに最適なハイドレーションパック。",
        "price": 980000,  # 9,800円
        "inventory_count": 25,
        "metadata": {
            "category": "Running Accessories",
            "brand": "Salomon",
            "color": "Black/Blue",
            "capacity": "5L",
            "image_url": "https://placehold.co/400x400/00F/FFF?text=Hydration+Pack"
        }
    },
    {
        "sku": "ACC-SOCKS-001",
        "name": "ナイキ エリート ランニングソックス (3足セット)",
        "description": "クッション性とサポート性を兼ね備えたプレミアムソックス。",
        "price": 280000,  # 2,800円
        "inventory_count": 150,
        "metadata": {
            "category": "Running Accessories",
            "brand": "Nike",
            "color": "Assorted",
            "pack_size": 3,
            "sizes": ["M", "L"],
            "image_url": "https://placehold.co/400x400/888/FFF?text=Nike+Socks"
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
