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
from v2.services.merchant_agent.nodes import (
    analyze_intent,
    search_products,
    check_inventory,
    optimize_cart,
    build_cart_mandates,
    rank_and_select
)

logger = get_logger(__name__, service_name='langgraph_merchant')
tracer = get_tracer(__name__)

# ========================================
# 定数定義
# ========================================

# CartMandate承認待機設定
MAX_CART_APPROVAL_WAIT_TIME = 270  # 秒（4.5分 - Shopping Agentの300秒タイムアウトより短く設定）
CART_APPROVAL_POLL_INTERVAL = 5    # 秒（ポーリング間隔）

# CartMandate有効期限
CART_MANDATE_EXPIRY_MINUTES = 30   # 分（CartMandateの有効期限）

# AP2ステータス定数
STATUS_PENDING_MERCHANT_SIGNATURE = "pending_merchant_signature"
STATUS_SIGNED = "signed"
STATUS_REJECTED = "rejected"

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

        # ノード追加（インスタンスメソッドとしてラップ）
        workflow.add_node("analyze_intent", self._analyze_intent_node)
        workflow.add_node("search_products", self._search_products_node)
        workflow.add_node("check_inventory", self._check_inventory_node)
        workflow.add_node("optimize_cart", self._optimize_cart_node)
        workflow.add_node("build_cart_mandates", self._build_cart_mandates_node)
        workflow.add_node("rank_and_select", self._rank_and_select_node)

        # フロー定義
        workflow.set_entry_point("analyze_intent")
        workflow.add_edge("analyze_intent", "search_products")
        workflow.add_edge("search_products", "check_inventory")
        workflow.add_edge("check_inventory", "optimize_cart")
        workflow.add_edge("optimize_cart", "build_cart_mandates")
        workflow.add_edge("build_cart_mandates", "rank_and_select")
        workflow.add_edge("rank_and_select", END)

        return workflow.compile()

    # ノードメソッド（agentインスタンスを自動的に渡す）
    async def _analyze_intent_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """Intent解析ノード"""
        return await analyze_intent(self, state)

    async def _search_products_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """商品検索ノード"""
        return await search_products(self, state)

    async def _check_inventory_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """在庫確認ノード"""
        return await check_inventory(self, state)

    async def _optimize_cart_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """カート最適化ノード"""
        return await optimize_cart(self, state)

    async def _build_cart_mandates_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """CartMandate構築ノード"""
        return await build_cart_mandates(self, state)

    async def _rank_and_select_node(self, state: MerchantAgentState) -> MerchantAgentState:
        """ランキングノード"""
        return await rank_and_select(state)


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
