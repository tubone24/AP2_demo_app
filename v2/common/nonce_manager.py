"""
NonceManager - Nonce再利用攻撃を防ぐためのnonce管理クラス

AP2プロトコルのA2Aメッセージング層で使用され、各nonceが一度だけ使用されることを保証します。
"""

import threading
import time
from typing import Dict, Optional
from datetime import datetime, timedelta

try:
    from v2.common.logger import get_logger
except ModuleNotFoundError:
    from common.logger import get_logger

# ロガーのセットアップ
logger = get_logger(__name__, service_name='nonce')


class NonceManager:
    """
    Nonce再利用攻撃を防ぐためのマネージャークラス

    特徴:
    - スレッドセーフな実装（threading.Lock使用）
    - TTLベースの自動クリーンアップ（デフォルト300秒）
    - アトミックなチェック&記録操作
    """

    def __init__(self, ttl_seconds: int = 300, cleanup_interval: int = 60):
        """
        NonceManagerを初期化

        Args:
            ttl_seconds: Nonceの有効期限（秒）。デフォルト300秒（A2Aタイムスタンプ検証ウィンドウと同じ）
            cleanup_interval: クリーンアップの実行間隔（秒）
        """
        self._used_nonces: Dict[str, float] = {}  # nonce -> expiry_timestamp
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds
        self._cleanup_interval = cleanup_interval
        self._last_cleanup = time.time()

    def is_valid_nonce(self, nonce: str) -> bool:
        """
        Nonceが有効（未使用）かチェックし、使用済みとして記録

        このメソッドはアトミックな操作で、チェックと記録を同時に行います。
        同じnonceが複数のスレッドから同時にチェックされても、
        1つだけがTrueを返し、他はFalseを返します。

        Args:
            nonce: チェック対象のnonce文字列

        Returns:
            True: Nonceが有効（初めて使用）
            False: Nonceが無効（既に使用済み）
        """
        with self._lock:
            # 定期的なクリーンアップ実行
            current_time = time.time()
            if current_time - self._last_cleanup > self._cleanup_interval:
                self._cleanup_expired()

            # Nonceが既に使用済みかチェック
            if nonce in self._used_nonces:
                # 期限切れかチェック
                if self._used_nonces[nonce] > current_time:
                    # まだ有効期限内 -> 再利用攻撃
                    return False
                else:
                    # 期限切れなので削除して新規として扱う
                    del self._used_nonces[nonce]

            # 新しいnonceとして記録
            expiry_time = current_time + self._ttl_seconds
            self._used_nonces[nonce] = expiry_time
            return True

    def _cleanup_expired(self) -> None:
        """
        期限切れのnonceをストレージから削除

        注意: このメソッドは_lockを保持している状態で呼び出される前提です
        """
        current_time = time.time()
        expired_nonces = [
            nonce for nonce, expiry in self._used_nonces.items()
            if expiry <= current_time
        ]

        for nonce in expired_nonces:
            del self._used_nonces[nonce]

        self._last_cleanup = current_time

        if expired_nonces:
            logger.debug(f"Cleaned up {len(expired_nonces)} expired nonces")

    def get_stats(self) -> Dict[str, any]:
        """
        現在のNonceManager統計情報を取得（デバッグ用）

        Returns:
            統計情報を含む辞書
        """
        with self._lock:
            current_time = time.time()
            active_count = sum(1 for expiry in self._used_nonces.values() if expiry > current_time)
            expired_count = len(self._used_nonces) - active_count

            return {
                "total_nonces": len(self._used_nonces),
                "active_nonces": active_count,
                "expired_nonces": expired_count,
                "ttl_seconds": self._ttl_seconds,
                "last_cleanup": datetime.fromtimestamp(self._last_cleanup).isoformat(),
            }

    def clear_all(self) -> None:
        """
        すべてのnonceをクリア（テスト用）
        """
        with self._lock:
            count = len(self._used_nonces)
            self._used_nonces.clear()
            logger.info(f"Cleared {count} nonces")


# シングルトンインスタンス（オプション）
_global_nonce_manager: Optional[NonceManager] = None


def get_global_nonce_manager() -> NonceManager:
    """
    グローバルなNonceManagerインスタンスを取得

    複数の場所から同じインスタンスを共有する場合に使用。
    """
    global _global_nonce_manager
    if _global_nonce_manager is None:
        _global_nonce_manager = NonceManager()
    return _global_nonce_manager
