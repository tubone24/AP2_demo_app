"""
v2/services/credential_provider/utils/passkey_helpers.py

Passkey/WebAuthn関連のヘルパーメソッド
"""

import base64
import json
import secrets
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class PasskeyHelpers:
    """Passkey/WebAuthn処理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager, key_manager, attestation_manager, challenge_store):
        """
        Args:
            db_manager: データベースマネージャー
            key_manager: キーマネージャー
            attestation_manager: Attestationマネージャー
            challenge_store: Challengeストア（Redis）
        """
        self.db_manager = db_manager
        self.key_manager = key_manager
        self.attestation_manager = attestation_manager
        self.challenge_store = challenge_store

    # TODO: 必要に応じてメソッドを追加
    # このファイルはスタブとして作成し、後で完全な実装を追加可能
