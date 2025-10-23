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

    フロー（全てMCP経由で実行）:
    1. analyze_intent - IntentMandateをLLMで解析
    2. search_products - データベースから商品検索
    3. check_inventory - 在庫確認（MCP経由）
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

        # MCP Client初期化（MCPサーバー経由でLLM処理）
        from v2.common.mcp_client import MCPClient
        mcp_url = os.getenv("MERCHANT_MCP_URL", "http://merchant_agent_mcp:8011")
        self.mcp_client = MCPClient(
            base_url=mcp_url,
            timeout=600.0,  # LLM応答遅延対応: 600秒（10分）タイムアウト
            http_client=http_client
        )
        self.mcp_initialized = False

        # グラフ構築
        self.graph = self._build_graph()

        logger.info(f"[MerchantLangGraphAgent] Initialized with MCP: {mcp_url}")

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
        """IntentMandateを解析してユーザー嗜好を抽出（MCP経由）

        AP2準拠のIntentMandate構造:
        - natural_language_description: ユーザーの意図
        - merchants: 許可されたMerchantリスト（オプション）
        - skus: 特定のSKUリスト（オプション）
        - requires_refundability: 返金可能性要件（オプション）
        """
        # MCP初期化（初回のみ）
        if not self.mcp_initialized:
            try:
                await self.mcp_client.initialize()
                self.mcp_initialized = True
                logger.info("[analyze_intent] MCP client initialized")
            except Exception as e:
                logger.error(f"[analyze_intent] MCP initialization failed: {e}")
                # フォールバック処理
                intent_mandate = state["intent_mandate"]
                natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))
                state["user_preferences"] = {
                    "primary_need": natural_language_description,
                    "budget_strategy": "balanced",
                    "key_factors": [],
                    "search_keywords": natural_language_description.split()[:3]
                }
                return state

        # MCP経由でIntent解析（AP2準拠）
        intent_mandate = state["intent_mandate"]

        try:
            # MCPツール呼び出し
            preferences = await self.mcp_client.call_tool("analyze_intent", {
                "intent_mandate": intent_mandate
            })

            state["user_preferences"] = preferences
            state["llm_reasoning"] = f"Intent分析完了（MCP経由）: {preferences.get('primary_need', '')}"

            logger.info(f"[analyze_intent] MCP result: {preferences}")
        except Exception as e:
            logger.error(f"[analyze_intent] MCP error: {e}")
            # フォールバック（AP2準拠）
            natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))
            state["user_preferences"] = {
                "primary_need": natural_language_description,
                "budget_strategy": "balanced",
                "key_factors": ["品質", "価格"],
                "search_keywords": [natural_language_description] if natural_language_description else []
            }

        return state

    async def _search_products(self, state: MerchantAgentState) -> MerchantAgentState:
        """データベースから商品検索（MCP経由）

        AP2準拠のIntentMandate構造を使用:
        - skus: 特定のSKUリスト（オプション）
        - merchants: 許可されたMerchantリスト（オプション）
        - natural_language_description: 検索に使用
        """
        preferences = state["user_preferences"]

        # キーワード抽出（AP2準拠）
        search_keywords = preferences.get("search_keywords", [])

        try:
            # MCP経由で商品検索
            result = await self.mcp_client.call_tool("search_products", {
                "keywords": search_keywords,
                "limit": 20
            })

            products = result.get("products", [])
            state["available_products"] = products
            logger.info(f"[search_products] MCP returned {len(products)} products")

        except Exception as e:
            logger.error(f"[search_products] MCP error: {e}")
            state["available_products"] = []

        return state

    async def _check_inventory(self, state: MerchantAgentState) -> MerchantAgentState:
        """在庫確認（MCP経由）"""
        products = state["available_products"]

        # 商品IDリスト抽出
        product_ids = [p["id"] for p in products]

        try:
            # MCP経由で在庫確認
            result = await self.mcp_client.call_tool("check_inventory", {
                "product_ids": product_ids
            })

            inventory_status = result.get("inventory", {})
            state["inventory_status"] = inventory_status
            logger.info(f"[check_inventory] MCP checked {len(inventory_status)} products")

        except Exception as e:
            logger.error(f"[check_inventory] MCP error: {e}")
            # フォールバック: 商品データから在庫情報取得
            inventory_status = {}
            for product in products:
                inventory_status[product["id"]] = product.get("stock", 0)
            state["inventory_status"] = inventory_status

        return state

    async def _optimize_cart(self, state: MerchantAgentState) -> MerchantAgentState:
        """LLMによるカート最適化（MCP経由） - 3プラン生成（AP2準拠）

        MCPサーバー経由でLLMに深く思考させユーザーに最適なカートプランを提案
        十分な時間（180秒×2回リトライ）を確保
        """
        preferences = state["user_preferences"]
        products = state["available_products"]

        if not products:
            state["cart_plans"] = []
            logger.warning("[optimize_cart] No products available")
            return state

        # AP2準拠: 予算制限を計算（商品価格帯から推定）
        if products:
            avg_price = sum(p.get("price_jpy", 0) for p in products) / len(products)
            max_amount = avg_price * 3
        else:
            max_amount = None

        try:
            # MCP経由でカート最適化
            result = await self.mcp_client.call_tool("optimize_cart", {
                "products": products,
                "user_preferences": preferences,
                "max_amount": max_amount
            })

            cart_plans = result.get("cart_plans", [])
            state["cart_plans"] = cart_plans
            state["llm_reasoning"] = "Cart optimization completed via MCP"

            logger.info(f"[optimize_cart] MCP generated {len(cart_plans)} cart plans")

        except Exception as e:
            logger.error(f"[optimize_cart] MCP error: {e}")
            # フォールバック: Rule-basedで複数プラン生成（タイムアウト時でもユーザーに選択肢を提供）
            plans = []

            if products:
                # プラン1: 最安値の商品組み合わせ
                sorted_by_price = sorted(products, key=lambda p: p.get("price_jpy", 0))
                total_price = sum(p.get("price_jpy", 0) for p in sorted_by_price[:2])
                plans.append({
                    "name": f"予算内プラン ({int(total_price):,}円)",
                    "description": "最安値の商品を組み合わせました",
                    "items": [{"product_id": p["id"], "quantity": 1} for p in sorted_by_price[:2]]
                })

                # プラン2: 全商品を含むプラン
                total_price = sum(p.get("price_jpy", 0) for p in products)
                budget_diff = ""
                if max_amount and total_price > max_amount:
                    budget_diff = f" (予算+{int(total_price - max_amount):,}円)"
                plans.append({
                    "name": f"全商品プラン ({int(total_price):,}円{budget_diff})",
                    "description": f"検索結果の全{len(products)}商品を含むカート",
                    "items": [{"product_id": p["id"], "quantity": 1} for p in products]
                })

                # プラン3: 最初の1商品のみ
                price = products[0].get("price_jpy", 0)
                plans.append({
                    "name": f"シンプルプラン ({int(price):,}円)",
                    "description": "人気商品1点のみ",
                    "items": [{"product_id": products[0]["id"], "quantity": 1}]
                })

                state["cart_plans"] = plans
                logger.info(f"[optimize_cart] Fallback: Created {len(plans)} rule-based plans")
            else:
                state["cart_plans"] = []

        return state

    async def _build_cart_mandates(self, state: MerchantAgentState) -> MerchantAgentState:
        """AP2準拠のCartMandateを構築（MCP経由でベース作成、Merchant署名は別途）"""
        cart_plans = state["cart_plans"]
        products = state["available_products"]

        cart_candidates = []

        for plan in cart_plans:
            try:
                # MCP経由でCartMandate構築（未署名）
                result = await self.mcp_client.call_tool("build_cart_mandates", {
                    "cart_plan": plan,
                    "products": products,
                    "shipping_address": None  # デフォルト配送先使用
                })

                cart_mandate = result.get("cart_mandate")

                # Merchant署名依頼（HTTPリクエスト）
                response = await self.http_client.post(
                    f"{self.merchant_url}/sign/cart",
                    json={"cart_mandate": cart_mandate},
                    timeout=30.0
                )
                response.raise_for_status()
                signed_cart_response = response.json()

                # AP2準拠：Merchantからのレスポンスから署名済みCartMandateを取り出し
                signed_cart_mandate = signed_cart_response.get("signed_cart_mandate")
                if not signed_cart_mandate:
                    raise ValueError(f"Merchant response missing 'signed_cart_mandate': {signed_cart_response}")

                # Artifact形式でラップ（A2A仕様準拠）
                artifact = {
                    "artifactId": f"artifact_{uuid.uuid4().hex[:8]}",
                    "name": plan.get("name", "カート"),
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "ap2.mandates.CartMandate": signed_cart_mandate
                            }
                        }
                    ]
                }

                cart_candidates.append(artifact)

                logger.info(f"[build_cart_mandates] Built CartMandate for plan: {plan.get('name')}")

            except Exception as e:
                logger.error(f"[build_cart_mandates] Failed for plan {plan.get('name')}: {e}")
                continue

        state["cart_candidates"] = cart_candidates
        logger.info(f"[build_cart_mandates] Built {len(cart_candidates)} CartMandates via MCP")

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

            # AP2準拠: PaymentCurrencyAmount型（value: float、円単位）
            cart_items.append({
                "product_id": product_id,
                "name": product["name"],
                "description": product.get("description", ""),
                "quantity": quantity,
                "unit_price": {
                    "value": unit_price_cents / 100,  # AP2準拠: float型、円単位
                    "currency": "JPY"
                },
                "total_price": {
                    "value": total_price_cents / 100,  # AP2準拠: float型、円単位
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
        # Langfuseトレース（v3 APIではCallbackHandlerで自動的に作成される）
        # 手動でのトレース管理は不要

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

        # MCP統合後：_build_cart_mandatesで既にArtifact形式にラップ済み、Merchant署名済み
        # そのまま返却
        signed_candidates = cart_candidates

        logger.info(f"[create_cart_candidates] {len(signed_candidates)} carts ready (pre-signed via MCP)")

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
