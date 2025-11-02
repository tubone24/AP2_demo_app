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
from common.mcp_server import MCPServer
from common.database import DatabaseManager, ProductCRUD
from common.search_engine import MeilisearchClient
from common.logger import get_logger
from common.telemetry import setup_telemetry, instrument_fastapi_app
from services.merchant_agent_mcp.utils import CartMandateHelpers, ProductHelpers

logger = get_logger(__name__, service_name='merchant_agent_mcp')

# グローバル設定
MERCHANT_ID = os.getenv("MERCHANT_ID", "did:ap2:merchant:mugibo_merchant")
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "むぎぼーショップ")
MERCHANT_URL = os.getenv("MERCHANT_URL", "http://merchant:8002")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/merchant_agent.db")

# AP2準拠設定
SHIPPING_FEE = float(os.getenv("SHIPPING_FEE", "500.0"))  # 送料（円）
FREE_SHIPPING_THRESHOLD = float(os.getenv("FREE_SHIPPING_THRESHOLD", "5000.0"))  # 送料無料の閾値（円）
TAX_RATE = float(os.getenv("TAX_RATE", "0.1"))  # 税率（10%）

# AP2 & W3C Payment Request API完全準拠: サポートする支払い方法
# 環境変数でカスタマイズ可能（デフォルト: AP2プロトコル準拠の支払い方法）
SUPPORTED_PAYMENT_METHODS = json.loads(
    os.getenv("SUPPORTED_PAYMENT_METHODS", json.dumps([
        {
            "supported_methods": "basic-card",  # W3C標準: クレジットカード
            "data": {
                "supportedNetworks": ["visa", "mastercard", "jcb", "amex"],
                "supportedTypes": ["credit", "debit"]
            }
        },
        {
            "supported_methods": "https://a2a-protocol.org/payment-methods/ap2-payment",  # AP2準拠
            "data": {
                "version": "0.2",
                "processor": "did:ap2:agent:payment_processor",
                "supportedMethods": ["credential-based", "attestation-based"]
            }
        }
    ]))
)

# W3C Payment Request API準拠: PaymentOptions設定
PAYMENT_OPTIONS = {
    "request_payer_name": os.getenv("REQUEST_PAYER_NAME", "true").lower() == "true",
    "request_payer_email": os.getenv("REQUEST_PAYER_EMAIL", "true").lower() == "true",
    "request_payer_phone": os.getenv("REQUEST_PAYER_PHONE", "false").lower() == "true",
    "request_shipping": os.getenv("REQUEST_SHIPPING", "true").lower() == "true",
    "shipping_type": os.getenv("SHIPPING_TYPE", "shipping")  # shipping, delivery, pickup
}

# データベース初期化
db_manager = DatabaseManager(DATABASE_URL)

# Meilisearch初期化（全文検索エンジン）
search_client = MeilisearchClient()

# MCPサーバー初期化
mcp = MCPServer(
    server_name="merchant_agent_mcp",
    version="1.0.0"
)

# Helperクラス初期化（AP2 & W3C Payment Request API完全準拠）
cart_mandate_helpers = CartMandateHelpers(
    merchant_id=MERCHANT_ID,
    merchant_name=MERCHANT_NAME,
    merchant_url=MERCHANT_URL,
    shipping_fee=SHIPPING_FEE,
    free_shipping_threshold=FREE_SHIPPING_THRESHOLD,
    tax_rate=TAX_RATE,
    supported_payment_methods=SUPPORTED_PAYMENT_METHODS,  # W3C準拠: 支払い方法
    payment_options=PAYMENT_OPTIONS  # W3C準拠: PaymentOptions
)
product_helpers = ProductHelpers()


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

            # 商品データをマッピング（ヘルパーメソッドに委譲）
            products = []
            for product_id in product_ids:
                product = await ProductCRUD.get_by_id(session, product_id)
                if product:
                    products.append(product)

            products_list = product_helpers.map_products_to_list(products)

            logger.info(f"[search_products] Returned {len(products_list)} products for keywords: {keywords}")
            return {"products": products_list}

    except Exception as e:
        logger.error(f"[search_products] Error: {e}", exc_info=True)
        # エラー時はフォールバック: 全商品を返す
        try:
            async with db_manager.get_session() as session:
                all_products = await ProductCRUD.get_all_with_stock(session, limit=limit)
                # 商品データをマッピング（ヘルパーメソッドに委譲）
                products_list = product_helpers.map_products_to_list(all_products)
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
            },
            "intent_mandate_id": {
                "type": "string",
                "description": "IntentMandate ID（AP2準拠）"
            }
        },
        "required": ["cart_plan", "products"]
    }
)
async def build_cart_mandates(params: Dict[str, Any]) -> Dict[str, Any]:
    """AP2準拠のCartMandateを構築

    Args:
        params: {"cart_plan": {...}, "products": [...], "shipping_address": {...}, "intent_mandate_id": "..."}

    Returns:
        {"cart_mandate": {...}}  # 未署名
    """
    cart_plan = params["cart_plan"]
    products = params["products"]
    shipping_address = params.get("shipping_address")
    intent_mandate_id = params.get("intent_mandate_id")  # AP2準拠: IntentMandate IDを取得

    # 商品IDマッピング
    products_map = {p["id"]: p for p in products}

    # カートアイテム構築（ヘルパーメソッドに委譲）
    display_items, raw_items, subtotal = cart_mandate_helpers.build_cart_items(cart_plan, products_map)

    # 税金計算（ヘルパーメソッドに委譲）
    tax, tax_label = cart_mandate_helpers.calculate_tax(subtotal)
    display_items.append({
        "label": tax_label,
        "amount": {"value": tax, "currency": "JPY"},
        "refund_period": 0
    })

    # 送料計算（ヘルパーメソッドに委譲）
    shipping_fee = cart_mandate_helpers.calculate_shipping_fee(subtotal)
    if shipping_fee > 0:
        display_items.append({
            "label": "送料",
            "amount": {"value": shipping_fee, "currency": "JPY"},
            "refund_period": 0
        })

    total = subtotal + tax + shipping_fee

    # AP2準拠のCartMandate構築（ヘルパーメソッドに委譲）
    session_data = {
        "intent_mandate_id": intent_mandate_id,  # AP2準拠: IntentMandate IDを設定
        "cart_name": cart_plan.get("name", "カート"),
        "cart_description": cart_plan.get("description", "")
    }
    cart_mandate = cart_mandate_helpers.build_cart_mandate_structure(
        display_items, raw_items, total, shipping_address, session_data
    )

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
