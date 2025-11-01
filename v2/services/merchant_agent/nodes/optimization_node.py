"""
v2/services/merchant_agent/nodes/optimization_node.py

カート最適化ノード（LLM直接実行）
"""

import json
from typing import TYPE_CHECKING, Dict, Any, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from v2.common.logger import get_logger
from v2.services.merchant_agent.utils.llm_utils import parse_json_from_llm

if TYPE_CHECKING:
    from v2.services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent, MerchantAgentState

logger = get_logger(__name__, service_name='langgraph_merchant')


def create_rule_based_plans(products: List[Dict[str, Any]], max_amount: Optional[float]) -> List[Dict[str, Any]]:
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


async def optimize_cart(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
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
    if not agent.llm:
        plans = create_rule_based_plans(products, max_amount)
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
        response = await agent.llm.ainvoke(messages)
        response_text = response.content

        # JSON抽出
        cart_plans = parse_json_from_llm(response_text)

        # AP2完全準拠: JSONパース失敗時はルールベースフォールバック
        if cart_plans is None:
            logger.warning("[optimize_cart] LLM JSON parse failed, using rule-based fallback")
            plans = create_rule_based_plans(products, max_amount)
            state["cart_plans"] = plans
            state["llm_reasoning"] = "LLM JSON parse failed, using rule-based fallback"
            logger.info(f"[optimize_cart] Fallback: Created {len(plans)} rule-based plans")
            return state

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
        plans = create_rule_based_plans(products, max_amount)
        state["cart_plans"] = plans
        state["llm_reasoning"] = f"LLM error, using rule-based fallback: {str(e)}"
        logger.info(f"[optimize_cart] Fallback: Created {len(plans)} rule-based plans")

    return state
