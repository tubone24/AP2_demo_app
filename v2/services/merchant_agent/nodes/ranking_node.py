"""
v2/services/merchant_agent/nodes/ranking_node.py

カート候補ランキングノード
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from v2.services.merchant_agent.langgraph_merchant import MerchantAgentState

from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='langgraph_merchant')


async def rank_and_select(state: 'MerchantAgentState') -> 'MerchantAgentState':
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
