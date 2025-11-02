#!/usr/bin/env python3
"""
v2/scripts/init_seeds.py

AP2デモアプリのシードデータ投入スクリプト

このスクリプトは、各データベースに初期データを投入します。
init_keysと同様に、起動時に1回実行され、データがあればスキップします。

投入データ：
1. merchant_agent.db: 商品データ（SAMPLE_PRODUCTS）
2. credential_provider.db: 支払い方法（Visa, Amex with STEP_UP）
3. credential_provider_2.db: 支払い方法（JCB）
4. shopping_agent.db: ユーザーデータ（必要に応じて）

使用方法：
    python v2/scripts/init_seeds.py

必須環境変数：
    なし（DATABASE_URLは各処理で直接指定）
"""

import os
import sys
import asyncio
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List

# プロジェクトルートをパスに追加
project_root = Path(__file__).parent.parent.parent
# データディレクトリ（Docker Volumeマウント想定）
DATA_DIR = Path("/app/v2/data")

# サンプル商品データをインポート（common/seed_data.pyから）
try:
    from common.seed_data import SAMPLE_PRODUCTS
except ImportError:
    # フォールバック: 最小限の商品データ
    SAMPLE_PRODUCTS = []

# AP2完全準拠の設計：
# - ユーザー登録: Passkeyを登録したときに自動作成される（フロントエンド）
# - 支払い方法: Passkey登録後、ユーザー自身が登録する（セキュリティ要件）
# - 商品データ: Merchantが管理するので、シードデータで投入可能
#
# したがって、ユーザーデータと支払い方法のシードデータ投入は不要


class SeedInitializer:
    """シードデータ投入クラス"""

    def __init__(self):
        """初期化"""
        # ディレクトリ作成
        DATA_DIR.mkdir(parents=True, exist_ok=True)

    async def seed_products(self, db_url: str):
        """
        商品データを投入（merchant_agent.db）

        Args:
            db_url: データベースURL
        """
        from common.database import DatabaseManager, ProductCRUD

        print("\n[商品データ投入]")
        print(f"データベース: {db_url}")

        db_manager = DatabaseManager(database_url=db_url)
        await db_manager.init_db()

        async with db_manager.get_session() as session:
            # 既存データチェック（1件でもあればスキップ）
            from sqlalchemy import select, func
            from common.database import Product

            count_stmt = select(func.count()).select_from(Product)
            result = await session.execute(count_stmt)
            existing_count = result.scalar()

            if existing_count > 0:
                print(f"  ℹ️  既存の商品データが見つかりました（{existing_count}件、スキップ）")
                return

            # データ投入
            for product_data in SAMPLE_PRODUCTS:
                product = await ProductCRUD.create(session, product_data)
                print(f"  ✅ 作成: {product.name} (¥{product.price / 100:.0f})")

        print(f"  ✅ 商品データ投入完了 ({len(SAMPLE_PRODUCTS)}件)")

    async def run(self):
        """商品データのみ投入（AP2完全準拠）"""
        print("="*80)
        print("AP2 シードデータ投入 (AP2完全準拠)")
        print("="*80)
        print(f"\nデータ保存先: {DATA_DIR}")
        print("\nAP2完全準拠のため、以下のデータのみ投入します：")
        print("  ✅ 商品データ: Merchantが管理")
        print("  ⚠️  ユーザーデータ: Passkey登録時に自動作成（フロントエンド）")
        print("  ⚠️  支払い方法: Passkey登録後、ユーザーが登録（セキュリティ要件）")

        try:
            # 1. 商品データ投入（merchant_agent.db）
            await self.seed_products("sqlite+aiosqlite:////app/v2/data/merchant_agent.db")

        except Exception as e:
            print(f"\n❌ エラー: シードデータ投入に失敗しました")
            print(f"   {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        print("\n" + "="*80)
        print("✅ 商品データの投入が完了しました (AP2完全準拠)")
        print("="*80)
        print("\n投入データサマリ:")
        print(f"  - 商品: {len(SAMPLE_PRODUCTS)}件 (merchant_agent.db)")
        print("\n次のステップ:")
        print("  1. フロントエンド (http://localhost:3000) にアクセス")
        print("  2. ユーザー登録 (/auth/register)")
        print("  3. Passkey登録 (/auth/register-passkey)")
        print("  4. 支払い方法登録（Passkey登録後に自動表示）")
        print()


if __name__ == "__main__":
    initializer = SeedInitializer()
    asyncio.run(initializer.run())
