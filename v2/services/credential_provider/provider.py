"""
v2/services/credential_provider/provider.py

Credential Provider実装
- WebAuthn attestation検証
- 支払い方法管理
- トークン発行
"""

import sys
import uuid
import json
import base64
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
import logging

from fastapi import HTTPException
from fido2.webauthn import AttestationObject

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage, AttestationVerifyRequest, AttestationVerifyResponse
from v2.common.database import DatabaseManager, Attestation, PasskeyCredentialCRUD
from ap2_crypto import DeviceAttestationManager, KeyManager

logger = logging.getLogger(__name__)


class CredentialProviderService(BaseAgent):
    """
    Credential Provider

    ユーザーの認証情報を管理
    - WebAuthn attestation検証
    - 支払い方法管理
    - トークン発行
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:agent:credential_provider",
            agent_name="Credential Provider",
            passphrase=AgentPassphraseManager.get_passphrase("credential_provider"),
            keys_directory="./keys"
        )

        # データベースマネージャー（絶対パスを使用）
        self.db_manager = DatabaseManager(database_url="sqlite+aiosqlite:////app/v2/data/ap2.db")

        # Device Attestation Manager（既存のap2_crypto.pyを使用）
        self.attestation_manager = DeviceAttestationManager(self.key_manager)

        # 支払い方法データ（簡易版 - インメモリ）
        self.payment_methods: Dict[str, List[Dict[str, Any]]] = {
            "user_demo_001": [
                {
                    "id": "pm_001",
                    "type": "card",
                    "token": "tok_visa_4242",
                    "last4": "4242",
                    "brand": "visa",
                    "expiry_month": 12,
                    "expiry_year": 2025,
                    "holder_name": "山田太郎"
                }
            ],
            "user_demo_002": [
                {
                    "id": "pm_002",
                    "type": "card",
                    "token": "tok_mastercard_5555",
                    "last4": "5555",
                    "brand": "mastercard",
                    "expiry_month": 6,
                    "expiry_year": 2026,
                    "holder_name": "佐藤花子"
                }
            ]
        }

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Credential Providerが受信するA2Aメッセージ：
        - ap2/PaymentMandate: Shopping Agentからの認証依頼
        - ap2/AttestationRequest: デバイス証明リクエスト
        """
        self.a2a_handler.register_handler("ap2/PaymentMandate", self.handle_payment_mandate)
        self.a2a_handler.register_handler("ap2/AttestationRequest", self.handle_attestation_request)

    def register_endpoints(self):
        """
        Credential Provider固有エンドポイントの登録
        """

        @self.app.post("/register/passkey")
        async def register_passkey(registration_request: Dict[str, Any]):
            """
            POST /register/passkey - Passkey登録

            WebAuthn Registration Ceremonyの結果を受信して、
            公開鍵をデータベースに保存します。

            リクエスト:
            {
              "user_id": "user_demo_001",
              "credential_id": "...",  // Base64URL
              "public_key_cose": "...",  // Base64（COSE format）
              "transports": ["internal"],  // オプション
              "attestation_object": "...",  // オプション（検証用）
              "client_data_json": "..."  // オプション（検証用）
            }

            レスポンス:
            {
              "success": true,
              "credential_id": "...",
              "message": "Passkey registered successfully"
            }
            """
            try:
                user_id = registration_request["user_id"]
                credential_id = registration_request["credential_id"]
                attestation_object_b64 = registration_request["attestation_object"]
                transports = registration_request.get("transports", [])

                logger.info(f"[register_passkey] Registering passkey for user: {user_id}")

                # attestationObjectから公開鍵を抽出
                # Base64URLデコード
                padding_needed = len(attestation_object_b64) % 4
                if padding_needed:
                    attestation_object_b64 += '=' * (4 - padding_needed)

                attestation_object_b64_std = attestation_object_b64.replace('-', '+').replace('_', '/')
                attestation_object_bytes = base64.b64decode(attestation_object_b64_std)

                # fido2ライブラリでパース
                attestation_obj = AttestationObject(attestation_object_bytes)
                auth_data = attestation_obj.auth_data

                # 公開鍵を取得（COSE形式）
                # auth_data.credential_data.public_keyはCoseKeyオブジェクト
                credential_public_key = auth_data.credential_data.public_key

                # CoseKeyオブジェクトを辞書に変換してCBORエンコード
                import cbor2
                if hasattr(credential_public_key, '__iter__') and not isinstance(credential_public_key, (str, bytes)):
                    # CoseKeyは辞書のようなオブジェクト
                    cose_key_dict = dict(credential_public_key)
                    public_key_cose_bytes = cbor2.dumps(cose_key_dict)
                else:
                    # フォールバック: bytesならそのまま使用
                    public_key_cose_bytes = bytes(credential_public_key)

                # COSE公開鍵をBase64エンコード（検証時に使用）
                public_key_cose_b64 = base64.b64encode(public_key_cose_bytes).decode('utf-8')

                logger.info(f"[register_passkey] COSE key length: {len(public_key_cose_bytes)} bytes")
                logger.info(f"[register_passkey] COSE key dict: {cose_key_dict if 'cose_key_dict' in locals() else 'N/A'}")

                logger.info(f"[register_passkey] Extracted public key from attestationObject")

                # データベースに保存
                async with self.db_manager.get_session() as session:
                    # 既存のcredential_idをチェック
                    existing_credential = await PasskeyCredentialCRUD.get_by_credential_id(
                        session, credential_id
                    )

                    if existing_credential:
                        logger.warning(f"[register_passkey] Credential already exists: {credential_id}")
                        raise HTTPException(
                            status_code=400,
                            detail="Credential already registered"
                        )

                    # 新規登録
                    credential = await PasskeyCredentialCRUD.create(session, {
                        "credential_id": credential_id,
                        "user_id": user_id,
                        "public_key_cose": public_key_cose_b64,
                        "counter": 0,  # 初期値
                        "transports": transports
                    })

                logger.info(f"[register_passkey] Passkey registered: {credential_id[:16]}...")

                return {
                    "success": True,
                    "credential_id": credential_id,
                    "message": "Passkey registered successfully"
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[register_passkey] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.post("/verify/attestation")
        async def verify_attestation(request: AttestationVerifyRequest):
            """
            POST /verify/attestation - WebAuthn attestation検証

            demo_app_v2.md:
            リクエスト： { payment_mandate: {...}, attestation: {...} }

            処理： WebAuthn attestation の検証（公開鍵検証・authenticatorData, clientDataJSONの検証等）

            レスポンス： { verified: true/false, token?: "...", details?: {...} }
            """
            try:
                payment_mandate = request.payment_mandate
                attestation = request.attestation

                # WebAuthn検証（ap2_crypto.DeviceAttestationManagerを使用）
                challenge = attestation.get("challenge", "")
                credential_id = attestation.get("rawId")  # WebAuthnのcredential ID

                if not credential_id:
                    logger.error("[verify_attestation] Missing credential_id (rawId)")
                    return AttestationVerifyResponse(
                        verified=False,
                        details={"error": "Missing credential_id"}
                    )

                # データベースから登録済みPasskeyを取得
                async with self.db_manager.get_session() as session:
                    passkey_credential = await PasskeyCredentialCRUD.get_by_credential_id(
                        session, credential_id
                    )

                    if not passkey_credential:
                        logger.error(f"[verify_attestation] Passkey not found: {credential_id[:16]}...")
                        return AttestationVerifyResponse(
                            verified=False,
                            details={"error": "Passkey not registered"}
                        )

                    logger.info(f"[verify_attestation] Found passkey: {credential_id[:16]}...")
                    logger.info(f"  User: {passkey_credential.user_id}")
                    logger.info(f"  Counter: {passkey_credential.counter}")

                    # WebAuthn署名検証（完全な暗号学的検証）
                    verified, new_counter = self.attestation_manager.verify_webauthn_signature(
                        webauthn_auth_result=attestation,
                        challenge=challenge,
                        public_key_cose_b64=passkey_credential.public_key_cose,
                        stored_counter=passkey_credential.counter,
                        rp_id="localhost"
                    )

                    if verified:
                        # Signature counterを更新（リプレイ攻撃対策）
                        await PasskeyCredentialCRUD.update_counter(
                            session, credential_id, new_counter
                        )

                        logger.info(f"[verify_attestation] Signature counter updated: {passkey_credential.counter} → {new_counter}")

                        # トークン発行
                        token = self._generate_token(payment_mandate, attestation)

                        # データベースに保存
                        await self._save_attestation(
                            user_id=payment_mandate.get("payer_id", "unknown"),
                            attestation_raw=attestation,
                            verified=True,
                            token=token
                        )

                        return AttestationVerifyResponse(
                            verified=True,
                            token=token,
                            details={
                                "attestation_type": attestation.get("attestation_type", "passkey"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "counter": new_counter
                            }
                        )
                    else:
                        # 検証失敗
                        await self._save_attestation(
                            user_id=payment_mandate.get("payer_id", "unknown"),
                            attestation_raw=attestation,
                            verified=False
                        )

                        return AttestationVerifyResponse(
                            verified=False,
                            details={
                                "error": "Attestation verification failed (signature invalid)"
                            }
                        )

            except Exception as e:
                logger.error(f"[verify_attestation] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.get("/payment-methods")
        async def get_payment_methods(user_id: str):
            """
            GET /payment-methods?user_id=... - 支払い方法一覧取得
            """
            try:
                methods = self.payment_methods.get(user_id, [])
                return {
                    "user_id": user_id,
                    "payment_methods": methods
                }

            except Exception as e:
                logger.error(f"[get_payment_methods] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/payment-methods")
        async def add_payment_method(method_request: Dict[str, Any]):
            """
            POST /payment-methods - 支払い方法追加
            """
            try:
                user_id = method_request["user_id"]
                payment_method = method_request["payment_method"]

                # ID生成
                payment_method["id"] = f"pm_{uuid.uuid4().hex[:8]}"

                # 保存
                if user_id not in self.payment_methods:
                    self.payment_methods[user_id] = []
                self.payment_methods[user_id].append(payment_method)

                return {
                    "payment_method": payment_method,
                    "message": "Payment method added successfully"
                }

            except Exception as e:
                logger.error(f"[add_payment_method] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_payment_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """PaymentMandateを受信（Shopping Agentから）"""
        logger.info("[CredentialProvider] Received PaymentMandate")
        payment_mandate = message.dataPart.payload

        # 簡易応答（実際はデバイス証明を待つ）
        return {
            "type": "ap2/Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "payment_mandate_id": payment_mandate.get("id"),
                "message": "Please provide device attestation"
            }
        }

    async def handle_attestation_request(self, message: A2AMessage) -> Dict[str, Any]:
        """Attestationリクエストを受信"""
        logger.info("[CredentialProvider] Received AttestationRequest")
        request_data = message.dataPart.payload

        # チャレンジ生成
        challenge = self.attestation_manager.generate_challenge()

        return {
            "type": "ap2/AttestationChallenge",
            "id": str(uuid.uuid4()),
            "payload": {
                "challenge": challenge,
                "rp_id": "localhost",
                "timeout": 60000  # 60秒
            }
        }

    # ========================================
    # 内部メソッド
    # ========================================

    def _generate_token(self, payment_mandate: Dict[str, Any], attestation: Dict[str, Any]) -> str:
        """
        トークン発行

        簡易版：UUIDベースのトークン
        本番環境ではJWT等を使用
        """
        token_data = {
            "payment_mandate_id": payment_mandate.get("id"),
            "user_id": payment_mandate.get("payer_id"),
            "attestation_type": attestation.get("attestation_type", "passkey"),
            "issued_at": datetime.now(timezone.utc).isoformat()
        }

        # 簡易トークン（Base64エンコードされたJSON）
        import base64
        token = base64.b64encode(json.dumps(token_data).encode()).decode()

        logger.info(f"[CredentialProvider] Generated token for user: {payment_mandate.get('payer_id')}")

        return f"cred_token_{token[:32]}"

    async def _save_attestation(
        self,
        user_id: str,
        attestation_raw: Dict[str, Any],
        verified: bool,
        token: Optional[str] = None
    ):
        """
        Attestationをデータベースに保存
        """
        from sqlalchemy import Column, String, Integer, DateTime, Text
        from v2.common.database import Base

        # AttestationDBモデルを使用してSQLAlchemyに保存
        async with self.db_manager.get_session() as session:
            from v2.common.database import Attestation

            attestation_record = Attestation(
                id=str(uuid.uuid4()),
                user_id=user_id,
                attestation_raw=json.dumps(attestation_raw),
                verified=1 if verified else 0,  # SQLiteはboolを0/1で保存
                verification_details=json.dumps({
                    "token": token,
                    "verified_at": datetime.now(timezone.utc).isoformat()
                }) if token else None
            )

            session.add(attestation_record)
            await session.commit()

        logger.info(f"[CredentialProvider] Saved attestation: user={user_id}, verified={verified}")
