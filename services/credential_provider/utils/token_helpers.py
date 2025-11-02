"""
v2/services/credential_provider/utils/token_helpers.py

トークン生成関連のヘルパーメソッド
"""

import uuid
import json
import secrets
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TokenHelpers:
    """トークン生成に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: データベースマネージャーのインスタンス
        """
        self.db_manager = db_manager

    @staticmethod
    def generate_token(payment_mandate: Dict[str, Any], attestation: Dict[str, Any]) -> str:
        """
        認証トークン発行（WebAuthn attestation検証後）

        AP2仕様準拠：
        - 暗号学的に安全なトークンを生成
        - トークンは一時的（有効期限付き）

        Args:
            payment_mandate: PaymentMandate情報
            attestation: Attestation情報

        Returns:
            str: 生成されたトークン
        """
        # 暗号学的に安全なトークン生成
        # secrets.token_urlsafe()を使用（cryptographically strong random）
        random_bytes = secrets.token_urlsafe(32)  # 32バイト = 256ビット
        secure_token = f"cred_token_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"

        logger.info(f"[CredentialProvider] Generated attestation token for user: {payment_mandate.get('payer_id')}")

        return secure_token

    async def save_attestation(
        self,
        user_id: str,
        attestation_raw: Dict[str, Any],
        verified: bool,
        token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """
        Attestationをデータベースに保存

        Args:
            user_id: ユーザーID
            attestation_raw: Attestation生データ
            verified: 検証結果
            token: 生成されたトークン
            agent_token: Agent Token
        """
        # AttestationDBモデルを使用してSQLAlchemyに保存
        async with self.db_manager.get_session() as session:
            from common.database import Attestation

            attestation_record = Attestation(
                id=str(uuid.uuid4()),
                user_id=user_id,
                attestation_raw=json.dumps(attestation_raw),
                verified=1 if verified else 0,  # SQLiteはboolを0/1で保存
                verification_details=json.dumps({
                    "token": token,
                    "agent_token": agent_token,  # 決済ネットワークから取得したAgent Token
                    "verified_at": datetime.now(timezone.utc).isoformat()
                }) if token else None
            )

            session.add(attestation_record)
            await session.commit()

        logger.info(
            f"[CredentialProvider] Saved attestation: "
            f"user={user_id}, verified={verified}, agent_token={agent_token[:32] if agent_token else 'None'}..."
        )
