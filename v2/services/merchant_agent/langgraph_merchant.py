"""
v2/services/merchant_agent/langgraph_merchant.py

Merchant Agent用LangGraphエンジン（AP2完全準拠、MCP仕様準拠）

役割:
- IntentMandate解析（LLM直接実行）
- 商品検索とフィルタリング（MCPツール）
- カート最適化・複数プラン生成（LLM直接実行）
- AP2準拠CartMandate構築（MCPツール + Merchant署名）

アーキテクチャ原則:
- LLM推論: LangGraph内で直接実行（ChatOpenAI使用）
- データアクセス: MCPツールを呼び出し（search_products, check_inventory, build_cart_mandates）
- MCPサーバーはツールのみを提供、LLM推論は行わない

AP2仕様準拠:
- IntentMandate: natural_language_description, constraints, merchants等
- CartMandate: PaymentRequest, CartContents, merchant_authorization
- 価格: float型、円単位（PaymentCurrencyAmount）
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
from v2.common.telemetry import get_tracer, create_http_span, is_telemetry_enabled

logger = get_logger(__name__, service_name='langgraph_merchant')
tracer = get_tracer(__name__)

# Langfuseトレーシング設定
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
CallbackHandler = None
langfuse_client = None

if LANGFUSE_ENABLED:
    try:
        from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
        from langfuse import Langfuse

        langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
        CallbackHandler = LangfuseCallbackHandler
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
    """Merchant Agent用LangGraphエンジン（AP2完全準拠、MCP仕様準拠）

    アーキテクチャ:
    - LLM: LangGraph内で直接実行（analyze_intent, optimize_cart）
    - MCP: データアクセスツールのみ（search_products, check_inventory, build_cart_mandates）

    フロー:
    1. analyze_intent - IntentMandateをLLMで解析（LLM直接実行）
    2. search_products - データベースから商品検索（MCPツール）
    3. check_inventory - 在庫確認（MCPツール）
    4. optimize_cart - LLMによるカート最適化3プラン生成（LLM直接実行）
    5. build_cart_mandates - AP2準拠CartMandate構築（MCPツール + Merchant署名）
    6. rank_and_select - トップ3を選択

    MCP仕様準拠:
    - MCPサーバーはツールのみを提供（LLM推論なし）
    - LangGraphでLLM推論とツール呼び出しをオーケストレーション

    AP2仕様準拠:
    - IntentMandate: natural_language_description, constraints, merchants等
    - CartMandate: PaymentRequest, CartContents, merchant_authorization
    - 価格: float型、円単位（PaymentCurrencyAmount）
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

        # LLM初期化（LangGraph内で直接実行）
        # DMR (Docker Model Runner) - OpenAI互換APIエンドポイント
        dmr_api_url = os.getenv("DMR_API_URL")
        dmr_model = os.getenv("DMR_MODEL", "ai/qwen3")
        dmr_api_key = os.getenv("DMR_API_KEY", "none")

        if not dmr_api_url:
            logger.warning("[MerchantLangGraphAgent] DMR_API_URL not set, LLM features disabled")
            self.llm = None
        else:
            # ChatOpenAIをDMRエンドポイントに向ける（OpenAI互換API）
            self.llm = ChatOpenAI(
                model=dmr_model,
                temperature=0.7,
                openai_api_key=dmr_api_key,  # DMRは認証不要だが、ChatOpenAIは必須なので"none"を渡す
                base_url=dmr_api_url  # DMRエンドポイント
            )
            logger.info(f"[MerchantLangGraphAgent] LLM initialized with DMR: {dmr_api_url}, model: {dmr_model}")

        # MCP Client初期化（データアクセスツールのみ）
        from v2.common.mcp_client import MCPClient
        mcp_url = os.getenv("MERCHANT_MCP_URL", "http://merchant_agent_mcp:8011")
        self.mcp_client = MCPClient(
            base_url=mcp_url,
            timeout=60.0,  # データアクセスのみ: 60秒タイムアウト
            http_client=http_client
        )
        self.mcp_initialized = False

        # グラフ構築
        self.graph = self._build_graph()

        # Langfuseハンドラー管理（セッションごとにCallbackHandlerインスタンスを保持）
        self._langfuse_handlers: Dict[str, Any] = {}

        logger.info(f"[MerchantLangGraphAgent] Initialized with LLM: {self.llm.model_name if self.llm else 'disabled'}, MCP: {mcp_url}")

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
        """IntentMandateを解析してユーザー嗜好を抽出（LLM直接実行）

        AP2準拠のIntentMandate構造:
        - natural_language_description: ユーザーの意図
        - merchants: 許可されたMerchantリスト（オプション）
        - skus: 特定のSKUリスト（オプション）
        - requires_refundability: 返金可能性要件（オプション）
        """
        # MCP初期化（初回のみ、データアクセスツール用）
        if not self.mcp_initialized:
            try:
                await self.mcp_client.initialize()
                self.mcp_initialized = True
                logger.info("[analyze_intent] MCP client initialized")
            except Exception as e:
                logger.error(f"[analyze_intent] MCP initialization failed: {e}")

        intent_mandate = state["intent_mandate"]
        natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))

        # LLMが無効な場合はフォールバック（AP2準拠）
        if not self.llm:
            # natural_language_descriptionからキーワード抽出
            # 簡易的な形態素解析: カッコや助詞を除去し、名詞的な単語を抽出
            keywords = self._extract_keywords_simple(natural_language_description)

            # 汎用的なキーワード（「グッズ」「商品」「アイテム」等）を追加
            # データベースの商品名に含まれる可能性が高い汎用語を補完
            generic_keywords = []
            desc_lower = natural_language_description.lower()

            # カテゴリヒント
            if any(word in desc_lower for word in ['グッズ', 'ぐっず', '商品', 'アイテム', '製品']):
                generic_keywords.extend(['グッズ', '商品'])
            if any(word in desc_lower for word in ['tシャツ', 'シャツ', '服', '衣類']):
                generic_keywords.extend(['tシャツ', 'シャツ'])
            if any(word in desc_lower for word in ['マグカップ', 'マグ', 'カップ']):
                generic_keywords.append('マグ')

            # 汎用キーワードがあれば優先、なければ空文字列で全商品検索
            if generic_keywords:
                keywords = generic_keywords
            elif not keywords:
                keywords = [""]  # 空文字列で全商品検索

            state["user_preferences"] = {
                "primary_need": natural_language_description,
                "budget_strategy": "balanced",
                "key_factors": ["品質", "価格"],
                "search_keywords": keywords
            }
            state["llm_reasoning"] = f"LLM disabled, using fallback keywords: {keywords}"
            logger.info(f"[analyze_intent] Fallback keywords extracted: {keywords} from '{natural_language_description}'")
            return state

        # LLMプロンプト構築（AP2準拠、日本語商品対応）
        system_prompt = """あなたはMerchant Agentのインテント分析エキスパートです。
ユーザーのIntentMandate（購入意図）を解析し、以下の情報を抽出してください:

1. primary_need: ユーザーの主な要求（1文で簡潔に、日本語）
2. budget_strategy: 予算戦略（"low"=最安値優先、"balanced"=バランス型、"premium"=高品質優先）
3. key_factors: 重視する要素のリスト（例: ["品質", "価格", "ブランド", "デザイン"]）
4. search_keywords: 商品検索用のキーワードリスト（日本語、3-5個、商品名に含まれそうな単語）

**重要**:
- search_keywordsは必ず日本語で返してください（例: ["かわいい", "グッズ", "Tシャツ"]）
- 商品データベースは日本語の商品名（例: "むぎぼーTシャツ", "むぎぼーマグカップ"）なので、日本語キーワードが必須です

必ずJSON形式で返答してください。"""

        user_prompt = f"""以下のIntentMandateを分析してください:

自然言語説明: {natural_language_description}
制約条件: {json.dumps(intent_mandate.get('constraints', {}), ensure_ascii=False)}

JSON形式で返答してください（search_keywordsは必ず日本語）:
{{
  "primary_need": "...",
  "budget_strategy": "low/balanced/premium",
  "key_factors": ["...", "..."],
  "search_keywords": ["...", "...", "..."]
}}"""

        try:
            # LLM呼び出し（コールバックはグラフレベルのconfigから自動的に伝播される）
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            response = await self.llm.ainvoke(messages)
            response_text = response.content

            # JSON抽出
            preferences = self._parse_json_from_llm(response_text)

            # 必須フィールドのバリデーション
            if not preferences.get("search_keywords"):
                preferences["search_keywords"] = [natural_language_description] if natural_language_description else []

            state["user_preferences"] = preferences
            state["llm_reasoning"] = f"Intent分析完了（LLM直接実行）: {preferences.get('primary_need', '')}"

            logger.info(f"[analyze_intent] LLM result: {preferences}")

        except Exception as e:
            logger.error(f"[analyze_intent] LLM error: {e}", exc_info=True)
            # フォールバック（AP2準拠）
            state["user_preferences"] = {
                "primary_need": natural_language_description,
                "budget_strategy": "balanced",
                "key_factors": ["品質", "価格"],
                "search_keywords": [natural_language_description] if natural_language_description else []
            }
            state["llm_reasoning"] = f"LLM error, using fallback: {str(e)}"

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

        # Langfuseトレーシング（MCPツール呼び出し）
        trace_id = state.get("session_id", "unknown")
        span = None  # スパン初期化

        try:
            # Langfuseスパン開始（可観測性向上）
            if LANGFUSE_ENABLED and langfuse_client:
                span = langfuse_client.start_span(
                    name="mcp_search_products",
                    input={"keywords": search_keywords, "limit": 20},
                    metadata={"tool": "search_products", "mcp_server": "merchant_agent_mcp", "session_id": trace_id}
                )

            # MCP経由で商品検索
            result = await self.mcp_client.call_tool("search_products", {
                "keywords": search_keywords,
                "limit": 20
            })

            products = result.get("products", [])
            state["available_products"] = products
            logger.info(f"[search_products] MCP returned {len(products)} products")

            # Langfuseスパン終了（成功時）
            if span:
                span.update(output={"products_count": len(products), "products": products[:5]})  # 最初の5件のみ記録
                span.end()

        except Exception as e:
            logger.error(f"[search_products] MCP error: {e}")
            state["available_products"] = []

            # Langfuseスパン終了（エラー時）
            if span:
                span.update(level="ERROR", status_message=str(e))
                span.end()

        return state

    async def _check_inventory(self, state: MerchantAgentState) -> MerchantAgentState:
        """在庫確認（MCP経由）"""
        products = state["available_products"]

        # 商品IDリスト抽出
        product_ids = [p["id"] for p in products]

        # Langfuseトレーシング（MCPツール呼び出し）
        trace_id = state.get("session_id", "unknown")
        span = None  # スパン初期化

        try:
            # Langfuseスパン開始（可観測性向上）
            if LANGFUSE_ENABLED and langfuse_client:
                span = langfuse_client.start_span(
                    name="mcp_check_inventory",
                    input={"product_ids": product_ids},
                    metadata={"tool": "check_inventory", "mcp_server": "merchant_agent_mcp", "session_id": trace_id}
                )

            # MCP経由で在庫確認
            result = await self.mcp_client.call_tool("check_inventory", {
                "product_ids": product_ids
            })

            inventory_status = result.get("inventory", {})
            state["inventory_status"] = inventory_status
            logger.info(f"[check_inventory] MCP checked {len(inventory_status)} products")

            # Langfuseスパン終了（成功時）
            if span:
                span.update(output={"inventory_status": inventory_status})
                span.end()

        except Exception as e:
            logger.error(f"[check_inventory] MCP error: {e}")
            # フォールバック: 商品データから在庫情報取得
            inventory_status = {}
            for product in products:
                inventory_status[product["id"]] = product.get("stock", 0)
            state["inventory_status"] = inventory_status

            # Langfuseスパン終了（エラー時）
            if span:
                span.update(level="ERROR", status_message=str(e), output={"fallback_inventory": inventory_status})
                span.end()

        return state

    async def _optimize_cart(self, state: MerchantAgentState) -> MerchantAgentState:
        """LLMによるカート最適化（LLM直接実行） - 3プラン生成（AP2準拠）"""
        preferences = state["user_preferences"]
        products = state["available_products"]
        intent_mandate = state["intent_mandate"]

        if not products:
            state["cart_plans"] = []
            logger.warning("[optimize_cart] No products available")
            return state

        # AP2準拠: IntentMandateから予算制限を取得
        constraints = intent_mandate.get("constraints", {})
        max_amount = constraints.get("max_amount", {}).get("value") if constraints.get("max_amount") else None

        # LLMが無効な場合はRule-basedフォールバック
        if not self.llm:
            plans = self._create_rule_based_plans(products, max_amount)
            state["cart_plans"] = plans
            state["llm_reasoning"] = "LLM disabled, using rule-based plans"
            logger.info(f"[optimize_cart] Fallback: Created {len(plans)} rule-based plans")
            return state

        # LLMプロンプト構築（AP2準拠）
        system_prompt = """あなたはMerchant Agentのカート最適化エキスパートです。
ユーザーの購入意図と商品リストから、最適なカートプラン3つを提案してください。

各プランには以下を含めてください:
1. name: プラン名（予算や特徴を含む、例: "予算内プラン (5,000円)"）
2. description: プランの説明（1-2文）
3. items: 商品リスト [{"product_id": 123, "quantity": 1}, ...]

プラン設計のガイドライン:
- プラン1: 予算内で最もコスパが良いプラン
- プラン2: 予算を少し超えても高品質なプラン
- プラン3: シンプルに1-2商品のみのプラン

必ずJSON配列形式で返答してください。"""

        # 商品リストを簡潔に要約（トークン節約）
        products_summary = []
        for p in products[:20]:  # 最大20商品まで
            products_summary.append({
                "id": p["id"],
                "name": p["name"],
                "price_jpy": p["price_jpy"],
                "category": p.get("category", ""),
                "inventory": p.get("inventory_count", 0)
            })

        user_prompt = f"""以下の条件でカートプランを3つ提案してください:

ユーザーの要求: {preferences.get('primary_need', '')}
予算戦略: {preferences.get('budget_strategy', 'balanced')}
重視要素: {', '.join(preferences.get('key_factors', []))}
予算上限: {f"{max_amount:,.0f}円" if max_amount else "指定なし"}

商品リスト（{len(products_summary)}件）:
{json.dumps(products_summary, ensure_ascii=False, indent=2)}

JSON配列形式で返答してください:
[
  {{
    "name": "プラン名（価格含む）",
    "description": "プラン説明",
    "items": [{{"product_id": 123, "quantity": 1}}]
  }},
  ...
]"""

        try:
            # LLM呼び出し（コールバックはグラフレベルのconfigから自動的に伝播される）
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ]
            response = await self.llm.ainvoke(messages)
            response_text = response.content

            # JSON抽出
            cart_plans = self._parse_json_from_llm(response_text)

            # リストでない場合はリストにラップ
            if isinstance(cart_plans, dict):
                cart_plans = [cart_plans]
            elif not isinstance(cart_plans, list):
                raise ValueError(f"Invalid cart_plans format: {type(cart_plans)}")

            # 各プランに価格情報を追加
            for plan in cart_plans:
                total_price = sum(
                    next((p["price_jpy"] for p in products if p["id"] == item["product_id"]), 0) * item.get("quantity", 1)
                    for item in plan.get("items", [])
                )
                # nameに価格が含まれていなければ追加
                if "円" not in plan.get("name", ""):
                    plan["name"] = f"{plan.get('name', 'プラン')} ({int(total_price):,}円)"

            state["cart_plans"] = cart_plans[:3]  # 最大3プラン
            state["llm_reasoning"] = f"Cart optimization completed via LLM: {len(cart_plans)} plans"

            logger.info(f"[optimize_cart] LLM generated {len(cart_plans)} cart plans")

        except Exception as e:
            logger.error(f"[optimize_cart] LLM error: {e}", exc_info=True)
            # フォールバック: Rule-basedで複数プラン生成
            plans = self._create_rule_based_plans(products, max_amount)
            state["cart_plans"] = plans
            state["llm_reasoning"] = f"LLM error, using rule-based fallback: {str(e)}"
            logger.info(f"[optimize_cart] Fallback: Created {len(plans)} rule-based plans")

        return state

    def _create_rule_based_plans(self, products: List[Dict[str, Any]], max_amount: Optional[float]) -> List[Dict[str, Any]]:
        """ルールベースでカートプランを生成（フォールバック用）"""
        plans = []

        if not products:
            return plans

        # プラン1: 最安値の商品組み合わせ
        sorted_by_price = sorted(products, key=lambda p: p.get("price_jpy", 0))
        top_products = sorted_by_price[:2]
        total_price = sum(p.get("price_jpy", 0) for p in top_products)
        plans.append({
            "name": f"予算内プラン ({int(total_price):,}円)",
            "description": "最安値の商品を組み合わせました",
            "items": [{"product_id": p["id"], "quantity": 1} for p in top_products]
        })

        # プラン2: バランス型（中間価格の商品2-3個）
        if len(products) >= 3:
            mid_index = len(products) // 2
            mid_products = products[mid_index:mid_index+2]
            total_price = sum(p.get("price_jpy", 0) for p in mid_products)
            budget_diff = ""
            if max_amount and total_price > max_amount:
                budget_diff = f" (予算+{int(total_price - max_amount):,}円)"
            plans.append({
                "name": f"バランスプラン ({int(total_price):,}円{budget_diff})",
                "description": "品質と価格のバランスを重視",
                "items": [{"product_id": p["id"], "quantity": 1} for p in mid_products]
            })

        # プラン3: シンプルプラン（最初の1商品のみ）
        price = products[0].get("price_jpy", 0)
        plans.append({
            "name": f"シンプルプラン ({int(price):,}円)",
            "description": "人気商品1点のみ",
            "items": [{"product_id": products[0]["id"], "quantity": 1}]
        })

        return plans

    async def _build_cart_mandates(self, state: MerchantAgentState) -> MerchantAgentState:
        """AP2準拠のCartMandateを構築（MCP経由でベース作成、Merchant署名は別途）"""
        cart_plans = state["cart_plans"]
        products = state["available_products"]

        # Langfuseトレーシング（MCPツール呼び出し）
        trace_id = state.get("session_id", "unknown")

        cart_candidates = []

        for plan in cart_plans:
            langfuse_span = None
            try:
                # Langfuseスパン開始（可観測性向上）
                if LANGFUSE_ENABLED and langfuse_client:
                    langfuse_span = langfuse_client.start_span(
                        name="mcp_build_cart_mandates",
                        input={"cart_plan": plan, "products_count": len(products)},
                        metadata={"tool": "build_cart_mandates", "mcp_server": "merchant_agent_mcp", "plan_name": plan.get("name"), "session_id": trace_id}
                    )

                # MCP経由でCartMandate構築（未署名）
                result = await self.mcp_client.call_tool("build_cart_mandates", {
                    "cart_plan": plan,
                    "products": products,
                    "shipping_address": None  # デフォルト配送先使用
                })

                cart_mandate = result.get("cart_mandate")

                # Merchant署名依頼（HTTPリクエスト）
                # OpenTelemetry 手動トレーシング: Merchant通信
                with create_http_span(
                    tracer,
                    "POST",
                    f"{self.merchant_url}/sign/cart",
                    **{
                        "merchant.cart_mandate_id": cart_mandate.get("id"),
                        "merchant.operation": "sign_cart"
                    }
                ) as otel_span:
                    response = await self.http_client.post(
                        f"{self.merchant_url}/sign/cart",
                        json={"cart_mandate": cart_mandate},
                        timeout=30.0
                    )
                    response.raise_for_status()
                    otel_span.set_attribute("http.status_code", response.status_code)
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

                # Langfuseスパン終了（成功時）
                if langfuse_span:
                    langfuse_span.update(output={"artifact_id": artifact["artifactId"], "plan_name": plan.get("name")})
                    langfuse_span.end()

            except Exception as e:
                logger.error(f"[build_cart_mandates] Failed for plan {plan.get('name')}: {e}")

                # Langfuseスパン終了（エラー時）
                if langfuse_span:
                    langfuse_span.update(level="ERROR", status_message=str(e))
                    langfuse_span.end()

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

    def _extract_keywords_simple(self, text: str) -> List[str]:
        """自然言語から検索キーワードを抽出（簡易版）

        LLM無効時のフォールバック用。カッコや助詞を除去し、名詞的な単語を抽出。

        Args:
            text: 自然言語テキスト（例: "かわいいグッズを購入したい（価格・カテゴリ・ブランド等の制約なし）"）

        Returns:
            検索キーワードリスト（例: ["グッズ"]）
        """
        import re

        if not text:
            return []

        # カッコ内を削除
        text = re.sub(r'[（(].*?[）)]', '', text)

        # 助詞・助動詞を除去（日本語の一般的なパターン）
        # 語末の助詞のみ除去（語中の文字を誤削除しないように）
        # 例: 「かわいいグッズを」→「かわいいグッズ」（「か」は残す）
        remove_particles = ['を', 'が', 'に', 'で', 'と', 'から', 'まで', 'の', 'は', 'も', 'や', 'へ', 'より']
        for particle in remove_particles:
            text = text.replace(particle, ' ')

        # 動詞的な語尾を除去（"たい"、"した"、"する"等）
        text = re.sub(r'(したい|した|する|ない|なる|れる|られる|せる|させる)(?=[、。\s]|$)', '', text)

        # 記号・句読点を除去
        text = re.sub(r'[、。！？!?　\s]+', ' ', text)

        # 単語分割（空白区切り）
        words = [w.strip() for w in text.split() if w.strip()]

        # 2文字以上の単語のみ抽出（「を」「が」等の1文字は除外）
        keywords = [w for w in words if len(w) >= 2]

        # 汎用的な単語（「グッズ」「商品」「アイテム」等）を優先
        # データベースに「むぎぼー」商品しかない場合でも、空文字列で全商品検索できるようにする
        if not keywords:
            # キーワードが抽出できない場合は空文字列で全商品検索
            return [""]

        # 重複除去
        keywords = list(dict.fromkeys(keywords))

        return keywords

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
        # Langfuseトレースをセッションごとに統合（shopping_agentと同じトレースに含まれる）
        config = {}
        if LANGFUSE_ENABLED and CallbackHandler:
            # セッションごとにCallbackHandlerインスタンスを取得または作成
            # shopping_agentと同じsession_idを使用することで、同じトレースグループに統合される
            if session_id not in self._langfuse_handlers:
                # 新しいハンドラーを作成（AP2完全準拠: オブザーバビリティ）
                langfuse_handler = CallbackHandler()
                self._langfuse_handlers[session_id] = langfuse_handler
                logger.info(f"[Langfuse] Created new handler for session: {session_id}")
            else:
                langfuse_handler = self._langfuse_handlers[session_id]
                logger.debug(f"[Langfuse] Reusing existing handler for session: {session_id}")

            # Langfuseハンドラーを設定
            config["callbacks"] = [langfuse_handler]
            # session_idをrun_idとして設定（重要：これにより同じトレースIDになる）
            config["run_id"] = session_id
            # metadataでsession_idとuser_idを指定
            config["metadata"] = {
                "langfuse_session_id": session_id,
                "langfuse_user_id": user_id,
                "agent_type": "merchant_agent"
            }
            config["tags"] = ["merchant_agent", "ap2_protocol"]

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
            # OpenTelemetry 手動トレーシング: Merchant通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.merchant_url}/sign/cart",
                **{
                    "merchant.cart_mandate_id": cart_mandate.get("id"),
                    "merchant.operation": "sign_cart"
                }
            ) as otel_span:
                response = await self.http_client.post(
                    f"{self.merchant_url}/sign/cart",
                    json={"cart_mandate": cart_mandate},
                    timeout=10.0
                )
                response.raise_for_status()
                otel_span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                raise ValueError(f"Merchant did not return signed cart: {result}")

            return signed_cart_mandate

        except Exception as e:
            logger.error(f"[_request_merchant_signature] Error: {e}", exc_info=True)
            raise
