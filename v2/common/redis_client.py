"""
v2/common/redis_client.py

Redis KVストアクライアント（共通モジュール）
- 一時データのTTL管理
- セッション・トークン・チャレンジの保存/取得
"""

import json
import logging
from typing import Optional, Any, Dict
from datetime import timedelta
import redis.asyncio as redis

logger = logging.getLogger(__name__)


class RedisClient:
    """
    Redis KVストアクライアント

    用途:
    - トークンストア（TTL: 15分）
    - Step-upセッション（TTL: 10分）
    - WebAuthn challenge（TTL: 60秒）
    - その他一時データ
    """

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        """
        Args:
            redis_url: Redis接続URL（デフォルト: redis://localhost:6379/0）
        """
        self.redis_url = redis_url
        self.client: Optional[redis.Redis] = None

    async def connect(self):
        """Redis接続を確立"""
        if self.client is None:
            self.client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_timeout=5.0,
                socket_connect_timeout=5.0
            )
            logger.info(f"[RedisClient] Connected to Redis: {self.redis_url}")

    async def disconnect(self):
        """Redis接続を切断"""
        if self.client:
            await self.client.close()
            self.client = None
            logger.info("[RedisClient] Disconnected from Redis")

    async def set(
        self,
        key: str,
        value: Any,
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        キーと値をRedisに保存

        Args:
            key: Redis key
            value: 保存する値（dict, list, str, int, bool等）
            ttl_seconds: 有効期限（秒）、Noneの場合は無期限

        Returns:
            成功した場合True
        """
        try:
            await self.connect()

            # 値をJSON文字列に変換
            if isinstance(value, (dict, list)):
                value_str = json.dumps(value, ensure_ascii=False)
            else:
                value_str = str(value)

            # TTL付きで保存
            if ttl_seconds:
                await self.client.setex(key, ttl_seconds, value_str)
            else:
                await self.client.set(key, value_str)

            logger.debug(f"[RedisClient] SET key={key}, ttl={ttl_seconds}s")
            return True

        except Exception as e:
            logger.error(f"[RedisClient] Failed to SET key={key}: {e}", exc_info=True)
            return False

    async def get(self, key: str, as_json: bool = True) -> Optional[Any]:
        """
        キーの値を取得

        Args:
            key: Redis key
            as_json: True の場合、JSON文字列をパースして返す

        Returns:
            値（存在しない場合None）
        """
        try:
            await self.connect()

            value_str = await self.client.get(key)
            if value_str is None:
                return None

            # JSONパース
            if as_json:
                try:
                    return json.loads(value_str)
                except json.JSONDecodeError:
                    # JSONパースに失敗した場合は文字列として返す
                    return value_str
            else:
                return value_str

        except Exception as e:
            logger.error(f"[RedisClient] Failed to GET key={key}: {e}", exc_info=True)
            return None

    async def delete(self, key: str) -> bool:
        """
        キーを削除

        Args:
            key: Redis key

        Returns:
            成功した場合True
        """
        try:
            await self.connect()

            deleted = await self.client.delete(key)
            logger.debug(f"[RedisClient] DELETE key={key}, deleted={deleted}")
            return deleted > 0

        except Exception as e:
            logger.error(f"[RedisClient] Failed to DELETE key={key}: {e}", exc_info=True)
            return False

    async def exists(self, key: str) -> bool:
        """
        キーが存在するかチェック

        Args:
            key: Redis key

        Returns:
            存在する場合True
        """
        try:
            await self.connect()

            exists = await self.client.exists(key)
            return exists > 0

        except Exception as e:
            logger.error(f"[RedisClient] Failed to check EXISTS key={key}: {e}", exc_info=True)
            return False

    async def get_ttl(self, key: str) -> Optional[int]:
        """
        キーの残りTTLを取得

        Args:
            key: Redis key

        Returns:
            残りTTL（秒）、キーが存在しない場合None、TTLが設定されていない場合-1
        """
        try:
            await self.connect()

            ttl = await self.client.ttl(key)
            if ttl == -2:  # キーが存在しない
                return None
            return ttl

        except Exception as e:
            logger.error(f"[RedisClient] Failed to get TTL for key={key}: {e}", exc_info=True)
            return None

    async def keys(self, pattern: str = "*") -> list[str]:
        """
        パターンにマッチするキー一覧を取得

        Args:
            pattern: キーパターン（例: "token:*", "session:*"）

        Returns:
            キーのリスト
        """
        try:
            await self.connect()

            keys = await self.client.keys(pattern)
            return keys

        except Exception as e:
            logger.error(f"[RedisClient] Failed to get KEYS pattern={pattern}: {e}", exc_info=True)
            return []


class TokenStore:
    """
    トークンストア（Redis KV）

    用途:
    - payment_method トークン（TTL: 15分）
    - step-up 完了トークン（TTL: 15分）
    """

    def __init__(self, redis_client: RedisClient, prefix: str = "token"):
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = 15 * 60  # 15分

    def _make_key(self, token: str) -> str:
        """トークンキーを生成"""
        return f"{self.prefix}:{token}"

    async def save_token(
        self,
        token: str,
        token_data: Dict[str, Any],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        トークンを保存

        Args:
            token: トークン文字列
            token_data: トークンに関連付けるデータ
            ttl_seconds: 有効期限（秒）、Noneの場合はデフォルト15分
        """
        key = self._make_key(token)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        return await self.redis.set(key, token_data, ttl_seconds=ttl)

    async def get_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        トークンデータを取得

        Args:
            token: トークン文字列

        Returns:
            トークンデータ（存在しない場合None）
        """
        key = self._make_key(token)
        return await self.redis.get(key, as_json=True)

    async def delete_token(self, token: str) -> bool:
        """
        トークンを削除

        Args:
            token: トークン文字列
        """
        key = self._make_key(token)
        return await self.redis.delete(key)


class SessionStore:
    """
    セッションストア（Redis KV）

    用途:
    - Step-upセッション（TTL: 10分）
    - WebAuthn チャレンジ（TTL: 60秒）
    """

    def __init__(self, redis_client: RedisClient, prefix: str = "session"):
        self.redis = redis_client
        self.prefix = prefix
        self.default_ttl = 10 * 60  # 10分

    def _make_key(self, session_id: str) -> str:
        """セッションキーを生成"""
        return f"{self.prefix}:{session_id}"

    async def save_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        セッションを保存

        Args:
            session_id: セッションID
            session_data: セッションデータ
            ttl_seconds: 有効期限（秒）、Noneの場合はデフォルト10分
        """
        key = self._make_key(session_id)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl
        return await self.redis.set(key, session_data, ttl_seconds=ttl)

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        セッションデータを取得

        Args:
            session_id: セッションID

        Returns:
            セッションデータ（存在しない場合None）
        """
        key = self._make_key(session_id)
        return await self.redis.get(key, as_json=True)

    async def delete_session(self, session_id: str) -> bool:
        """
        セッションを削除

        Args:
            session_id: セッションID
        """
        key = self._make_key(session_id)
        return await self.redis.delete(key)

    async def update_session(
        self,
        session_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        セッションデータを更新（マージ）

        Args:
            session_id: セッションID
            updates: 更新するフィールド
        """
        key = self._make_key(session_id)

        # 既存データを取得
        existing_data = await self.get_session(session_id)
        if existing_data is None:
            return False

        # マージして保存
        existing_data.update(updates)

        # TTLを維持
        ttl = await self.redis.get_ttl(key)
        if ttl and ttl > 0:
            return await self.redis.set(key, existing_data, ttl_seconds=ttl)
        else:
            return await self.redis.set(key, existing_data, ttl_seconds=self.default_ttl)
