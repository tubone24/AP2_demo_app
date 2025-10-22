# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
LangGraphベースの対話フローエージェント

AP2仕様準拠：
- ユーザーとの対話でIntent Mandate必要情報を段階的に抽出
- 必須: インテント、最大金額
- オプション: カテゴリー、ブランド
- すべて揃ったらIntent Mandate生成
"""

import os
import json
import re
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.state import CompiledStateGraph

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='langgraph_conversation')


class ConversationState(dict):
    """対話状態管理

    必須フィールド:
    - intent: 購買意図（必須）
    - max_amount: 最大金額（必須）

    オプションフィールド:
    - categories: カテゴリーリスト
    - brands: ブランドリスト

    内部管理:
    - conversation_history: 対話履歴
    - missing_fields: 不足フィールドリスト
    - agent_response: エージェントの応答
    """
    user_input: str
    intent: Optional[str]
    max_amount: Optional[float]
    categories: Optional[List[str]]
    brands: Optional[List[str]]
    conversation_history: List[Dict[str, str]]
    missing_fields: List[str]
    agent_response: str
    is_complete: bool


class LangGraphConversationAgent:
    """
    LangGraphベースの対話エージェント

    役割：
    1. ユーザー入力から不足情報を判定
    2. 適切な質問を生成
    3. すべての必須情報が揃ったら完了
    """

    def __init__(self):
        # DMR endpoint設定（Docker Model Runner）
        self.llm_endpoint = os.getenv("DMR_API_URL", "http://host.docker.internal:12434/engines/llama.cpp/v1")
        self.llm_model = os.getenv("DMR_MODEL", "ai/smollm2")
        self.llm_api_key = os.getenv("DMR_API_KEY", "none")

        # ChatOpenAI初期化（OpenAI互換API）
        self.llm = ChatOpenAI(
            base_url=self.llm_endpoint,
            model=self.llm_model,
            api_key=self.llm_api_key,
            temperature=0.3,
            max_tokens=512,
        )

        # LangGraphのグラフを構築
        self.graph = self._build_graph()

        logger.info(f"[LangGraphConversationAgent] Initialized with LLM endpoint: {self.llm_endpoint}")

    def _build_graph(self) -> CompiledStateGraph:
        """LangGraphのグラフを構築

        フロー:
        1. extract_info: ユーザー入力から情報抽出
        2. check_completeness: 必須情報が揃ったか確認
        3. generate_question: 不足情報を質問（または完了メッセージ）
        """
        workflow = StateGraph(ConversationState)

        # ノード追加
        workflow.add_node("extract_info", self._extract_info_node)
        workflow.add_node("check_completeness", self._check_completeness_node)
        workflow.add_node("generate_question", self._generate_question_node)

        # エッジ追加
        workflow.set_entry_point("extract_info")
        workflow.add_edge("extract_info", "check_completeness")
        workflow.add_edge("check_completeness", "generate_question")
        workflow.add_edge("generate_question", END)

        return workflow.compile()

    def _extract_info_node(self, state: ConversationState) -> ConversationState:
        """ユーザー入力から情報抽出

        Args:
            state: 現在の状態

        Returns:
            更新された状態（抽出された情報を含む）
        """
        user_input = state.get("user_input", "")

        if not user_input:
            return state

        # 対話履歴に追加
        conversation_history = state.get("conversation_history", [])
        conversation_history.append({"role": "user", "content": user_input})
        state["conversation_history"] = conversation_history

        # LLMプロンプト構築
        system_prompt = """あなたはAP2 Shopping Agentです。ユーザーとの対話から以下の情報を抽出してください。

必須情報:
- intent: 購買意図（例: 「赤いバスケットボールシューズが欲しい」）
- max_amount: 最大金額（数値のみ、単位なし）

オプション情報:
- categories: カテゴリーリスト（例: ["スポーツ", "シューズ"]）。なければ空リスト
- brands: ブランドリスト（例: ["Nike", "Adidas"]）。なければ空リスト

以下のJSON形式で出力してください:
{
  "intent": "購買意図の文字列またはnull",
  "max_amount": 数値またはnull,
  "categories": ["カテゴリー1", "カテゴリー2"] または [],
  "brands": ["ブランド1", "ブランド2"] または []
}

JSONのみを出力し、説明文は含めないでください。"""

        # 対話履歴をコンテキストとして含める
        context_messages = []
        for msg in conversation_history[-5:]:  # 直近5件
            if msg["role"] == "user":
                context_messages.append(HumanMessage(content=msg["content"]))
            elif msg["role"] == "assistant":
                context_messages.append(AIMessage(content=msg["content"]))

        try:
            messages = [SystemMessage(content=system_prompt)] + context_messages

            response = self.llm.invoke(messages)
            llm_output = response.content.strip()

            logger.info(f"[extract_info] LLM raw output: {llm_output}")

            # JSON抽出
            if "```json" in llm_output:
                llm_output = llm_output.split("```json")[1].split("```")[0].strip()
            elif "```" in llm_output:
                llm_output = llm_output.split("```")[1].split("```")[0].strip()

            extracted = json.loads(llm_output)

            # 既存の値がある場合は上書きしない（累積的に情報を集める）
            if extracted.get("intent") and not state.get("intent"):
                state["intent"] = extracted["intent"]

            if extracted.get("max_amount") is not None and not state.get("max_amount"):
                state["max_amount"] = float(extracted["max_amount"])

            if extracted.get("categories") and not state.get("categories"):
                state["categories"] = extracted["categories"]

            if extracted.get("brands") and not state.get("brands"):
                state["brands"] = extracted["brands"]

            logger.info(
                f"[extract_info] Extracted: intent={state.get('intent')}, "
                f"max_amount={state.get('max_amount')}, "
                f"categories={state.get('categories')}, brands={state.get('brands')}"
            )

        except Exception as e:
            logger.error(f"[extract_info] Error: {e}", exc_info=True)
            # エラー時は状態を変更しない

        return state

    def _check_completeness_node(self, state: ConversationState) -> ConversationState:
        """必須情報が揃ったか確認

        Args:
            state: 現在の状態

        Returns:
            更新された状態（missing_fields, is_completeを含む）
        """
        missing_fields = []

        if not state.get("intent"):
            missing_fields.append("intent")

        if state.get("max_amount") is None:
            missing_fields.append("max_amount")

        state["missing_fields"] = missing_fields
        state["is_complete"] = len(missing_fields) == 0

        logger.info(f"[check_completeness] missing_fields={missing_fields}, is_complete={state['is_complete']}")

        return state

    def _generate_question_node(self, state: ConversationState) -> ConversationState:
        """不足情報を質問（または完了メッセージ）

        Args:
            state: 現在の状態

        Returns:
            更新された状態（agent_responseを含む）
        """
        missing_fields = state.get("missing_fields", [])

        if not missing_fields:
            # すべて揃った場合
            intent = state.get("intent", "")
            max_amount = state.get("max_amount", 0)
            categories = state.get("categories", [])
            brands = state.get("brands", [])

            response = f"購入条件が確認できました。\n\n"
            response += f"・購買意図: {intent}\n"
            response += f"・最大金額: {max_amount:,.0f}円\n"
            if categories:
                response += f"・カテゴリー: {', '.join(categories)}\n"
            if brands:
                response += f"・ブランド: {', '.join(brands)}\n"

            state["agent_response"] = response

        elif "intent" in missing_fields:
            # インテントが不足
            state["agent_response"] = "何をお探しですか？例えば「赤いバスケットボールシューズが欲しい」のように教えてください。"

        elif "max_amount" in missing_fields:
            # 最大金額が不足
            state["agent_response"] = "最大金額を教えてください。（例：50000円、または50000）"

        # 対話履歴に応答を追加
        conversation_history = state.get("conversation_history", [])
        conversation_history.append({"role": "assistant", "content": state["agent_response"]})
        state["conversation_history"] = conversation_history

        return state

    async def process_user_input(
        self,
        user_input: str,
        current_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """ユーザー入力を処理

        Args:
            user_input: ユーザーの入力
            current_state: 現在の状態（Noneの場合は新規開始）

        Returns:
            更新された状態
            {
                "intent": str | None,
                "max_amount": float | None,
                "categories": List[str],
                "brands": List[str],
                "agent_response": str,
                "is_complete": bool,
                "conversation_history": List[Dict]
            }
        """
        # 初期状態設定
        if current_state is None:
            initial_state: ConversationState = {
                "user_input": user_input,
                "intent": None,
                "max_amount": None,
                "categories": [],
                "brands": [],
                "conversation_history": [],
                "missing_fields": [],
                "agent_response": "",
                "is_complete": False,
            }
        else:
            initial_state: ConversationState = {
                "user_input": user_input,
                "intent": current_state.get("intent"),
                "max_amount": current_state.get("max_amount"),
                "categories": current_state.get("categories", []),
                "brands": current_state.get("brands", []),
                "conversation_history": current_state.get("conversation_history", []),
                "missing_fields": [],
                "agent_response": "",
                "is_complete": False,
            }

        # LangGraphグラフ実行
        final_state = self.graph.invoke(initial_state)

        # 結果を返す
        return {
            "intent": final_state.get("intent"),
            "max_amount": final_state.get("max_amount"),
            "categories": final_state.get("categories", []),
            "brands": final_state.get("brands", []),
            "agent_response": final_state.get("agent_response", ""),
            "is_complete": final_state.get("is_complete", False),
            "conversation_history": final_state.get("conversation_history", []),
        }


# シングルトンインスタンス
_conversation_agent_instance: Optional[LangGraphConversationAgent] = None


def get_conversation_agent() -> LangGraphConversationAgent:
    """LangGraphConversationAgentのシングルトンインスタンスを取得

    Returns:
        LangGraphConversationAgentインスタンス
    """
    global _conversation_agent_instance

    if _conversation_agent_instance is None:
        _conversation_agent_instance = LangGraphConversationAgent()

    return _conversation_agent_instance
