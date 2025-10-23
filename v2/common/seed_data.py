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
        "price": 80000,
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
        "price": 350000,
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
        "price": 150000,
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
        "price": 120000,
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
        "price": 50000,
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
        "price": 280000,
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
        "price": 180000,
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
        "price": 95000,
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
    {
        "sku": "MUGI-PLUSH-001",
        "name": "むぎぼーぬいぐるみ（S）",
        "description": "ふわふわのむぎぼーぬいぐるみ（Sサイズ）。デスクやベッドにぴったり。",
        "price": 220000,
        "inventory_count": 40,
        "metadata": {
            "category": "Plush Toys",
            "brand": "Mugibow Official",
            "color": "Brown/White",
            "size": "高さ15cm",
            "material": "ポリエステル",
            "image_url": "/assets/むぎぼーぬいぐるみS.png"
        }
    },
    {
        "sku": "MUGI-PLUSH-002",
        "name": "むぎぼーぬいぐるみ（L）",
        "description": "抱きしめたくなる大きなむぎぼーぬいぐるみ。リビングに癒しを。",
        "price": 480000,
        "inventory_count": 25,
        "metadata": {
            "category": "Plush Toys",
            "brand": "Mugibow Official",
            "color": "Brown/White",
            "size": "高さ40cm",
            "material": "ポリエステル",
            "image_url": "/assets/むぎぼーぬいぐるみL.png"
        }
    },
    {
        "sku": "MUGI-HAT-001",
        "name": "むぎぼーキャップ",
        "description": "むぎぼーの刺繍が入ったシンプルなキャップ。カジュアルコーデに。",
        "price": 200000,
        "inventory_count": 90,
        "metadata": {
            "category": "Mugibow Apparel",
            "brand": "Mugibow Official",
            "color": "Beige",
            "size": "フリーサイズ",
            "material": "コットン",
            "image_url": "/assets/むぎぼーキャップ.png"
        }
    },
    {
        "sku": "MUGI-CUSHION-001",
        "name": "むぎぼークッション",
        "description": "むぎぼーの顔が大きくプリントされたクッション。ソファのおともにどうぞ。",
        "price": 250000,
        "inventory_count": 45,
        "metadata": {
            "category": "Home Goods",
            "brand": "Mugibow Official",
            "color": "Yellow/White",
            "size": "40cm×40cm",
            "material": "ポリエステル",
            "image_url": "/assets/むぎぼークッション.png"
        }
    },
    {
        "sku": "MUGI-NOTEBOOK-001",
        "name": "むぎぼーノート",
        "description": "表紙にむぎぼーがデザインされたA5ノート。中は方眼タイプ。",
        "price": 70000,
        "inventory_count": 150,
        "metadata": {
            "category": "Stationery",
            "brand": "Mugibow Official",
            "color": "Full Color",
            "size": "A5",
            "pages": 80,
            "image_url": "/assets/むぎぼーノート.png"
        }
    },
    {
        "sku": "MUGI-PEN-001",
        "name": "むぎぼーボールペン",
        "description": "書き心地なめらかなむぎぼーデザインのボールペン。",
        "price": 60000,
        "inventory_count": 200,
        "metadata": {
            "category": "Stationery",
            "brand": "Mugibow Official",
            "color": "Blue Ink",
            "material": "プラスチック",
            "image_url": "/assets/むぎぼーペン.png"
        }
    },
    {
        "sku": "MUGI-BOTTLE-001",
        "name": "むぎぼーウォーターボトル",
        "description": "むぎぼーのロゴ入りステンレスボトル。保温・保冷に優れています。",
        "price": 240000,
        "inventory_count": 55,
        "metadata": {
            "category": "Drinkware",
            "brand": "Mugibow Official",
            "color": "Silver/Yellow",
            "capacity": "500ml",
            "material": "ステンレス",
            "image_url": "/assets/むぎぼーボトル.png"
        }
    },
    {
        "sku": "MUGI-SOCKS-001",
        "name": "むぎぼー靴下",
        "description": "むぎぼーがワンポイントで入ったかわいい靴下。やわらかい履き心地。",
        "price": 85000,
        "inventory_count": 100,
        "metadata": {
            "category": "Mugibow Apparel",
            "brand": "Mugibow Official",
            "color": "Gray/White",
            "size": "22-25cm",
            "material": "コットン/ポリエステル",
            "image_url": "/assets/むぎぼー靴下.png"
        }
    },
    {
        "sku": "MUGI-MOUSEPAD-001",
        "name": "むぎぼーマウスパッド",
        "description": "デスクワークのお供にぴったりなむぎぼー柄のマウスパッド。",
        "price": 90000,
        "inventory_count": 85,
        "metadata": {
            "category": "Office Goods",
            "brand": "Mugibow Official",
            "color": "Blue/White",
            "size": "25cm×20cm",
            "material": "ラバー",
            "image_url": "/assets/むぎぼーマウスパッド.png"
        }
    },
    {
        "sku": "MUGI-PHONECASE-001",
        "name": "むぎぼースマホケース",
        "description": "むぎぼーのイラスト入りスマホケース。iPhone対応サイズ。",
        "price": 180000,
        "inventory_count": 75,
        "metadata": {
            "category": "Phone Accessories",
            "brand": "Mugibow Official",
            "color": "White/Yellow",
            "size": "iPhone 15対応",
            "material": "TPU",
            "image_url": "/assets/むぎぼースマホケース.png"
        }
    },
    # --- ここから新10商品 ---
    {
        "sku": "MUGI-UMBRELLA-001",
        "name": "むぎぼー折りたたみ傘",
        "description": "雨の日もむぎぼーと一緒。軽量で持ち運びやすい折りたたみ傘。",
        "price": 260000,
        "inventory_count": 50,
        "metadata": {
            "category": "Outdoor Goods",
            "brand": "Mugibow Official",
            "color": "Navy/Yellow",
            "size": "直径90cm",
            "material": "ポリエステル",
            "image_url": "/assets/むぎぼー傘.png"
        }
    },
    {
        "sku": "MUGI-ECOBAG-001",
        "name": "むぎぼーエコバッグ",
        "description": "小さくたためるむぎぼーのエコバッグ。毎日のお買い物に便利。",
        "price": 120000,
        "inventory_count": 110,
        "metadata": {
            "category": "Mugibow Bags",
            "brand": "Mugibow Official",
            "color": "Light Green",
            "size": "縦40cm×横35cm",
            "material": "リサイクルナイロン",
            "image_url": "/assets/むぎぼーエコバッグ.png"
        }
    },
    {
        "sku": "MUGI-BLANKET-001",
        "name": "むぎぼーブランケット",
        "description": "ふんわりやわらかいむぎぼーブランケット。冬にぴったり。",
        "price": 320000,
        "inventory_count": 40,
        "metadata": {
            "category": "Home Goods",
            "brand": "Mugibow Official",
            "color": "Beige/Brown",
            "size": "100cm×150cm",
            "material": "フリース",
            "image_url": "/assets/むぎぼーブランケット.png"
        }
    },
    {
        "sku": "MUGI-PLATE-001",
        "name": "むぎぼープレート皿",
        "description": "むぎぼーが中央に描かれた陶器プレート。食卓をかわいく演出。",
        "price": 190000,
        "inventory_count": 70,
        "metadata": {
            "category": "Tableware",
            "brand": "Mugibow Official",
            "color": "White/Yellow",
            "size": "直径20cm",
            "material": "陶器",
            "image_url": "/assets/むぎぼープレート.png"
        }
    },
    {
        "sku": "MUGI-HOODIE-001",
        "name": "むぎぼーパーカー",
        "description": "むぎぼーの顔が大きくプリントされたあったかパーカー。",
        "price": 450000,
        "inventory_count": 35,
        "metadata": {
            "category": "Mugibow Apparel",
            "brand": "Mugibow Official",
            "color": "Gray",
            "sizes": ["M", "L", "XL"],
            "material": "コットン/ポリエステル",
            "image_url": "/assets/むぎぼーパーカー.png"
        }
    },
    {
        "sku": "MUGI-TOWEL-001",
        "name": "むぎぼーフェイスタオル",
        "description": "むぎぼー柄のフェイスタオル。吸水性抜群でやわらかい肌触り。",
        "price": 130000,
        "inventory_count": 90,
        "metadata": {
            "category": "Bath Goods",
            "brand": "Mugibow Official",
            "color": "White/Yellow",
            "size": "80cm×34cm",
            "material": "コットン",
            "image_url": "/assets/むぎぼータオル.png"
        }
    },
    {
        "sku": "MUGI-CANDLE-001",
        "name": "むぎぼーアロマキャンドル",
        "description": "むぎぼーをイメージしたやさしい香りのアロマキャンドル。",
        "price": 210000,
        "inventory_count": 60,
        "metadata": {
            "category": "Home Fragrance",
            "brand": "Mugibow Official",
            "color": "White",
            "scent": "Vanilla",
            "burn_time": "約30時間",
            "material": "ソイワックス",
            "image_url": "/assets/むぎぼーキャンドル.png"
        }
    },
    {
        "sku": "MUGI-PILLOW-001",
        "name": "むぎぼー抱き枕",
        "description": "むぎぼーの全身デザイン抱き枕。寝るときもむぎぼーと一緒！",
        "price": 550000,
        "inventory_count": 20,
        "metadata": {
            "category": "Home Goods",
            "brand": "Mugibow Official",
            "color": "Brown/White",
            "size": "長さ100cm",
            "material": "ポリエステル/綿",
            "image_url": "/assets/むぎぼー抱き枕.png"
        }
    },
    {
        "sku": "MUGI-POSTER-001",
        "name": "むぎぼーポスター",
        "description": "お部屋を明るくするむぎぼーのアートポスター。",
        "price": 90000,
        "inventory_count": 100,
        "metadata": {
            "category": "Posters",
            "brand": "Mugibow Official",
            "color": "Full Color",
            "size": "A3",
            "material": "光沢紙",
            "image_url": "/assets/むぎぼーポスター.png"
        }
    },
    {
        "sku": "MUGI-CAP-002",
        "name": "むぎぼーニット帽",
        "description": "冬にぴったりなむぎぼーの刺繍入りニット帽。",
        "price": 180000,
        "inventory_count": 50,
        "metadata": {
            "category": "Mugibow Apparel",
            "brand": "Mugibow Official",
            "color": "Navy",
            "size": "フリーサイズ",
            "material": "アクリル",
            "image_url": "/assets/むぎぼーニット帽.png"
        }
    }
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
