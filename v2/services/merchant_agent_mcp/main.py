"""
v2/services/merchant_agent_mcp/main.py

Merchant Agent MCP Server - データアクセスツール提供（AP2準拠）

MCP仕様準拠：
- MCPサーバーは「ツール」のみを提供（LLM推論なし）
- LangGraph側でLLMを使った推論とツール呼び出しをオーケストレーション

提供ツール（データアクセス専用）:
- search_products: データベースから商品検索
- check_inventory: 在庫確認
- get_product_details: 商品詳細取得
- build_cart_mandate: AP2準拠CartMandate構築（データ構造化のみ）
"""

import os
import sys
import json
import uuid
import uvicorn
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone, timedelta

# パス設定
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from common.mcp_server import MCPServer
from common.database import DatabaseManager, ProductCRUD
from common.search_engine import MeilisearchClient
from common.logger import get_logger
from common.telemetry import setup_telemetry, instrument_fastapi_app

logger = get_logger(__name__, service_name='merchant_agent_mcp')

# グローバル設定
MERCHANT_ID = os.getenv("MERCHANT_ID", "did:ap2:merchant:mugibo_merchant")
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "Demo Merchant")
MERCHANT_URL = os.getenv("MERCHANT_URL", "http://merchant:8002")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/merchant_agent.db")

# AP2準拠設定
SHIPPING_FEE = float(os.getenv("SHIPPING_FEE", "500.0"))  # 送料（円）
FREE_SHIPPING_THRESHOLD = float(os.getenv("FREE_SHIPPING_THRESHOLD", "5000.0"))  # 送料無料の閾値（円）
TAX_RATE = float(os.getenv("TAX_RATE", "0.1"))  # 税率（10%）

# データベース初期化
db_manager = DatabaseManager(DATABASE_URL)

# Meilisearch初期化（全文検索エンジン）
search_client = MeilisearchClient()

# MCPサーバー初期化
mcp = MCPServer(
    server_name="merchant_agent_mcp",
    version="1.0.0"
)


@mcp.tool(
    name="search_products",
    description="データベースから商品を検索",
    input_schema={
        "type": "object",
        "properties": {
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "検索キーワードリスト"
            },
            "limit": {
                "type": "integer",
                "description": "最大検索結果数",
                "default": 20
            }
        },
        "required": ["keywords"]
    }
)
async def search_products(params: Dict[str, Any]) -> Dict[str, Any]:
    """Meilisearch全文検索で商品を検索（AP2準拠、MCP仕様準拠）

    アーキテクチャ:
    1. Meilisearchで全文検索（商品名、説明、キーワード、カテゴリ、ブランド）
    2. 商品IDリストを取得
    3. Product DBから詳細情報を取得（価格、在庫、メタデータ）

    Args:
        params: {"keywords": [...], "limit": 20}

    Returns:
        {"products": [...]}

    注意:
    - keywords が空配列 or [""] の場合: 全商品を返す
    - keywords が複数の場合: スペース区切りで結合してMeilisearchに渡す（OR検索）
    """
    keywords = params["keywords"]
    limit = params.get("limit", 20)

    try:
        # キーワードを結合して検索クエリ作成
        if not keywords or (len(keywords) == 1 and keywords[0] == ""):
            # 空キーワード: 全商品取得
            query = ""
            logger.info("[search_products] Empty keywords, fetching all products via Meilisearch")
        else:
            # キーワード結合（例: ["かわいい", "グッズ"] → "かわいい グッズ"）
            query = " ".join(keywords)
            logger.info(f"[search_products] Searching with query: '{query}'")

        # Step 1: Meilisearchで全文検索
        product_ids = await search_client.search(query, limit=limit)

        # Step 2: Product DBから詳細情報取得
        async with db_manager.get_session() as session:
            products_list = []

            if not product_ids:
                logger.warning(f"[search_products] No products found in Meilisearch for query: '{query}'")
                # フォールバック: 全商品を返す（ユーザー体験向上）
                all_products = await ProductCRUD.get_all_with_stock(session, limit=limit)
                product_ids = [p.id for p in all_products]
                logger.info(f"[search_products] Fallback to all products: {len(product_ids)} products")

            for product_id in product_ids:
                product = await ProductCRUD.get_by_id(session, product_id)

                if not product or product.inventory_count <= 0:
                    # 在庫なしはスキップ
                    continue

                # metadataがSQLAlchemyのMetaDataオブジェクトの場合は空辞書に
                if hasattr(product.metadata, '__class__') and product.metadata.__class__.__name__ == 'MetaData':
                    metadata = {}
                else:
                    metadata = product.metadata or {}

                products_list.append({
                    "id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "description": product.description,
                    "price_cents": product.price,  # データベースはcents単位
                    "price_jpy": product.price / 100.0,  # AP2準拠: float, 円単位
                    "inventory_count": product.inventory_count,
                    "category": metadata.get("category"),
                    "brand": metadata.get("brand"),
                    "image_url": metadata.get("image_url"),
                    "refund_period_days": metadata.get("refund_period_days", 30)
                })

            logger.info(f"[search_products] Returned {len(products_list)} products for keywords: {keywords}")
            return {"products": products_list}

    except Exception as e:
        logger.error(f"[search_products] Error: {e}", exc_info=True)
        # エラー時はフォールバック: 全商品を返す
        try:
            async with db_manager.get_session() as session:
                all_products = await ProductCRUD.get_all_with_stock(session, limit=limit)
                products_list = []
                for product in all_products:
                    if hasattr(product.metadata, '__class__') and product.metadata.__class__.__name__ == 'MetaData':
                        metadata = {}
                    else:
                        metadata = product.metadata or {}

                    products_list.append({
                        "id": product.id,
                        "sku": product.sku,
                        "name": product.name,
                        "description": product.description,
                        "price_cents": product.price,
                        "price_jpy": product.price / 100.0,
                        "inventory_count": product.inventory_count,
                        "category": metadata.get("category"),
                        "brand": metadata.get("brand"),
                        "image_url": metadata.get("image_url"),
                        "refund_period_days": metadata.get("refund_period_days", 30)
                    })
                logger.info(f"[search_products] Fallback returned {len(products_list)} products")
                return {"products": products_list}
        except Exception as fallback_error:
            logger.error(f"[search_products] Fallback also failed: {fallback_error}", exc_info=True)
            return {"products": []}


@mcp.tool(
    name="check_inventory",
    description="在庫状況を確認",
    input_schema={
        "type": "object",
        "properties": {
            "product_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "商品IDリスト"
            }
        },
        "required": ["product_ids"]
    }
)
async def check_inventory(params: Dict[str, Any]) -> Dict[str, Any]:
    """在庫状況を確認

    Args:
        params: {"product_ids": [1, 2, 3]}

    Returns:
        {"inventory": {1: 10, 2: 5, 3: 0}}
    """
    product_ids = params["product_ids"]

    try:
        async with db_manager.get_session() as session:
            inventory = {}
            for product_id in product_ids:
                product = await ProductCRUD.get_by_id(session, product_id)
                if product:
                    inventory[product_id] = product.inventory_count
                else:
                    inventory[product_id] = 0

            logger.info(f"[check_inventory] Inventory: {inventory}")
            return {"inventory": inventory}

    except Exception as e:
        logger.error(f"[check_inventory] Error: {e}", exc_info=True)
        return {"inventory": {pid: 0 for pid in product_ids}}


@mcp.tool(
    name="build_cart_mandates",
    description="AP2準拠のCartMandateを構築（未署名）",
    input_schema={
        "type": "object",
        "properties": {
            "cart_plan": {
                "type": "object",
                "description": "カートプラン（optimize_cartの結果）"
            },
            "products": {
                "type": "array",
                "items": {"type": "object"},
                "description": "商品情報リスト"
            },
            "shipping_address": {
                "type": "object",
                "description": "AP2準拠のContactAddress"
            }
        },
        "required": ["cart_plan", "products"]
    }
)
async def build_cart_mandates(params: Dict[str, Any]) -> Dict[str, Any]:
    """AP2準拠のCartMandateを構築

    Args:
        params: {"cart_plan": {...}, "products": [...], "shipping_address": {...}}

    Returns:
        {"cart_mandate": {...}}  # 未署名
    """
    cart_plan = params["cart_plan"]
    products = params["products"]
    shipping_address = params.get("shipping_address")

    # 商品IDマッピング
    products_map = {p["id"]: p for p in products}

    # カートアイテム構築
    display_items = []
    raw_items = []
    subtotal = 0.0

    for item in cart_plan.get("items", []):
        product_id = item["product_id"]
        quantity = item["quantity"]

        if product_id not in products_map:
            continue

        product = products_map[product_id]
        unit_price_jpy = product["price_jpy"]
        total_price_jpy = unit_price_jpy * quantity

        # AP2準拠: PaymentItem
        display_items.append({
            "label": product["name"],
            "amount": {
                "value": total_price_jpy,  # AP2準拠: float, 円単位
                "currency": "JPY"
            },
            "refund_period": product.get("refund_period_days", 30) * 86400  # 秒単位
        })

        # メタデータ（raw_items）
        raw_items.append({
            "product_id": product_id,
            "name": product["name"],
            "description": product.get("description"),
            "quantity": quantity,
            "unit_price": {"value": unit_price_jpy, "currency": "JPY"},
            "total_price": {"value": total_price_jpy, "currency": "JPY"},
            "image_url": product.get("image_url")
        })

        subtotal += total_price_jpy

    # 税金（AP2準拠：環境変数から税率取得）
    tax = round(subtotal * TAX_RATE, 2)
    tax_label = f"消費税（{int(TAX_RATE * 100)}%）"
    display_items.append({
        "label": tax_label,
        "amount": {"value": tax, "currency": "JPY"},
        "refund_period": 0
    })

    # 送料（AP2準拠：環境変数から取得）
    shipping_fee = SHIPPING_FEE if subtotal < FREE_SHIPPING_THRESHOLD else 0.0
    if shipping_fee > 0:
        display_items.append({
            "label": "送料",
            "amount": {"value": shipping_fee, "currency": "JPY"},
            "refund_period": 0
        })

    total = subtotal + tax + shipping_fee

    # AP2準拠のCartMandate構築
    cart_id = f"cart_{uuid.uuid4().hex[:8]}"
    cart_expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat().replace('+00:00', 'Z')

    cart_mandate = {
        "contents": {
            "id": cart_id,
            "user_cart_confirmation_required": True,
            "payment_request": {
                "method_data": [],
                "details": {
                    "id": cart_id,
                    "display_items": display_items,
                    "total": {
                        "label": "合計",
                        "amount": {"value": total, "currency": "JPY"}
                    }
                },
                "shipping_address": shipping_address
            },
            "cart_expiry": cart_expiry,
            "merchant_name": MERCHANT_NAME
        },
        "merchant_authorization": None,  # 未署名
        "_metadata": {
            "intent_mandate_id": params.get("_session_data", {}).get("intent_mandate_id"),
            "merchant_id": MERCHANT_ID,
            "created_at": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "cart_name": cart_plan.get("name", "カート"),
            "cart_description": cart_plan.get("description", ""),
            "raw_items": raw_items
        }
    }

    logger.info(f"[build_cart_mandates] Built CartMandate: {cart_id}")
    return {"cart_mandate": cart_mandate}


# FastAPIアプリ
app = mcp.app

# OpenTelemetryセットアップ（Jaegerトレーシング）
service_name = os.getenv("OTEL_SERVICE_NAME", "merchant_agent_mcp")
setup_telemetry(service_name)

# FastAPI計装（AP2完全準拠：MCP通信の可視化）
instrument_fastapi_app(app)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8011,  # Merchant Agent MCP専用ポート
        reload=False,
        log_level="info"
    )
