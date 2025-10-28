"""
v2/services/payment_network/network.py

Payment Network Service実装

決済ネットワークのスタブサービス：
- Agent Tokenの発行（トークン化呼び出し）
- トークン検証
- 決済ネットワーク固有のロジック

AP2仕様準拠：
- Step 23: CPからのトークン化呼び出しを受け付ける
- Agent Tokenを発行してCPに返却
"""

import sys
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import secrets

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from services.payment_network.utils import TokenHelpers

logger = logging.getLogger(__name__)


# ========================================
# リクエスト/レスポンスモデル
# ========================================

class TokenizeRequest(BaseModel):
    """
    トークン化リクエスト（CPから受信）

    AP2 Step 23: CPが決済ネットワークに送信するトークン化呼び出し
    """
    payment_mandate: Dict[str, Any]  # PaymentMandate オブジェクト
    attestation: Optional[Dict[str, Any]] = None  # デバイス認証情報
    payment_method_token: str  # CPが管理する支払い方法トークン
    transaction_context: Optional[Dict[str, Any]] = None  # 追加のトランザクションデータ


class TokenizeResponse(BaseModel):
    """
    トークン化レスポンス（CPに返却）
    """
    agent_token: str  # 決済ネットワークが発行するエージェントトークン
    expires_at: str  # トークン有効期限（ISO 8601形式）
    network_name: str  # ネットワーク名（例: "Visa", "Mastercard"）
    token_type: str = "agent_token"  # トークンタイプ


class VerifyTokenRequest(BaseModel):
    """
    トークン検証リクエスト
    """
    agent_token: str  # エージェントトークン


class VerifyTokenResponse(BaseModel):
    """
    トークン検証レスポンス
    """
    valid: bool
    token_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


# ========================================
# Payment Network Service
# ========================================

class PaymentNetworkService:
    """
    決済ネットワークサービス（スタブ実装）

    実際の決済ネットワーク（Visa, Mastercard等）のスタブとして動作
    - Agent Tokenの発行
    - トークン検証

    注意: このサービスは実際の決済ネットワークではなく、
    デモ環境でのスタブ実装です。
    """

    def __init__(self, network_name: str = "DemoPaymentNetwork"):
        self.network_name = network_name
        self.app = FastAPI(
            title=f"{network_name} - Payment Network Service",
            description="AP2準拠の決済ネットワークスタブサービス",
            version="1.0.0"
        )

        # トークンストア（Agent Token → トークン情報のマッピング）
        # 本番環境ではRedis等のKVストアやデータベースを使用
        self.agent_token_store: Dict[str, Dict[str, Any]] = {}

        # Helperクラス初期化
        self.token_helpers = TokenHelpers(
            network_name=self.network_name,
            token_store=self.agent_token_store
        )

        # エンドポイント登録
        self.register_endpoints()

        logger.info(f"[{self.network_name}] Payment Network Service initialized")

    def register_endpoints(self):
        """エンドポイントの登録"""

        @self.app.get("/health")
        async def health_check():
            """ヘルスチェックエンドポイント"""
            return {
                "status": "healthy",
                "service": "payment_network",
                "network_name": self.network_name,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        @self.app.post("/network/tokenize", response_model=TokenizeResponse)
        async def tokenize_payment(request: TokenizeRequest):
            """
            POST /network/tokenize - Agent Token発行

            AP2 Step 23: Credential Providerからのトークン化呼び出し

            処理フロー:
            1. PaymentMandateとattestationを検証
            2. 支払い方法トークンを検証
            3. Agent Tokenを生成（暗号学的に安全なトークン）
            4. トークンストアに保存
            5. Agent Tokenを返却

            リクエスト:
            {
              "payment_mandate": {...},
              "attestation": {...},
              "payment_method_token": "tok_xxx",
              "transaction_context": {...}
            }

            レスポンス:
            {
              "agent_token": "agent_tok_xxx",
              "expires_at": "2025-10-18T12:34:56Z",
              "network_name": "DemoPaymentNetwork",
              "token_type": "agent_token"
            }
            """
            try:
                payment_mandate = request.payment_mandate
                payment_method_token = request.payment_method_token

                logger.info(
                    f"[{self.network_name}] Received tokenization request: "
                    f"payment_mandate_id={payment_mandate.get('id')}, "
                    f"payment_method_token={payment_method_token[:20]}..."
                )

                # PaymentMandate検証（スタブ実装）
                if not payment_mandate.get("id"):
                    raise HTTPException(
                        status_code=400,
                        detail="Missing payment_mandate.id"
                    )

                # 支払い方法トークン検証（スタブ実装）
                if not payment_method_token.startswith("tok_"):
                    raise HTTPException(
                        status_code=400,
                        detail="Invalid payment_method_token format"
                    )

                # Agent Token生成（ヘルパーメソッドに委譲）
                agent_token, expires_at_iso = self.token_helpers.generate_agent_token(
                    payment_mandate=payment_mandate,
                    payment_method_token=payment_method_token,
                    attestation_verified=request.attestation is not None,
                    expiry_hours=1
                )

                return TokenizeResponse(
                    agent_token=agent_token,
                    expires_at=expires_at_iso.replace('+00:00', 'Z'),
                    network_name=self.network_name,
                    token_type="agent_token"
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[{self.network_name}] Tokenization error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/network/verify-token", response_model=VerifyTokenResponse)
        async def verify_token(request: VerifyTokenRequest):
            """
            POST /network/verify-token - Agent Token検証

            処理フロー:
            1. Agent Tokenをトークンストアから取得
            2. 有効期限を確認
            3. トークン情報を返却

            リクエスト:
            {
              "agent_token": "agent_tok_xxx"
            }

            レスポンス:
            {
              "valid": true,
              "token_info": {
                "payment_mandate_id": "...",
                "payer_id": "...",
                "amount": {...},
                "network_name": "DemoPaymentNetwork"
              }
            }
            """
            try:
                agent_token = request.agent_token

                # Agent Token検証（ヘルパーメソッドに委譲）
                valid, token_info, error = self.token_helpers.verify_agent_token(agent_token)

                return VerifyTokenResponse(
                    valid=valid,
                    token_info=token_info,
                    error=error
                )

            except Exception as e:
                logger.error(f"[{self.network_name}] Token verification error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/network/info")
        async def network_info():
            """
            GET /network/info - ネットワーク情報取得

            レスポンス:
            {
              "network_name": "DemoPaymentNetwork",
              "supported_payment_methods": ["card"],
              "tokenization_enabled": true,
              "agent_transactions_supported": true
            }
            """
            return {
                "network_name": self.network_name,
                "supported_payment_methods": ["card", "digital_wallet"],
                "tokenization_enabled": True,
                "agent_transactions_supported": True,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
