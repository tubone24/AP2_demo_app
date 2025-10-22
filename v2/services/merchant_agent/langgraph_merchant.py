"""
v2/services/merchant_agent/langgraph_merchant.py

Merchant Agent用LangGraphエンジン

役割:
- IntentMandate解析
- 商品検索とフィルタリング
- カート最適化（複数プラン生成）
- AP2準拠CartMandate構築
"""

import os
import json
import uuid
from typing import Dict, Any, List, Optional, TypedDict
from datetime import datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='langgraph_merchant')

# Langfuseトレーシング設定
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
langfuse_handler = None
langfuse_client = None

if LANGFUSE_ENABLED:
    try:
        from langfuse.langchain import CallbackHandler
        from langfuse import Langfuse

        langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
        langfuse_handler = CallbackHandler()
        logger.info("[Langfuse] Tracing enabled")
    except Exception as e:
        logger.warning(f"[Langfuse] Failed to initialize: {e}")
        LANGFUSE_ENABLED = False


class MerchantAgentState(TypedDict):
    """Merchant Agentの状態管理

    入力:
        intent_mandate: IntentMandate（Shopping Agentから受信）
        user_id: ユーザーID
        session_id: セッションID

    中間データ:
        available_products: データベース検索結果
        inventory_status: 在庫状況（現在はDB、将来的にMCP）
        llm_reasoning: LLMの思考過程

    出力:
        cart_candidates: 複数のCartMandate候補（通常3つ）
    """
    # 入力
    intent_mandate: Dict[str, Any]
    user_id: str
    session_id: str

    # 中間データ
    available_products: List[Dict[str, Any]]
    inventory_status: Dict[str, int]
    user_preferences: Dict[str, Any]
    llm_reasoning: str
    cart_plans: List[Dict[str, Any]]

    # 出力
    cart_candidates: List[Dict[str, Any]]


class MerchantLangGraphAgent:
    """Merchant Agent用LangGraphエンジン

    フロー:
    1. analyze_intent - IntentMandateを解析
    2. search_products - データベースから商品検索
    3. check_inventory - 在庫確認（現在はDB、将来的にMCP）
    4. optimize_cart - LLMによるカート最適化（3プラン生成）
    5. build_cart_mandates - AP2準拠CartMandate構築
    6. rank_and_select - トップ3を選択
    """

    def __init__(self, db_manager, merchant_id: str, merchant_name: str, merchant_url: str, http_client):
        """
        Args:
            db_manager: DatabaseManager インスタンス
            merchant_id: Merchant DID
            merchant_name: Merchant名
            merchant_url: MerchantサービスのURL（署名依頼用）
            http_client: httpx.AsyncClient インスタンス
        """
        self.db_manager = db_manager
        self.merchant_id = merchant_id
        self.merchant_name = merchant_name
        self.merchant_url = merchant_url
        self.http_client = http_client

        # LLM初期化（OpenAI互換API）
        self.llm_endpoint = os.getenv("DMR_API_URL", "http://host.docker.internal:12434/engines/llama.cpp/v1")
        self.llm_model = os.getenv("DMR_MODEL", "ai/smollm2")
        self.llm_api_key = os.getenv("DMR_API_KEY", "none")

        self.llm = ChatOpenAI(
            base_url=self.llm_endpoint,
            model=self.llm_model,
            api_key=self.llm_api_key,
            temperature=0.5,
            max_tokens=2048,  # AP2準拠: 詳細な思考のためトークン数増加
            timeout=180.0,  # AP2準拠: LLM深い思考のため180秒（3分）タイムアウト
            max_retries=2  # リトライ実施で安定性向上
        )

        # グラフ構築
        self.graph = self._build_graph()

        logger.info(f"[MerchantLangGraphAgent] Initialized with LLM: {self.llm_endpoint}")

    def _build_graph(self) -> CompiledStateGraph:
        """LangGraphのグラフを構築"""
        workflow = StateGraph(MerchantAgentState)

        # ノード追加
        workflow.add_node("analyze_intent", self._analyze_intent)
        workflow.add_node("search_products", self._search_products)
        workflow.add_node("check_inventory", self._check_inventory)
        workflow.add_node("optimize_cart", self._optimize_cart)
        workflow.add_node("build_cart_mandates", self._build_cart_mandates)
        workflow.add_node("rank_and_select", self._rank_and_select)

        # フロー定義
        workflow.set_entry_point("analyze_intent")
        workflow.add_edge("analyze_intent", "search_products")
        workflow.add_edge("search_products", "check_inventory")
        workflow.add_edge("check_inventory", "optimize_cart")
        workflow.add_edge("optimize_cart", "build_cart_mandates")
        workflow.add_edge("build_cart_mandates", "rank_and_select")
        workflow.add_edge("rank_and_select", END)

        return workflow.compile()

    async def _analyze_intent(self, state: MerchantAgentState) -> MerchantAgentState:
        """IntentMandateを解析してユーザー嗜好を抽出

        AP2準拠のIntentMandate構造:
        - natural_language_description: ユーザーの意図
        - merchants: 許可されたMerchantリスト（オプション）
        - skus: 特定のSKUリスト（オプション）
        - requires_refundability: 返金可能性要件（オプション）
        """
        intent_mandate = state["intent_mandate"]

        # AP2準拠のフィールド抽出
        natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))
        merchants = intent_mandate.get("merchants", [])
        skus = intent_mandate.get("skus", [])
        requires_refundability = intent_mandate.get("requires_refundability", False)

        # LLMでユーザーの嗜好を分析
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

            # Langfuseトレーシング
            config = {}
            if LANGFUSE_ENABLED and langfuse_handler:
                config["callbacks"] = [langfuse_handler]
                config["run_name"] = "analyze_intent"
                config["metadata"] = {
                    "session_id": state.get("session_id"),
                    "user_id": state.get("user_id"),
                    "natural_language_description": natural_language_description[:100]
                }

            response = await self.llm.ainvoke(messages, config=config)

            # JSON抽出
            preferences = self._parse_json_from_llm(response.content)
            state["user_preferences"] = preferences
            state["llm_reasoning"] = f"Intent分析: {response.content}"

            logger.info(f"[analyze_intent] Extracted preferences: {preferences}")
        except Exception as e:
            logger.error(f"[analyze_intent] LLM error: {e}")
            # フォールバック（AP2準拠）
            state["user_preferences"] = {
                "primary_need": natural_language_description,
                "budget_strategy": "balanced",
                "key_factors": ["品質", "価格"],
                "search_keywords": [natural_language_description] if natural_language_description else []
            }

        return state

    async def _search_products(self, state: MerchantAgentState) -> MerchantAgentState:
        """データベースから商品検索

        AP2準拠のIntentMandate構造を使用:
        - skus: 特定のSKUリスト（オプション）
        - merchants: 許可されたMerchantリスト（オプション）
        - natural_language_description: 検索に使用
        """
        intent_mandate = state["intent_mandate"]
        preferences = state["user_preferences"]

        # AP2準拠のフィールド抽出
        skus = intent_mandate.get("skus", [])
        merchants = intent_mandate.get("merchants", [])
        natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))

        # キーワード検索（LLMで抽出したキーワードまたはnatural_language_description）
        search_keywords = preferences.get("search_keywords", [])
        query = " ".join(search_keywords) if search_keywords else natural_language_description

        # ProductCRUDで検索（AP2準拠の静的メソッド使用）
        from v2.common.database import ProductCRUD

        async with self.db_manager.get_session() as session:
            products = await ProductCRUD.search(session, query, limit=20)

        # AP2準拠のフィルタリング
        filtered_products = []
        for product in products:
            # dict形式に変換
            product_dict = {
                "id": product.id,
                "sku": product.sku,
                "name": product.name,
                "description": product.description,
                "price": product.price,
                "inventory_count": product.inventory_count,
                "metadata": json.loads(product.product_metadata) if product.product_metadata else {}
            }

            # SKUフィルタ（AP2準拠）
            if skus and product_dict["sku"] not in skus:
                continue

            # Merchantフィルタ（AP2準拠）
            if merchants and self.merchant_id not in merchants:
                continue

            # 在庫あり
            if product_dict["inventory_count"] > 0:
                filtered_products.append(product_dict)

        state["available_products"] = filtered_products
        logger.info(f"[search_products] Found {len(filtered_products)} products (AP2 compliant)")

        return state

    async def _check_inventory(self, state: MerchantAgentState) -> MerchantAgentState:
        """在庫確認（現在はDBから、将来的にMCP統合）"""
        products = state["available_products"]

        # 在庫状況をDict形式で保存
        inventory_status = {}
        for product in products:
            inventory_status[product["id"]] = product["inventory_count"]

        state["inventory_status"] = inventory_status
        logger.info(f"[check_inventory] Checked {len(inventory_status)} products")

        # 将来的にMCP統合する場合:
        # for product_id in product_ids:
        #     inventory = await self.mcp_client.check_inventory(product_id, self.merchant_id)
        #     inventory_status[product_id] = inventory["available"]

        return state

    async def _optimize_cart(self, state: MerchantAgentState) -> MerchantAgentState:
        """LLMによるカート最適化 - 3プラン生成（AP2準拠）

        LLMで深く思考してユーザーに最適なカートプランを提案
        十分な時間（180秒×3回リトライ）を確保
        """
        intent_mandate = state["intent_mandate"]
        preferences = state["user_preferences"]
        products = state["available_products"]
        inventory = state["inventory_status"]

        if not products:
            state["cart_plans"] = []
            logger.warning("[optimize_cart] No products available")
            return state

        # AP2準拠: 予算制限がないため、商品価格帯から推定
        if products:
            avg_price = sum(p["price"] for p in products) / len(products) / 100
            max_amount = int(avg_price * 3)
        else:
            max_amount = 50000

        # 商品情報を整形（上位10個まで）
        products_summary = []
        for p in products[:10]:
            products_summary.append({
                "id": p["id"],
                "name": p["name"],
                "price": int(p["price"] / 100),
                "description": p.get("description", "")[:100]
            })

        # シンプルなプロンプト（LLMの負荷軽減）
        prompt = f"""ユーザーの要望: {preferences.get("primary_need", "商品を購入したい")}

利用可能な商品（上位10個）:
{json.dumps(products_summary, ensure_ascii=False, indent=2)}

以下の3プランを作成してください:
1. お手頃プラン: 最もコストパフォーマンスが良い商品
2. バランスプラン: 品質と価格のバランスが良い商品
3. 高品質プラン: 最も品質が高い商品

JSON配列で出力してください:
[
  {{"plan_name": "お手頃プラン", "items": [{{"product_id": "商品ID", "quantity": 1}}], "selling_points": ["ポイント1", "ポイント2"]}},
  {{"plan_name": "バランスプラン", "items": [{{"product_id": "商品ID", "quantity": 1}}], "selling_points": ["ポイント1", "ポイント2"]}},
  {{"plan_name": "高品質プラン", "items": [{{"product_id": "商品ID", "quantity": 1}}], "selling_points": ["ポイント1", "ポイント2"]}}
]"""

        try:
            messages = [
                SystemMessage(content="あなたは商品選びのプロフェッショナルです。ユーザーに最適な商品プランを提案してください。"),
                HumanMessage(content=prompt)
            ]

            # Langfuseトレーシング
            config = {}
            if LANGFUSE_ENABLED and langfuse_handler:
                config["callbacks"] = [langfuse_handler]
                config["run_name"] = "optimize_cart"
                config["metadata"] = {
                    "session_id": state.get("session_id"),
                    "user_id": state.get("user_id"),
                    "product_count": len(products)
                }

            logger.info("[optimize_cart] Calling LLM for cart optimization...")
            response = await self.llm.ainvoke(messages, config=config)
            logger.info(f"[optimize_cart] LLM response received: {len(response.content)} chars")

            # JSON配列を抽出
            cart_plans = self._parse_json_from_llm(response.content)

            if not isinstance(cart_plans, list):
                cart_plans = [cart_plans]

            # total_priceを計算
            for plan in cart_plans:
                total = 0
                for item in plan.get("items", []):
                    product_id = item.get("product_id")
                    quantity = item.get("quantity", 1)
                    product = next((p for p in products if p["id"] == product_id), None)
                    if product:
                        total += (product["price"] / 100) * quantity
                plan["total_price"] = total

            state["cart_plans"] = cart_plans
            state["llm_reasoning"] = response.content

            logger.info(f"[optimize_cart] Generated {len(cart_plans)} cart plans via LLM (AP2 compliant)")

        except Exception as e:
            logger.error(f"[optimize_cart] LLM error: {e}")
            # フォールバック: 価格帯別に3プラン生成
            sorted_by_price = sorted(products, key=lambda p: p["price"])
            cart_plans = []

            if len(sorted_by_price) >= 1:
                cart_plans.append({
                    "plan_name": "お手頃プラン",
                    "items": [{"product_id": sorted_by_price[0]["id"], "quantity": 1}],
                    "total_price": sorted_by_price[0]["price"] / 100,
                    "selling_points": ["コストパフォーマンス重視", "在庫あり"]
                })

            if len(sorted_by_price) >= 2:
                mid_idx = len(sorted_by_price) // 2
                cart_plans.append({
                    "plan_name": "バランスプラン",
                    "items": [{"product_id": sorted_by_price[mid_idx]["id"], "quantity": 1}],
                    "total_price": sorted_by_price[mid_idx]["price"] / 100,
                    "selling_points": ["品質と価格のバランス", "在庫あり"]
                })

            if len(sorted_by_price) >= 3:
                cart_plans.append({
                    "plan_name": "高品質プラン",
                    "items": [{"product_id": sorted_by_price[-1]["id"], "quantity": 1}],
                    "total_price": sorted_by_price[-1]["price"] / 100,
                    "selling_points": ["高品質重視", "在庫あり"]
                })

            if not cart_plans:
                cart_plans.append({
                    "plan_name": "デフォルトプラン",
                    "items": [{"product_id": products[0]["id"], "quantity": 1}],
                    "total_price": products[0]["price"] / 100,
                    "selling_points": ["在庫あり"]
                })

            state["cart_plans"] = cart_plans
            logger.info(f"[optimize_cart] Generated {len(cart_plans)} cart plans via fallback (AP2 compliant)")

        return state

    async def _build_cart_mandates(self, state: MerchantAgentState) -> MerchantAgentState:
        """AP2準拠のCartMandateを構築"""
        cart_plans = state["cart_plans"]
        products = state["available_products"]
        user_id = state["user_id"]

        # 商品IDをキーにした辞書
        products_dict = {p["id"]: p for p in products}

        cart_candidates = []

        for plan in cart_plans:
            try:
                cart_mandate = await self._create_single_cart_mandate(
                    plan, products_dict, user_id
                )
                cart_candidates.append({
                    "cart_mandate": cart_mandate,
                    "plan_name": plan.get("plan_name", "カート"),
                    "selling_points": plan.get("selling_points", []),
                    "total_price": cart_mandate["contents"]["payment_request"]["details"]["total"]["amount"]
                })
            except Exception as e:
                logger.error(f"[build_cart_mandates] Failed to build cart for plan {plan.get('plan_name')}: {e}")
                continue

        state["cart_candidates"] = cart_candidates
        logger.info(f"[build_cart_mandates] Built {len(cart_candidates)} CartMandates")

        return state

    async def _create_single_cart_mandate(
        self,
        plan: Dict[str, Any],
        products_dict: Dict[str, Any],
        user_id: str
    ) -> Dict[str, Any]:
        """単一のAP2準拠CartMandateを作成

        AP2仕様完全準拠（既存のagent.py実装と同一構造）:
        - refs/AP2-main/src/ap2/types/mandate.py:107-135
        - refs/AP2-main/src/ap2/types/payment_request.py:184-202
        - PaymentItem: refund_period（商品は30日、税・送料は0）
        - ContactAddress: address_line は配列形式
        - pending, refund_period フィールド必須
        """
        cart_id = f"cart_{uuid.uuid4().hex[:8]}"
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=30)

        # プランから商品アイテムを構築
        items = plan.get("items", [])
        cart_items = []
        subtotal_cents = 0

        for item in items:
            product_id = item["product_id"]
            quantity = item.get("quantity", 1)

            product = products_dict.get(product_id)
            if not product:
                continue

            unit_price_cents = product["price"]
            total_price_cents = unit_price_cents * quantity

            # メタデータ取得
            metadata = product.get("metadata", {})
            if isinstance(metadata, str):
                import json
                try:
                    metadata_dict = json.loads(metadata)
                except:
                    metadata_dict = {}
            else:
                metadata_dict = metadata

            cart_items.append({
                "product_id": product_id,
                "name": product["name"],
                "description": product.get("description", ""),
                "quantity": quantity,
                "unit_price": {
                    "value": str(unit_price_cents),
                    "currency": "JPY"
                },
                "total_price": {
                    "value": str(total_price_cents),
                    "currency": "JPY"
                },
                "image_url": metadata_dict.get("image_url"),
                "sku": product["sku"],
                "category": metadata_dict.get("category"),
                "brand": metadata_dict.get("brand")
            })

            subtotal_cents += total_price_cents

        # 税金計算（10%）
        tax_cents = int(subtotal_cents * 0.1)

        # 送料計算（固定500円）
        shipping_cost_cents = 50000

        # 合計
        total_cents = subtotal_cents + tax_cents + shipping_cost_cents

        # PaymentItem形式でdisplay_itemsを構築（AP2準拠）
        display_items = []

        # 商品アイテム（refund_period = 30日）
        for item in cart_items:
            display_items.append({
                "label": item["name"],
                "amount": {
                    "currency": "JPY",
                    "value": float(item["total_price"]["value"]) / 100
                },
                "pending": False,
                "refund_period": 30  # 30日返金可能期間
            })

        # 送料をdisplay_itemsに追加（refund_period = 0）
        if shipping_cost_cents > 0:
            display_items.append({
                "label": "送料",
                "amount": {
                    "currency": "JPY",
                    "value": float(shipping_cost_cents / 100)
                },
                "pending": False,
                "refund_period": 0
            })

        # 税金をdisplay_itemsに追加（refund_period = 0）
        if tax_cents > 0:
            display_items.append({
                "label": "消費税",
                "amount": {
                    "currency": "JPY",
                    "value": float(tax_cents / 100)
                },
                "pending": False,
                "refund_period": 0
            })

        # デフォルト配送先（ContactAddress形式）
        shipping_address = {
            "recipient_name": "購入者様",
            "organization": "",
            "address_line": ["東京都渋谷区神南1-2-3", "サンプルビル3F"],  # 配列形式（AP2準拠）
            "city": "渋谷区",
            "region": "東京都",
            "postal_code": "150-0041",
            "country": "JP",
            "phone": "03-1234-5678"
        }

        # PaymentRequest.options（AP2準拠）
        payment_options = {
            "request_payer_name": False,
            "request_payer_email": False,
            "request_payer_phone": False,
            "request_shipping": True,
            "shipping_type": "shipping"
        }

        # PaymentRequest.method_data（AP2準拠）
        payment_method_data = [
            {
                "supported_methods": "basic-card",
                "data": {}
            }
        ]

        # PaymentRequest構造（AP2準拠）
        payment_request = {
            "method_data": payment_method_data,
            "details": {
                "id": cart_id,
                "display_items": display_items,
                "total": {
                    "label": "合計",
                    "amount": {
                        "currency": "JPY",
                        "value": float(total_cents / 100)
                    },
                    "pending": False,
                    "refund_period": 30
                },
                "shipping_options": [
                    {
                        "id": "standard",
                        "label": "通常配送（3日程度）",
                        "amount": {
                            "currency": "JPY",
                            "value": float(shipping_cost_cents / 100)
                        },
                        "selected": True
                    }
                ],
                "modifiers": None
            },
            "options": payment_options,
            "shipping_address": shipping_address
        }

        # CartContents構造（AP2準拠）
        cart_contents = {
            "id": cart_id,
            "user_cart_confirmation_required": True,  # Human-Presentフロー
            "payment_request": payment_request,
            "cart_expiry": expires_at.isoformat().replace('+00:00', 'Z'),
            "merchant_name": self.merchant_name
        }

        # CartMandate構造（AP2準拠）
        cart_mandate = {
            "contents": cart_contents,
            "merchant_authorization": None,  # Merchantが署名する
            # 追加メタデータ（AP2仕様外だが、Shopping Agent UIで必要）
            "_metadata": {
                "merchant_id": self.merchant_id,
                "created_at": now.isoformat().replace('+00:00', 'Z'),
                "cart_name": plan.get("plan_name", "カート"),
                "cart_description": ", ".join([f"{i['name']} x {i['quantity']}" for i in cart_items]),
                "raw_items": cart_items,  # 元のアイテム情報（互換性のため保持）
                "user_id": user_id
            }
        }

        return cart_mandate

    async def _rank_and_select(self, state: MerchantAgentState) -> MerchantAgentState:
        """カート候補をランク付けしてトップ3を選択"""
        cart_candidates = state["cart_candidates"]

        # 現在は全て返す（将来的にランキングロジック追加）
        # ランキング基準:
        # - ユーザー嗜好マッチ度
        # - 在庫確実性
        # - 価格競争力

        # トップ3まで
        selected = cart_candidates[:3]
        state["cart_candidates"] = selected

        logger.info(f"[rank_and_select] Selected top {len(selected)} carts")

        return state

    def _parse_json_from_llm(self, text: str) -> Any:
        """LLMの応答からJSON部分を抽出してパース"""
        # ```json ... ``` または ``` ... ``` から抽出
        import re

        # JSONブロックを探す
        json_match = re.search(r'```(?:json)?\s*(\[.*?\]|\{.*?\})\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # ブロックがない場合、全体をJSONとして試す
            json_str = text.strip()

        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"[_parse_json_from_llm] JSON parse error: {e}, text: {json_str[:200]}")
            # フォールバック
            return {}

    async def create_cart_candidates(
        self,
        intent_mandate: Dict[str, Any],
        user_id: str,
        session_id: str
    ) -> List[Dict[str, Any]]:
        """カート候補を生成（エントリーポイント）

        Args:
            intent_mandate: IntentMandate
            user_id: ユーザーID
            session_id: セッションID

        Returns:
            複数のCartMandate候補（通常3つ、署名済み）
        """
        # Langfuseトレース開始（AP2準拠のIntentMandate構造）
        # TODO: Langfuse SDK v3のAPI仕様を確認して修正
        span = None
        if LANGFUSE_ENABLED and langfuse_client:
            try:
                # Context manager形式で使用
                span = langfuse_client.start_as_current_span(
                    name="merchant_agent_cart_generation"
                )
                # __enter__を呼ぶと実際のspanオブジェクトが返される
                actual_span = span.__enter__()
                # user_id/session_idはmetadataに含める
                if hasattr(actual_span, 'update_trace'):
                    actual_span.update_trace(
                        metadata={
                            "user_id": user_id,
                            "session_id": session_id,
                            "natural_language_description": intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))[:100],
                            "merchants": intent_mandate.get("merchants"),
                            "requires_refundability": intent_mandate.get("requires_refundability", False)
                        },
                        input={"intent_mandate_id": intent_mandate.get("id")}
                    )
            except Exception as e:
                logger.warning(f"[Langfuse] Failed to create span: {e}")
                span = None

        # 初期状態
        initial_state: MerchantAgentState = {
            "intent_mandate": intent_mandate,
            "user_id": user_id,
            "session_id": session_id,
            "available_products": [],
            "inventory_status": {},
            "user_preferences": {},
            "llm_reasoning": "",
            "cart_plans": [],
            "cart_candidates": []
        }

        # グラフ実行（未署名のCartMandate候補を生成）
        # Langfuseハンドラーをconfigとして渡す
        config = {}
        if LANGFUSE_ENABLED and langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        result = await self.graph.ainvoke(initial_state, config=config)
        cart_candidates = result["cart_candidates"]

        # AP2仕様準拠：各CartMandateをMerchantサービスに署名依頼し、Artifact形式でラップ
        signed_candidates = []
        for candidate in cart_candidates:
            try:
                cart_mandate = candidate["cart_mandate"]
                signed_cart = await self._request_merchant_signature(cart_mandate)

                # AP2/A2A仕様準拠：Artifact形式でラップ（a2a-extension.md:144-229）
                artifact = {
                    "artifactId": f"artifact_{uuid.uuid4().hex[:8]}",
                    "name": candidate.get("plan_name", "カート"),
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "ap2.mandates.CartMandate": signed_cart
                            }
                        }
                    ]
                }
                signed_candidates.append(artifact)

                logger.info(
                    f"[create_cart_candidates] Cart signed and wrapped: "
                    f"cart_id={signed_cart.get('contents', {}).get('id')}, "
                    f"plan={candidate.get('plan_name')}"
                )

            except Exception as e:
                logger.error(
                    f"[create_cart_candidates] Failed to sign cart {candidate.get('plan_name')}: {e}",
                    exc_info=True
                )
                # 署名失敗したカートは除外
                continue

        logger.info(f"[create_cart_candidates] {len(signed_candidates)}/{len(cart_candidates)} carts signed successfully")

        # Langfuseトレース終了
        if span:
            try:
                span.update_trace(
                    output={
                        "cart_count": len(signed_candidates),
                        "artifact_ids": [c.get("artifactId") for c in signed_candidates],
                        "cart_names": [c.get("name") for c in signed_candidates]
                    }
                )
                span.__exit__(None, None, None)
            except Exception as e:
                logger.warning(f"[Langfuse] Failed to close span: {e}")

        # Langfuseトレースを即座に送信
        if LANGFUSE_ENABLED and langfuse_client:
            try:
                langfuse_client.flush()
                logger.debug("[Langfuse] Flushed traces")
            except Exception as e:
                logger.warning(f"[Langfuse] Failed to flush: {e}")

        return signed_candidates

    async def _request_merchant_signature(self, cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """MerchantサービスにCartMandateの署名を依頼

        Args:
            cart_mandate: 未署名のCartMandate

        Returns:
            署名済みCartMandate（merchant_signature付き）
        """
        try:
            response = await self.http_client.post(
                f"{self.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                raise ValueError(f"Merchant did not return signed cart: {result}")

            return signed_cart_mandate

        except Exception as e:
            logger.error(f"[_request_merchant_signature] Error: {e}", exc_info=True)
            raise
