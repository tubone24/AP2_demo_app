"""
v2/services/merchant_agent/nodes/intent_node.py

IntentMandate解析ノード（LLM直接実行）
"""

import json
from typing import TYPE_CHECKING, List

from langchain_core.messages import HumanMessage, SystemMessage

from v2.common.logger import get_logger
from v2.services.merchant_agent.utils.llm_utils import extract_keywords_simple, parse_json_from_llm

if TYPE_CHECKING:
    from v2.services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent, MerchantAgentState

logger = get_logger(__name__, service_name='langgraph_merchant')


async def analyze_intent(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
    """IntentMandateを解析してユーザー嗜好を抽出（LLM直接実行）

    AP2準拠のIntentMandate構造:
    - natural_language_description: ユーザーの意図
    - merchants: 許可されたMerchantリスト（オプション）
    - skus: 特定のSKUリスト（オプション）
    - requires_refundability: 返金可能性要件（オプション）
    """
    # MCP初期化（初回のみ、データアクセスツール用）
    if not agent.mcp_initialized:
        try:
            await agent.mcp_client.initialize()
            agent.mcp_initialized = True
            logger.info("[analyze_intent] MCP client initialized")
        except Exception as e:
            logger.error(f"[analyze_intent] MCP initialization failed: {e}")

    intent_mandate = state["intent_mandate"]
    natural_language_description = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))

    # LLMが無効な場合はフォールバック（AP2準拠）
    if not agent.llm:
        # natural_language_descriptionからキーワード抽出
        # 簡易的な形態素解析: カッコや助詞を除去し、名詞的な単語を抽出
        keywords = extract_keywords_simple(natural_language_description)

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
        response = await agent.llm.ainvoke(messages)
        response_text = response.content

        # JSON抽出
        preferences = parse_json_from_llm(response_text)

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
