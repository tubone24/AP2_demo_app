"""
LangGraphベースのインテント抽出エージェント

AP2仕様準拠：
- 既存のIntentMandate型（Pydantic）を使用
- ユーザーの自然言語プロンプトから構造化データを抽出
- DMR endpoint（OpenAI互換API）経由でLLMを呼び出し
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

# AP2型定義をインポート
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

from v2.common.mandate_types import IntentMandate
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='langgraph_agent')

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
        logger.info("[Langfuse] Tracing enabled for Shopping Agent")
    except Exception as e:
        logger.warning(f"[Langfuse] Failed to initialize: {e}")
        LANGFUSE_ENABLED = False


class IntentExtractionState(dict):
    """LangGraphのState型定義

    AP2準拠のIntent Mandate抽出に必要な状態を管理
    """
    user_prompt: str  # ユーザーの自然言語入力
    intent_data: Optional[Dict[str, Any]]  # 抽出されたインテントデータ
    error: Optional[str]  # エラーメッセージ


class LangGraphIntentAgent:
    """
    LangGraphベースのIntent抽出エージェント

    役割：
    1. ユーザーの自然言語プロンプトを受け取る
    2. LLMでインテント抽出（商品カテゴリ、価格帯、Merchant制約等）
    3. AP2仕様準拠のIntentMandateデータを生成

    重要：
    - IntentMandate型（mandate_types.py）を絶対に遵守
    - DMR endpoint経由でLLM呼び出し（OpenAI互換API）
    - 署名は行わない（Passkey署名はフロントエンド/別フローで実施）
    """

    def __init__(self):
        # DMR endpoint設定（環境変数から読み込み）
        self.llm_endpoint = os.getenv("DMR_API_URL", "http://llm:12434/engines/llama.cpp/v1")
        self.llm_model = os.getenv("DMR_MODEL", "ai/smollm2")
        self.llm_api_key = os.getenv("DMR_API_KEY", "none")

        # ChatOpenAI初期化（OpenAI互換API）
        self.llm = ChatOpenAI(
            base_url=self.llm_endpoint,
            model=self.llm_model,
            api_key=self.llm_api_key,
            temperature=0.3,  # 決定論的な出力
            max_tokens=512,
        )

        # LangGraphのグラフを構築
        self.graph = self._build_graph()

        logger.info(f"[LangGraphIntentAgent] Initialized with LLM endpoint: {self.llm_endpoint}, model: {self.llm_model}")

    def _build_graph(self) -> CompiledStateGraph:
        """LangGraphのグラフを構築

        フロー：
        1. extract_intent: LLMでインテント抽出
        2. format_intent: IntentMandate形式に変換
        """
        workflow = StateGraph(IntentExtractionState)

        # ノード追加
        workflow.add_node("extract_intent", self._extract_intent_node)
        workflow.add_node("format_intent", self._format_intent_node)

        # エッジ追加
        workflow.set_entry_point("extract_intent")
        workflow.add_edge("extract_intent", "format_intent")
        workflow.add_edge("format_intent", END)

        return workflow.compile()

    def _extract_intent_node(self, state: IntentExtractionState) -> IntentExtractionState:
        """LLMでユーザーインテントを抽出

        Args:
            state: 現在の状態（user_promptを含む）

        Returns:
            更新された状態（intent_dataを含む）
        """
        user_prompt = state.get("user_prompt", "")

        if not user_prompt:
            state["error"] = "user_prompt is empty"
            return state

        # LLMプロンプト構築（JSON形式で出力させる）
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
入力: 「赤いバスケットボールシューズがほしい。3万円以内」
出力:
{
  "natural_language_description": "赤いバスケットボールシューズを3万円以内で購入したい",
  "user_cart_confirmation_required": true,
  "merchants": null,
  "skus": null,
  "requires_refundability": false
}

入力: 「かわいいグッズがほしい。5000円以内」
出力:
{
  "natural_language_description": "かわいいグッズを5000円以内で購入したい",
  "user_cart_confirmation_required": true,
  "merchants": null,
  "skus": null,
  "requires_refundability": false
}

入力: 「時計とステッカーがほしい」
出力:
{
  "natural_language_description": "時計とステッカーを購入したい（予算制約なし）",
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
                config["run_name"] = "extract_intent"
                config["metadata"] = {
                    "user_prompt": user_prompt[:100]  # 最初の100文字
                }

            response = self.llm.invoke(messages, config=config)
            llm_output = response.content.strip()

            logger.info(f"[extract_intent] LLM raw output: {llm_output}")

            # JSON抽出（LLMが余計なテキストを含む場合に対応）
            if "```json" in llm_output:
                llm_output = llm_output.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_output:
                llm_output = llm_output.split("```")[1].split("```")[0].strip()

            intent_data = json.loads(llm_output)
            state["intent_data"] = intent_data

        except json.JSONDecodeError as e:
            logger.error(f"[extract_intent] JSON parse error: {e}, output: {llm_output}")
            state["error"] = f"Failed to parse LLM output as JSON: {e}"
        except Exception as e:
            logger.error(f"[extract_intent] Unexpected error: {e}", exc_info=True)
            state["error"] = f"Intent extraction failed: {e}"

        return state

    def _format_intent_node(self, state: IntentExtractionState) -> IntentExtractionState:
        """IntentMandate形式に変換

        Args:
            state: intent_dataを含む状態

        Returns:
            IntentMandateデータを含む状態
        """
        intent_data = state.get("intent_data")

        if not intent_data or state.get("error"):
            return state

        try:
            # intent_expiryを自動生成（24時間後）
            expiry_time = datetime.now(timezone.utc) + timedelta(hours=24)
            intent_data["intent_expiry"] = expiry_time.isoformat().replace('+00:00', 'Z')

            # IntentMandate型でバリデーション（Pydantic）
            intent_mandate = IntentMandate(**intent_data)

            # dict形式で保存（後続処理でJSONシリアライズ可能に）
            state["intent_data"] = intent_mandate.model_dump()

            logger.info(f"[format_intent] Intent Mandate formatted: {state['intent_data']}")

        except Exception as e:
            logger.error(f"[format_intent] Validation error: {e}", exc_info=True)
            state["error"] = f"Intent Mandate validation failed: {e}"

        return state

    async def extract_intent_from_prompt(self, user_prompt: str) -> Dict[str, Any]:
        """ユーザープロンプトからIntent Mandateデータを抽出

        Args:
            user_prompt: ユーザーの自然言語入力

        Returns:
            IntentMandateデータ（dict形式）
            エラー時は {"error": "エラーメッセージ"}

        Raises:
            ValueError: インテント抽出に失敗した場合
        """
        # Langfuseトレース（v3 APIではCallbackHandlerで自動的に作成される）
        # 手動でのトレース管理は不要

        initial_state: IntentExtractionState = {
            "user_prompt": user_prompt,
            "intent_data": None,
            "error": None,
        }

        # LangGraphグラフ実行（Langfuseハンドラーを渡す）
        config = {}
        if LANGFUSE_ENABLED and langfuse_handler:
            config["callbacks"] = [langfuse_handler]

        final_state = self.graph.invoke(initial_state, config=config)

        if final_state.get("error"):
            error_msg = final_state["error"]
            logger.error(f"[extract_intent_from_prompt] Error: {error_msg}")
            raise ValueError(error_msg)

        intent_data = final_state.get("intent_data")
        if not intent_data:
            error_msg = "Intent extraction returned no data"
            raise ValueError(error_msg)

        # Langfuseトレースを即座に送信
        if LANGFUSE_ENABLED and langfuse_client:
            try:
                langfuse_client.flush()
                logger.debug("[Langfuse] Flushed traces")
            except Exception as e:
                logger.warning(f"[Langfuse] Failed to flush: {e}")

        return intent_data


# シングルトンインスタンス（モジュールレベル）
_langgraph_agent_instance: Optional[LangGraphIntentAgent] = None


def get_langgraph_agent() -> LangGraphIntentAgent:
    """LangGraphIntentAgentのシングルトンインスタンスを取得

    Returns:
        LangGraphIntentAgentインスタンス
    """
    global _langgraph_agent_instance

    if _langgraph_agent_instance is None:
        _langgraph_agent_instance = LangGraphIntentAgent()

    return _langgraph_agent_instance
