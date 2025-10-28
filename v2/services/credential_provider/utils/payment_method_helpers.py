"""
v2/services/credential_provider/utils/payment_method_helpers.py

支払い方法管理関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class PaymentMethodHelpers:
    """支払い方法管理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager, token_store):
        """
        Args:
            db_manager: データベースマネージャー
            token_store: トークンストア（Redis）
        """
        self.db_manager = db_manager
        self.token_store = token_store

    # TODO: 必要に応じてメソッドを追加
    # このファイルはスタブとして作成し、後で完全な実装を追加可能
