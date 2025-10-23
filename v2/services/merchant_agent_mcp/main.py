"""
v2/services/merchant_agent_mcp/main.py

Merchant Agent MCP Server - LangGraphノードをMCPツールとして公開

MCPツール:
- analyze_intent: IntentMandateを解析
- search_products: データベースから商品検索
- check_inventory: 在庫確認
- optimize_cart: LLMによるカート最適化
- build_cart_mandates: AP2準拠CartMandate構築
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
from common.logger import get_logger

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

logger = get_logger(__name__, service_name='merchant_agent_mcp')

# グローバル設定
MERCHANT_ID = os.getenv("MERCHANT_ID", "did:ap2:merchant:mugibo_merchant")
MERCHANT_NAME = os.getenv("MERCHANT_NAME", "Demo Merchant")
MERCHANT_URL = os.getenv("MERCHANT_URL", "http://merchant:8002")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/merchant_agent.db")

# LLM設定
LLM_ENDPOINT = os.getenv("DMR_API_URL", "http://host.docker.internal:12434/engines/llama.cpp/v1")
LLM_MODEL = os.getenv("DMR_MODEL", "ai/qwen3")
LLM_API_KEY = os.getenv("DMR_API_KEY", "none")

# データベース初期化
db_manager = DatabaseManager(DATABASE_URL)

# LLM初期化
llm = ChatOpenAI(
    base_url=LLM_ENDPOINT,
    model=LLM_MODEL,
    api_key=LLM_API_KEY,
    temperature=0.5,
    max_tokens=2048,
    timeout=180.0,
    max_retries=2
)

# MCPサーバー初期化
mcp = MCPServer(
    server_name="merchant_agent_mcp",
    version="1.0.0"
)


@mcp.tool(
    name="analyze_intent",
    description="IntentMandateを解析してユーザーの嗜好と検索キーワードを抽出",
    input_schema={
        "type": "object",
        "properties": {
            "intent_mandate": {
                "type": "object",
                "description": "AP2準拠のIntentMandate",
                "properties": {
                    "natural_language_description": {"type": "string"},
                    "merchants": {"type": "array", "items": {"type": "string"}},
                    "skus": {"type": "array", "items": {"type": "string"}},
                    "requires_refundability": {"type": "boolean"}
                },
                "required": ["natural_language_description"]
            }
        },
        "required": ["intent_mandate"]
    }
)
async def analyze_intent(params: Dict[str, Any]) -> Dict[str, Any]:
    """IntentMandateを解析してユーザー嗜好を抽出（LLM使用）

    Args:
        params: {"intent_mandate": {...}}

    Returns:
        {
            "primary_need": str,
            "budget_strategy": "budget_conscious" | "balanced" | "premium",
            "key_factors": List[str],
            "search_keywords": List[str]
        }
    """
    intent_mandate = params["intent_mandate"]

    # AP2準拠のフィールド抽出
    natural_language_description = intent_mandate.get("natural_language_description", "")
    merchants = intent_mandate.get("merchants", [])
    skus = intent_mandate.get("skus", [])
    requires_refundability = intent_mandate.get("requires_refundability", False)

    # LLMプロンプト
    prompt = f"""以下のIntent Mandateから、ユーザーの具体的なニーズと嗜好を抽出してください。

ユーザーの意図: {natural_language_description}
指定Merchant: {merchants if merchants else "制約なし"}
指定SKU: {skus if skus else "制約なし"}
返金可能性要件: {requires_refundability}

以下をJSON形式で出力してください：
{{
  "primary_need": "主なニーズ（1文で）",
  "budget_strategy": "budget_conscious" | "balanced" | "premium",
  "key_factors": ["重視するポイント1", "重視するポイント2"],
  "search_keywords": ["検索キーワード1", "キーワード2"]
}}
"""

    try:
        messages = [
            SystemMessage(content="あなたは商品専門のアナリストです。ユーザーの購買意図を正確に理解してください。"),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        llm_output = response.content.strip()

        # JSON抽出
        if "```json" in llm_output:
            llm_output = llm_output.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_output:
            llm_output = llm_output.split("```")[1].split("```")[0].strip()

        result = json.loads(llm_output)

        logger.info(f"[analyze_intent] Analyzed: {result}")
        return result

    except Exception as e:
        logger.error(f"[analyze_intent] Error: {e}", exc_info=True)
        # フォールバック
        return {
            "primary_need": natural_language_description,
            "budget_strategy": "balanced",
            "key_factors": [],
            "search_keywords": natural_language_description.split()[:3]
        }


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
    """データベースから商品を検索

    Args:
        params: {"keywords": [...], "limit": 20}

    Returns:
        {"products": [...]}
    """
    keywords = params["keywords"]
    limit = params.get("limit", 20)

    try:
        async with db_manager.get_session() as session:
            # 各キーワードで個別に検索し、結果を統合（重複除去）
            all_products = {}  # product.id -> product

            # キーワードを展開：複合語を分解して個別検索も実施
            expanded_keywords = []
            for keyword in keywords:
                expanded_keywords.append(keyword)
                # 日本語の複合語を分解（例: 「高品質時計」→「時計」）
                # 一般的なパターン: 形容詞+名詞
                if len(keyword) > 2:
                    # 後ろから2文字以上を追加（名詞部分の可能性が高い）
                    expanded_keywords.append(keyword[-2:])
                    if len(keyword) > 3:
                        expanded_keywords.append(keyword[-3:])

            for keyword in expanded_keywords:
                products = await ProductCRUD.search(session, keyword, limit=limit)
                for product in products:
                    if product.id not in all_products:
                        all_products[product.id] = product

            # 在庫がある商品のみに絞り込み
            products_with_stock = [p for p in all_products.values() if p.inventory_count > 0]

            # limit数まで制限
            products_with_stock = products_with_stock[:limit]

            # AP2準拠: 価格をfloat型（円単位）に変換
            products_list = []
            for product in products_with_stock:
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

            logger.info(f"[search_products] Found {len(products_list)} products for keywords: {keywords} (expanded: {expanded_keywords})")
            return {"products": products_list}

    except Exception as e:
        logger.error(f"[search_products] Error: {e}", exc_info=True)
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
    name="optimize_cart",
    description="LLMによるカート最適化（3つのプラン生成）",
    input_schema={
        "type": "object",
        "properties": {
            "products": {
                "type": "array",
                "items": {"type": "object"},
                "description": "検索結果の商品リスト"
            },
            "user_preferences": {
                "type": "object",
                "description": "ユーザーの嗜好（analyze_intentの結果）"
            },
            "max_amount": {
                "type": "number",
                "description": "最大金額（円）"
            }
        },
        "required": ["products", "user_preferences"]
    }
)
async def optimize_cart(params: Dict[str, Any]) -> Dict[str, Any]:
    """LLMによるカート最適化

    Args:
        params: {"products": [...], "user_preferences": {...}, "max_amount": 3000}

    Returns:
        {"cart_plans": [{name, description, items: [{product_id, quantity}]}]}
    """
    products = params["products"]
    user_preferences = params["user_preferences"]
    max_amount = params.get("max_amount")

    if not products:
        return {"cart_plans": []}

    # Rule-basedフィルタリング
    filtered_products = []
    for product in products:
        if max_amount and product["price_jpy"] > max_amount:
            continue
        if product["inventory_count"] <= 0:
            continue
        filtered_products.append(product)

    if not filtered_products:
        return {"cart_plans": []}

    # LLMプロンプト
    prompt = f"""以下の商品リストから、ユーザーのニーズに合った3つのカートプランを提案してください。

ユーザーの嗜好:
- 主なニーズ: {user_preferences.get('primary_need', '')}
- 予算戦略: {user_preferences.get('budget_strategy', 'balanced')}
- 重視ポイント: {user_preferences.get('key_factors', [])}
- 最大金額: {max_amount or '制限なし'}円

利用可能な商品（JSON）:
{json.dumps(filtered_products[:10], ensure_ascii=False, indent=2)}

以下のJSON形式で3つのプランを出力してください:
{{
  "cart_plans": [
    {{
      "name": "プラン名（例: 予算重視プラン）",
      "description": "プランの説明",
      "items": [
        {{"product_id": 1, "quantity": 2}},
        {{"product_id": 3, "quantity": 1}}
      ]
    }}
  ]
}}
"""

    try:
        messages = [
            SystemMessage(content="あなたは優秀なショッピングアシスタントです。ユーザーに最適な商品の組み合わせを提案してください。"),
            HumanMessage(content=prompt)
        ]

        response = await llm.ainvoke(messages)
        llm_output = response.content.strip()

        # JSON抽出
        if "```json" in llm_output:
            llm_output = llm_output.split("```json")[1].split("```")[0].strip()
        elif "```" in llm_output:
            llm_output = llm_output.split("```")[1].split("```")[0].strip()

        result = json.loads(llm_output)

        logger.info(f"[optimize_cart] Generated {len(result.get('cart_plans', []))} plans")
        return result

    except Exception as e:
        logger.error(f"[optimize_cart] Error: {e}", exc_info=True)
        # フォールバック: シンプルな1商品プラン
        return {
            "cart_plans": [
                {
                    "name": "おすすめプラン",
                    "description": "人気商品をセレクトしました",
                    "items": [{"product_id": filtered_products[0]["id"], "quantity": 1}]
                }
            ]
        }


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

    # 税金（10%）
    tax = round(subtotal * 0.1, 2)
    display_items.append({
        "label": "消費税（10%）",
        "amount": {"value": tax, "currency": "JPY"},
        "refund_period": 0
    })

    # 送料
    shipping_fee = 500.0 if subtotal < 5000 else 0.0
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

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8011,  # Merchant Agent MCP専用ポート
        reload=False,
        log_level="info"
    )
