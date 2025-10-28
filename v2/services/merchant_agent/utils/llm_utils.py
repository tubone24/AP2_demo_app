"""
v2/services/merchant_agent/utils/llm_utils.py

LLM処理用ヘルパー関数
"""

import re
import json
from typing import List, Any

from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='langgraph_merchant')


def extract_keywords_simple(text: str) -> List[str]:
    """自然言語から検索キーワードを抽出（簡易版）

    LLM無効時のフォールバック用。カッコや助詞を除去し、名詞的な単語を抽出。

    Args:
        text: 自然言語テキスト（例: "かわいいグッズを購入したい（価格・カテゴリ・ブランド等の制約なし）"）

    Returns:
        検索キーワードリスト（例: ["グッズ"]）
    """
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


def parse_json_from_llm(text: str) -> Any:
    """LLMの応答からJSON部分を抽出してパース"""
    # ```json ... ``` または ``` ... ``` から抽出

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
        logger.error(f"[parse_json_from_llm] JSON parse error: {e}, text: {json_str[:200]}")
        # フォールバック
        return {}
