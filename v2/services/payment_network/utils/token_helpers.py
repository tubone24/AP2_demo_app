"""
v2/services/payment_network/utils/token_helpers.py

Agent Token生成・検証関連のヘルパーメソッド
"""

import uuid
import logging
import secrets
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta

from common.redis_client import TokenStore

logger = logging.getLogger(__name__)


class TokenHelpers:
    """Agent Token生成・検証に関連するヘルパーメソッドを提供するクラス（Redis対応）"""

    def __init__(self, network_name: str, token_store: TokenStore):
        """
        Args:
            network_name: ネットワーク名
            token_store: RedisベースのTokenStore
        """
        self.network_name = network_name
        self.token_store = token_store

    async def generate_agent_token(
        self,
        payment_mandate: Dict[str, Any],
        payment_method_token: str,
        attestation_verified: bool,
        expiry_hours: int = 1
    ) -> Tuple[str, str]:
        """
        Agent Token生成（Redis対応）

        Args:
            payment_mandate: PaymentMandate
            payment_method_token: 支払い方法トークン
            attestation_verified: 認証情報検証済みフラグ
            expiry_hours: 有効期限（時間）

        Returns:
            Tuple[str, str]: (agent_token, expires_at_iso)
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=expiry_hours)

        # secrets.token_urlsafe()を使用（cryptographically strong random）
        random_bytes = secrets.token_urlsafe(32)  # 32バイト = 256ビット
        agent_token = f"agent_tok_{self.network_name.lower()}_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"

        # トークンデータ
        token_data = {
            "payment_mandate_id": payment_mandate.get("id"),
            "payment_method_token": payment_method_token,
            "payer_id": payment_mandate.get("payer_id"),
            "amount": payment_mandate.get("amount"),
            "issued_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "network_name": self.network_name,
            "attestation_verified": attestation_verified
        }

        # RedisベースのTokenStoreに保存（TTL: expiry_hours）
        ttl_seconds = expiry_hours * 3600
        await self.token_store.save_token(agent_token, token_data, ttl_seconds=ttl_seconds)

        logger.info(
            f"[{self.network_name}] Issued Agent Token (Redis): {agent_token[:32]}..., "
            f"expires_at={expires_at.isoformat()}, ttl={ttl_seconds}s"
        )

        return agent_token, expires_at.isoformat()

    async def verify_agent_token(self, agent_token: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Agent Token検証（Redis対応）

        Args:
            agent_token: Agent Token

        Returns:
            Tuple[bool, Optional[Dict[str, Any]], Optional[str]]: (valid, token_info, error)
        """
        logger.info(f"[{self.network_name}] Verifying Agent Token (Redis): {agent_token[:32]}...")

        # RedisベースのTokenStoreから取得
        token_data = await self.token_store.get_token(agent_token)
        if not token_data:
            logger.warning(f"[{self.network_name}] Agent Token not found in Redis: {agent_token[:32]}...")
            return False, None, "Agent Token not found"

        # 有効期限確認（Redis TTLで自動削除されるが、念のため確認）
        expires_at = datetime.fromisoformat(token_data["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            logger.warning(f"[{self.network_name}] Agent Token expired: {agent_token[:32]}...")
            # 期限切れトークンを削除
            await self.token_store.delete_token(agent_token)
            return False, None, "Agent Token expired"

        logger.info(
            f"[{self.network_name}] Agent Token valid: "
            f"payment_mandate_id={token_data.get('payment_mandate_id')}"
        )

        token_info = {
            "payment_mandate_id": token_data.get("payment_mandate_id"),
            "payer_id": token_data.get("payer_id"),
            "amount": token_data.get("amount"),
            "network_name": token_data.get("network_name"),
            "issued_at": token_data.get("issued_at"),
            "expires_at": token_data.get("expires_at")
        }

        return True, token_info, None
