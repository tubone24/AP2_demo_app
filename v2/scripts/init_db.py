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

from v2.common.database import DatabaseManager
from v2.common.seed_data import seed_products, seed_users


async def main():
    """データベースを初期化してサンプルデータを投入"""
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

    print("\n🎉 Database initialization complete!")
    print(f"Database location: {db_dir / 'ap2.db'}")


if __name__ == "__main__":
    asyncio.run(main())
