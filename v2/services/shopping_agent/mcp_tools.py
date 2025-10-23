"""
MCP（Model Context Protocol）ツール実装

AP2仕様準拠：
- LangGraphから呼び出し可能なツールを提供
- Intent Mandate生成支援（商品検索、価格推定等）
- 既存のA2A通信基盤と統合
"""

import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='mcp_tools')


class MCPIntentTools:
    """
    MCPプロトコルで提供するIntent Mandate生成支援ツール群

    ツール一覧:
    1. validate_merchant: Merchant検証
    2. estimate_price_range: 価格帯推定
    3. suggest_skus: SKU候補提案
    """

    @staticmethod
    async def validate_merchant(merchant_id: str) -> Dict[str, Any]:
        """Merchantの検証

        Args:
            merchant_id: Merchant識別子（例: "merchant_demo_001"）

        Returns:
            {
                "valid": bool,
                "merchant_name": str,
                "description": str
            }
        """
        # デモ実装: 既知のMerchantリスト
        known_merchants = {
            "merchant_demo_001": {
                "valid": True,
                "merchant_name": "AP2 Demo Merchant",
                "description": "AP2デモ用のMerchant（電化製品、衣料品等）"
            },
            "merchant_demo_002": {
                "valid": True,
                "merchant_name": "Alternative Merchant",
                "description": "代替Merchant"
            }
        }

        result = known_merchants.get(merchant_id, {
            "valid": False,
            "merchant_name": "",
            "description": "Unknown merchant"
        })

        logger.info(f"[validate_merchant] merchant_id={merchant_id}, valid={result['valid']}")
        return result

    @staticmethod
    async def estimate_price_range(
        product_description: str,
        category: Optional[str] = None
    ) -> Dict[str, Any]:
        """商品の価格帯推定

        Args:
            product_description: 商品の自然言語説明
            category: 商品カテゴリ（オプション）

        Returns:
            {
                "min_price": float,
                "max_price": float,
                "currency": str,
                "confidence": str  # "high", "medium", "low"
            }
        """
        # デモ実装: キーワードベースの簡易推定
        description_lower = product_description.lower()

        # カテゴリ別の価格帯
        if "シューズ" in description_lower or "靴" in description_lower:
            return {
                "min_price": 5000.0,
                "max_price": 30000.0,
                "currency": "JPY",
                "confidence": "medium"
            }
        elif "スマートフォン" in description_lower or "スマホ" in description_lower:
            return {
                "min_price": 30000.0,
                "max_price": 150000.0,
                "currency": "JPY",
                "confidence": "medium"
            }
        elif "tシャツ" in description_lower or "シャツ" in description_lower:
            return {
                "min_price": 1000.0,
                "max_price": 10000.0,
                "currency": "JPY",
                "confidence": "medium"
            }
        else:
            # デフォルト価格帯
            return {
                "min_price": 1000.0,
                "max_price": 50000.0,
                "currency": "JPY",
                "confidence": "low"
            }

    @staticmethod
    async def suggest_skus(
        product_description: str,
        merchant_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """SKU候補の提案

        Args:
            product_description: 商品の自然言語説明
            merchant_id: Merchant識別子（オプション）

        Returns:
            {
                "suggested_skus": List[str],
                "confidence": str
            }
        """
        # デモ実装: キーワードマッチング
        description_lower = product_description.lower()
        suggested_skus = []

        if "赤" in description_lower and "シューズ" in description_lower:
            suggested_skus = ["SHOE_RED_001", "SHOE_RED_002"]
        elif "スマートフォン" in description_lower:
            suggested_skus = ["PHONE_ANDROID_001", "PHONE_IOS_001"]
        elif "tシャツ" in description_lower:
            suggested_skus = ["TSHIRT_001", "TSHIRT_002"]

        return {
            "suggested_skus": suggested_skus,
            "confidence": "medium" if suggested_skus else "low"
        }

    @staticmethod
    async def calculate_intent_expiry(hours: int = 24) -> str:
        """Intent Mandateの有効期限を計算

        Args:
            hours: 有効期間（時間）

        Returns:
            ISO 8601形式の有効期限
        """
        expiry_time = datetime.now(timezone.utc) + timedelta(hours=hours)
        return expiry_time.isoformat().replace('+00:00', 'Z')


# ツールレジストリ（LangGraphから呼び出し可能な関数リスト）
MCP_TOOL_REGISTRY = {
    "validate_merchant": MCPIntentTools.validate_merchant,
    "estimate_price_range": MCPIntentTools.estimate_price_range,
    "suggest_skus": MCPIntentTools.suggest_skus,
    "calculate_intent_expiry": MCPIntentTools.calculate_intent_expiry,
}


async def call_mcp_tool(tool_name: str, **kwargs) -> Dict[str, Any]:
    """MCPツールを呼び出す

    Args:
        tool_name: ツール名
        **kwargs: ツールへの引数

    Returns:
        ツールの実行結果

    Raises:
        ValueError: ツールが見つからない場合
    """
    tool_func = MCP_TOOL_REGISTRY.get(tool_name)

    if not tool_func:
        raise ValueError(f"Unknown MCP tool: {tool_name}")

    logger.info(f"[call_mcp_tool] Calling {tool_name} with args: {kwargs}")
    result = await tool_func(**kwargs)
    logger.info(f"[call_mcp_tool] Result from {tool_name}: {result}")

    return result
