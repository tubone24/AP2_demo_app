"""
v2/services/shopping_agent/nodes/common.py

LangGraphノードの共通定義・型・ユーティリティ
"""

import os
import asyncio
import logging
from typing import Any, Dict, List, Optional, TypedDict

# AP2型定義
import sys
sys.path.insert(0, '/app')
from ap2_types import Signature

logger = logging.getLogger(__name__)


# ============================================================================
# State定義
# ============================================================================

class ShoppingFlowState(TypedDict):
    """LangGraph StateGraphの状態

    注意: eventsはreducerを使わず、各ノードが新しいイベントのみを返す
    これにより、フロントエンドには今回の実行で生成されたイベントのみが送信される
    """
    user_input: str
    session_id: str
    session: Dict[str, Any]
    events: List[Dict[str, Any]]  # reducerなし：各ノードが新しいイベントのみを返す
    next_step: Optional[str]
    error: Optional[str]


# ============================================================================
# ユーティリティ関数
# ============================================================================

async def send_agent_message(events: List[Dict[str, Any]], message: str, delay: float = 0.2):
    """
    エージェントメッセージを一文字ずつストリーミング送信

    Args:
        events: イベントリスト
        message: 送信するメッセージ
        delay: メッセージ送信後のディレイ（秒）
    """
    for char in message:
        events.append({
            "type": "agent_text_chunk",
            "content": char
        })

    events.append({
        "type": "agent_text_complete",
        "content": ""
    })

    if delay > 0:
        await asyncio.sleep(delay)
