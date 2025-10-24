"""
v2/services/shopping_agent/langgraph_shopping.py

Shopping Agent用LangGraphエンジン（AP2完全準拠、MCP仕様準拠）

役割:
- ユーザーインテント抽出（LLM直接実行）
- IntentMandate構築（MCPツール）
- Merchant Agentにカート候補依頼（MCPツール）
- カート候補分析・ランク付け（LLM直接実行）
- カート署名（MCPツール）
- リスク評価（MCPツール）
- PaymentMandate構築（MCPツール）
- 決済実行（MCPツール）

アーキテクチャ原則:
- LLM推論: LangGraph内で直接実行（ChatOpenAI使用）
- データアクセス: MCPツールを呼び出し
- MCPサーバーはツールのみを提供、LLM推論は行わない

AP2仕様準拠:
- IntentMandate: natural_language_description（価格制約含む）
- CartMandate: Merchant署名 + User署名
- PaymentMandate: risk_score, fraud_indicators含む
"""

import os
import json
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

logger = get_logger(__name__, service_name='langgraph_shopping')

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


class ShoppingAgentState(TypedDict):
    """Shopping Agentの状態管理

    AP2フロー全体をカバー（AP2仕様準拠）:
    1. IntentMandate作成
    2. Merchant Agentにカート候補依頼
    3. カート候補をユーザーに提示（分析不要）
    4. ユーザーがカート選択
    5. PaymentMandate作成
    6. 決済実行
    """
    # 入力
    user_prompt: str
    session_id: str
    user_id: str
    shipping_address: Optional[Dict[str, Any]]

    # IntentMandateフェーズ
    intent_data: Optional[Dict[str, Any]]
    intent_mandate: Optional[Dict[str, Any]]

    # CartMandateフェーズ（AP2準拠: 分析なしで直接提示）
    cart_candidates: List[Dict[str, Any]]
    selected_cart_index: Optional[int]
    selected_cart: Optional[Dict[str, Any]]
    signed_cart_mandate: Optional[Dict[str, Any]]

    # PaymentMandateフェーズ
    payment_method: Optional[Dict[str, Any]]
    risk_assessment: Optional[Dict[str, Any]]
    payment_mandate: Optional[Dict[str, Any]]

    # 決済結果
    payment_result: Optional[Dict[str, Any]]

    # エラー処理
    error: Optional[str]


class ShoppingLangGraphAgent:
    """Shopping Agent用LangGraphエンジン（AP2完全準拠、MCP仕様準拠）

    アーキテクチャ:
    - LLM: LangGraph内で直接実行（analyze_user_intent, analyze_cart_options）
    - MCP: データアクセスツールのみ（build_intent_mandate, request_cart_candidates等）

    フロー:
    1. analyze_user_intent - ユーザーインテント抽出（LLM直接実行）
    2. build_intent_mandate - IntentMandate構築（MCPツール）
    3. request_cart_candidates - Merchant Agentにカート候補依頼（MCPツール）
    4. analyze_cart_options - カート候補分析・ランク付け（LLM直接実行）
    5. select_and_sign_cart - ユーザーがカート選択し署名（MCPツール）
    6. assess_payment_risk - リスク評価（MCPツール）
    7. build_payment_mandate - PaymentMandate構築（MCPツール）
    8. execute_payment - 決済実行（MCPツール）
    """

    def __init__(self, http_client):
        """
        Args:
            http_client: httpx.AsyncClient インスタンス
        """
        self.http_client = http_client

        # LLM初期化（LangGraph内で直接実行）
        dmr_api_url = os.getenv("DMR_API_URL")
        dmr_model = os.getenv("DMR_MODEL", "ai/qwen3")
        dmr_api_key = os.getenv("DMR_API_KEY", "none")

        if not dmr_api_url:
            logger.warning("[ShoppingLangGraphAgent] DMR_API_URL not set, LLM features disabled")
            self.llm = None
        else:
            self.llm = ChatOpenAI(
                model=dmr_model,
                temperature=0.3,
                openai_api_key=dmr_api_key,
                base_url=dmr_api_url
            )
            logger.info(f"[ShoppingLangGraphAgent] LLM initialized with DMR: {dmr_api_url}, model: {dmr_model}")

        # MCP Client初期化
        from v2.common.mcp_client import MCPClient
        mcp_url = os.getenv("SHOPPING_MCP_URL", "http://shopping_agent_mcp:8010")
        self.mcp_client = MCPClient(
            base_url=mcp_url,
            timeout=600.0,  # 10分タイムアウト（Merchant Agentの処理待ち）
            http_client=http_client
        )
        self.mcp_initialized = False

        # グラフ構築
        self.graph = self._build_graph()

        logger.info(f"[ShoppingLangGraphAgent] Initialized with LLM: {self.llm.model_name if self.llm else 'disabled'}, MCP: {mcp_url}")

    def _build_graph(self) -> CompiledStateGraph:
        """LangGraphのグラフを構築

        AP2仕様準拠:
        - Shopping AgentはIntentMandateを作成
        - Merchant Agentにカート候補を依頼
        - カート候補をユーザーに提示（分析・ランク付けは不要）
        - ユーザーがカートを選択して署名
        """
        workflow = StateGraph(ShoppingAgentState)

        # ノード追加（AP2準拠: カート分析は不要）
        workflow.add_node("analyze_user_intent", self._analyze_user_intent)
        workflow.add_node("build_intent_mandate", self._build_intent_mandate)
        workflow.add_node("request_cart_candidates", self._request_cart_candidates)

        # フロー定義（カート選択以降は別フローで実行）
        workflow.set_entry_point("analyze_user_intent")
        workflow.add_edge("analyze_user_intent", "build_intent_mandate")
        workflow.add_edge("build_intent_mandate", "request_cart_candidates")
        workflow.add_edge("request_cart_candidates", END)

        return workflow.compile()

    async def _analyze_user_intent(self, state: ShoppingAgentState) -> ShoppingAgentState:
        """ユーザーインテント抽出（LLM直接実行）

        ユーザーの自然言語入力から以下を抽出:
        - natural_language_description（価格制約含む）
        - user_cart_confirmation_required
        - merchants（オプション）
        - skus（オプション）
        - requires_refundability（オプション）
        """
        # MCP初期化（初回のみ）
        if not self.mcp_initialized:
            try:
                await self.mcp_client.initialize()
                self.mcp_initialized = True
                logger.info("[analyze_user_intent] MCP client initialized")
            except Exception as e:
                logger.error(f"[analyze_user_intent] MCP initialization failed: {e}")

        user_prompt = state.get("user_prompt", "")

        if not user_prompt:
            state["error"] = "user_prompt is empty"
            return state

        # LLMが無効な場合はエラー
        if not self.llm:
            state["error"] = "LLM not available"
            return state

        # LLMプロンプト構築（価格制約を必ず含める）
        system_prompt = """あなたはAP2（Agent Payments Protocol）準拠のShopping Agentです。
ユーザーの購買意図を抽出し、以下のJSON形式で出力してください。

必須フィールド:
- natural_language_description: ユーザーの意図の自然言語説明（1-2文）
  ★★★最重要★★★: ユーザーが指定した最大金額制約を**必ず**含めてください
  - 「〜を〜円以内で購入したい」のように、金額制約を明示的に記載
  - 金額が指定されていない場合は「予算制約なし」と記載
  - カテゴリー、ブランド、その他すべての制約も含める

- user_cart_confirmation_required: カート確認が必要か（通常はtrue）

オプションフィールド:
- merchants: 許可されたMerchantのリスト（例: ["merchant_demo_001"]）。指定がなければnull
- skus: 特定のSKUリスト（例: ["SKU123"]）。指定がなければnull
- requires_refundability: 返金可能性が必要か（デフォルトfalse）

出力例:
入力: 「かわいいグッズがほしい。5000円以内」
出力:
{
  "natural_language_description": "かわいいグッズを5000円以内で購入したい",
  "user_cart_confirmation_required": true,
  "merchants": null,
  "skus": null,
  "requires_refundability": false
}

JSONのみを出力し、説明文は含めないでください。"""

        try:
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"ユーザーの要望: {user_prompt}")
            ]

            # Langfuseトレーシング
            config = {}
            if LANGFUSE_ENABLED and langfuse_handler:
                config["callbacks"] = [langfuse_handler]
                config["run_name"] = "analyze_user_intent"
                config["metadata"] = {"user_prompt": user_prompt[:100]}

            response = self.llm.invoke(messages, config=config)
            llm_output = response.content.strip()

            logger.info(f"[analyze_user_intent] LLM raw output: {llm_output}")

            # JSON抽出
            if "```json" in llm_output:
                llm_output = llm_output.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_output:
                llm_output = llm_output.split("```")[1].split("```")[0].strip()

            intent_data = json.loads(llm_output)

            # intent_expiry追加（24時間後）
            expiry_time = datetime.now(timezone.utc) + timedelta(hours=24)
            intent_data["intent_expiry"] = expiry_time.isoformat().replace('+00:00', 'Z')

            state["intent_data"] = intent_data
            logger.info(f"[analyze_user_intent] Intent extracted: {intent_data}")

        except json.JSONDecodeError as e:
            logger.error(f"[analyze_user_intent] JSON parse error: {e}, output: {llm_output}")
            state["error"] = f"Failed to parse LLM output as JSON: {e}"
        except Exception as e:
            logger.error(f"[analyze_user_intent] Error: {e}", exc_info=True)
            state["error"] = str(e)

        return state

    async def _build_intent_mandate(self, state: ShoppingAgentState) -> ShoppingAgentState:
        """IntentMandate構築（MCPツール）"""
        intent_data = state.get("intent_data")

        if not intent_data or state.get("error"):
            return state

        try:
            # MCPツール呼び出し
            result = await self.mcp_client.call_tool(
                "build_intent_mandate",
                {
                    "intent_data": intent_data,
                    "session_data": {
                        "user_id": state.get("user_id"),
                        "session_id": state.get("session_id")
                    }
                }
            )

            if "error" in result:
                state["error"] = result["error"]
                logger.error(f"[build_intent_mandate] Error: {result['error']}")
            else:
                state["intent_mandate"] = result["intent_mandate"]
                logger.info(f"[build_intent_mandate] IntentMandate built: {result['intent_mandate']['id']}")

        except Exception as e:
            logger.error(f"[build_intent_mandate] Error: {e}", exc_info=True)
            state["error"] = str(e)

        return state

    async def _request_cart_candidates(self, state: ShoppingAgentState) -> ShoppingAgentState:
        """Merchant Agentにカート候補依頼（MCPツール）"""
        intent_mandate = state.get("intent_mandate")

        if not intent_mandate or state.get("error"):
            return state

        try:
            # MCPツール呼び出し
            result = await self.mcp_client.call_tool(
                "request_cart_candidates",
                {
                    "intent_mandate": intent_mandate,
                    "shipping_address": state.get("shipping_address")
                }
            )

            if "error" in result:
                state["error"] = result["error"]
                logger.error(f"[request_cart_candidates] Error: {result['error']}")
            else:
                state["cart_candidates"] = result["cart_candidates"]
                logger.info(f"[request_cart_candidates] Received {len(result['cart_candidates'])} cart candidates")

        except Exception as e:
            logger.error(f"[request_cart_candidates] Error: {e}", exc_info=True)
            state["error"] = str(e)

        return state

    async def process_intent_to_carts(
        self,
        user_prompt: str,
        session_id: str,
        user_id: str,
        shipping_address: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """ユーザープロンプトからカート候補取得までの処理

        Args:
            user_prompt: ユーザーの自然言語入力
            session_id: セッションID
            user_id: ユーザーID
            shipping_address: 配送先住所

        Returns:
            {
                "intent_mandate": {...},
                "cart_candidates": [...],
                "error": "..." (オプション)
            }
        """
        initial_state: ShoppingAgentState = {
            "user_prompt": user_prompt,
            "session_id": session_id,
            "user_id": user_id,
            "shipping_address": shipping_address,
            "intent_data": None,
            "intent_mandate": None,
            "cart_candidates": [],
            "selected_cart_index": None,
            "selected_cart": None,
            "signed_cart_mandate": None,
            "payment_method": None,
            "risk_assessment": None,
            "payment_mandate": None,
            "payment_result": None,
            "error": None
        }

        # Langfuseトレース
        config = {}
        if LANGFUSE_ENABLED and langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        final_state = await self.graph.ainvoke(initial_state, config=config)

        # Langfuseトレース送信
        if LANGFUSE_ENABLED and langfuse_client:
            try:
                langfuse_client.flush()
            except Exception as e:
                logger.warning(f"[Langfuse] Failed to flush: {e}")

        return {
            "intent_mandate": final_state.get("intent_mandate"),
            "cart_candidates": final_state.get("cart_candidates", []),
            "error": final_state.get("error")
        }

    async def process_payment(
        self,
        cart_mandate: Dict[str, Any],
        intent_mandate: Dict[str, Any],
        payment_method: Dict[str, Any],
        user_signature: Dict[str, Any]
    ) -> Dict[str, Any]:
        """カート選択から決済実行までの処理

        Args:
            cart_mandate: 選択されたCartMandate
            intent_mandate: IntentMandate
            payment_method: 支払い方法
            user_signature: ユーザー署名

        Returns:
            {
                "payment_result": {...},
                "error": "..." (オプション)
            }
        """
        try:
            # 1. カート署名
            sign_result = await self.mcp_client.call_tool(
                "select_and_sign_cart",
                {
                    "cart_mandate": cart_mandate,
                    "user_signature": user_signature
                }
            )

            if "error" in sign_result:
                return {"error": sign_result["error"]}

            signed_cart_mandate = sign_result["signed_cart_mandate"]

            # 2. リスク評価
            risk_result = await self.mcp_client.call_tool(
                "assess_payment_risk",
                {
                    "cart_mandate": signed_cart_mandate,
                    "intent_mandate": intent_mandate,
                    "payment_method": payment_method
                }
            )

            if "error" in risk_result:
                return {"error": risk_result["error"]}

            risk_assessment = risk_result["risk_assessment"]

            # 3. PaymentMandate構築
            mandate_result = await self.mcp_client.call_tool(
                "build_payment_mandate",
                {
                    "cart_mandate": signed_cart_mandate,
                    "payment_method": payment_method,
                    "risk_assessment": risk_assessment
                }
            )

            if "error" in mandate_result:
                return {"error": mandate_result["error"]}

            payment_mandate = mandate_result["payment_mandate"]

            # 4. 決済実行
            payment_result = await self.mcp_client.call_tool(
                "execute_payment",
                {"payment_mandate": payment_mandate}
            )

            if "error" in payment_result:
                return {"error": payment_result["error"]}

            logger.info(f"[process_payment] Payment completed: {payment_result['payment_result'].get('transaction_id')}")

            # Langfuseトレース送信
            if LANGFUSE_ENABLED and langfuse_client:
                try:
                    langfuse_client.flush()
                except Exception as e:
                    logger.warning(f"[Langfuse] Failed to flush: {e}")

            return payment_result

        except Exception as e:
            logger.error(f"[process_payment] Error: {e}", exc_info=True)
            return {"error": str(e)}


# シングルトンインスタンス（モジュールレベル）
_langgraph_shopping_agent_instance: Optional[ShoppingLangGraphAgent] = None


def get_langgraph_shopping_agent(http_client) -> ShoppingLangGraphAgent:
    """ShoppingLangGraphAgentのシングルトンインスタンスを取得

    Args:
        http_client: httpx.AsyncClient インスタンス

    Returns:
        ShoppingLangGraphAgentインスタンス
    """
    global _langgraph_shopping_agent_instance

    if _langgraph_shopping_agent_instance is None:
        _langgraph_shopping_agent_instance = ShoppingLangGraphAgent(http_client)

    return _langgraph_shopping_agent_instance
