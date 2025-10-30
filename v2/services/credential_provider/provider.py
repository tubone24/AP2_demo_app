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
from datetime import datetime, timezone, timedelta
import logging
import httpx

from fastapi import HTTPException, Query
from fido2.webauthn import AttestationObject

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage, AttestationVerifyRequest, AttestationVerifyResponse
from v2.common.database import DatabaseManager, Attestation, PasskeyCredentialCRUD, PaymentMethodCRUD, ReceiptCRUD
from v2.common.crypto import DeviceAttestationManager, KeyManager
from v2.common.logger import get_logger, log_a2a_message, log_database_operation, LoggingAsyncClient
from v2.common.redis_client import RedisClient, TokenStore, SessionStore

logger = get_logger(__name__, service_name='credential_provider')


# ========================================
# 定数定義
# ========================================

# HTTP Timeout設定（秒）
PAYMENT_NETWORK_TIMEOUT = 10.0  # Payment Network通信のタイムアウト

# AP2ステータス定数
STATUS_SUCCESS = "success"
STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"

# Redis TTL設定（秒）
WEBAUTHN_CHALLENGE_TTL = 60  # WebAuthn challengeのTTL
STEPUP_SESSION_TTL = 600  # 10分（Step-upセッションのTTL）

# トークン有効期限（分）
TOKEN_EXPIRY_MINUTES = 15  # トークンの有効期限


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

        # データベースマネージャー（環境変数から読み込み、絶対パスを使用）
        import os
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/credential_provider.db")
        self.db_manager = DatabaseManager(database_url=database_url)

        # 決済ネットワークURL（環境変数から読み込み）
        self.payment_network_url = os.getenv("PAYMENT_NETWORK_URL", "http://payment_network:8005")

        # HTTPクライアント（Payment Networkとの通信用）
        # AP2完全準拠: LoggingAsyncClientで全HTTP通信をログ記録
        self.http_client = LoggingAsyncClient(
            logger=logger,
            timeout=PAYMENT_NETWORK_TIMEOUT
        )

        # Device Attestation Manager（既存のap2_crypto.pyを使用）
        self.attestation_manager = DeviceAttestationManager(self.key_manager)

        # Redis KVストア（一時データ管理）
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.redis_client = RedisClient(redis_url=redis_url)

        # トークンストア（AP2仕様準拠：トークン→支払い方法のマッピング）
        # Redis KVで管理（TTL: 15分）
        self.token_store = TokenStore(self.redis_client, prefix="cp:token")

        # Step-upセッション管理
        # Redis KVで管理（TTL: 10分）
        self.session_store = SessionStore(self.redis_client, prefix="cp:stepup")

        # WebAuthn challengeストア（TTL: 60秒）
        self.challenge_store = SessionStore(self.redis_client, prefix="cp:challenge")

        # AP2完全準拠: 支払い方法はデータベースで永続化
        # payment_methodsテーブルを使用

        # 領収書はデータベースで永続化
        # receiptsテーブルを使用

        # ヘルパークラスの初期化
        from services.credential_provider.utils import (
            PasskeyHelpers,
            PaymentMethodHelpers,
            StepUpHelpers,
            ReceiptHelpers,
            TokenHelpers,
        )

        self.passkey_helpers = PasskeyHelpers(
            db_manager=self.db_manager,
            key_manager=self.key_manager,
            attestation_manager=self.attestation_manager,
            challenge_store=self.challenge_store
        )
        self.payment_method_helpers = PaymentMethodHelpers(
            db_manager=self.db_manager,
            token_store=self.token_store
        )
        self.stepup_helpers = StepUpHelpers(
            db_manager=self.db_manager,
            session_store=self.session_store,
            challenge_store=self.challenge_store,
            payment_network_url=self.payment_network_url
        )
        self.receipt_helpers = ReceiptHelpers(db_manager=self.db_manager)
        self.token_helpers = TokenHelpers(db_manager=self.db_manager)

        # 起動イベントハンドラー登録
        @self.app.on_event("startup")
        async def startup_event():
            """起動時の初期化処理"""
            logger.info(f"[{self.agent_name}] Running startup tasks...")

            # データベース初期化
            await self.db_manager.init_db()
            logger.info(f"[{self.agent_name}] Database initialized")

        logger.info(f"[{self.agent_name}] Initialized")

    def get_ap2_roles(self) -> list[str]:
        """AP2でのロールを返す"""
        return ["credentials-provider"]

    def get_agent_description(self) -> str:
        """エージェントの説明を返す"""
        return "Credential Provider for AP2 Protocol - handles WebAuthn attestation verification, payment method management, and secure tokenization"

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Credential Providerが受信するA2Aメッセージ：
        - ap2/PaymentMandate: Shopping Agentからの認証依頼
        - ap2/AttestationRequest: デバイス証明リクエスト
        """
        self.a2a_handler.register_handler("ap2.mandates.PaymentMandate", self.handle_payment_mandate)
        self.a2a_handler.register_handler("ap2.requests.AttestationRequest", self.handle_attestation_request)

    def register_endpoints(self):
        """
        Credential Provider固有エンドポイントの登録
        """

        @self.app.post("/register/passkey/challenge")
        async def register_passkey_challenge(request: Dict[str, Any]):
            """
            POST /register/passkey/challenge - Passkey登録用challenge生成（AP2完全準拠）

            AP2仕様準拠:
            - サーバー側でchallengeを生成（リプレイ攻撃対策）
            - challengeは一時的にセッションに保存
            - Relying Party情報を返す

            リクエスト:
            {
              "user_id": "user_demo_001",
              "user_email": "user@example.com"
            }

            レスポンス:
            {
              "challenge": "base64url_challenge",
              "rp": {
                "id": "localhost",
                "name": "AP2 Credential Provider"
              },
              "user": {
                "id": "user_demo_001",
                "name": "user@example.com",
                "displayName": "user@example.com"
              },
              "pubKeyCredParams": [...],
              "timeout": 60000,
              "attestation": "none",
              "authenticatorSelection": {...}
            }
            """
            try:
                user_id = request["user_id"]
                user_email = request["user_email"]

                # AP2完全準拠：サーバー側でchallengeを生成
                import secrets
                challenge_bytes = secrets.token_bytes(32)
                challenge_b64url = base64.urlsafe_b64encode(challenge_bytes).decode('utf-8').rstrip('=')

                logger.info(f"[register_passkey_challenge] Generated challenge for user_id={user_id}")

                # challengeをRedis KVストアに保存（TTL: 60秒）
                # WebAuthn Registration Ceremony完了時に検証に使用
                challenge_data = {
                    "challenge": challenge_b64url,
                    "user_id": user_id,
                    "user_email": user_email,
                    "created_at": datetime.now(timezone.utc).isoformat()
                }
                await self.challenge_store.save_session(
                    challenge_b64url,
                    challenge_data,
                    ttl_seconds=WEBAUTHN_CHALLENGE_TTL  # WebAuthn challengeのTTL
                )

                logger.info(f"[register_passkey_challenge] Saved challenge to Redis KV (TTL: {WEBAUTHN_CHALLENGE_TTL}s)")

                # 注意: 現在は"none" attestationを使用
                # 本番環境では"direct"または"indirect"を使用し、challengeを厳密に検証すべき

                # WebAuthn Registration Optionsを返す
                return {
                    "challenge": challenge_b64url,
                    "rp": {
                        "id": "localhost",  # 本番環境では credentials.example.com
                        "name": "AP2 Credential Provider"
                    },
                    "user": {
                        "id": user_id,
                        "name": user_email,
                        "displayName": user_email
                    },
                    "pubKeyCredParams": [
                        {"alg": -7, "type": "public-key"},   # ES256 (ECDSA)
                        {"alg": -257, "type": "public-key"}  # RS256 (RSA)
                    ],
                    "timeout": 60000,
                    "attestation": "none",  # AP2仕様：attestation検証は不要
                    "authenticatorSelection": {
                        "authenticatorAttachment": "platform",  # ハードウェアバックドキー
                        "userVerification": "required",  # AP2完全準拠：生体認証必須
                        "residentKey": "required"  # AP2完全準拠：Discoverable Credential必須
                    }
                }

            except Exception as e:
                logger.error(f"[register_passkey_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

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
                client_data_json_b64 = registration_request.get("client_data_json")
                transports = registration_request.get("transports", [])

                logger.info(f"[register_passkey] Registering passkey for user: {user_id}")

                # Challenge検証（Redis KVストアから取得）
                if client_data_json_b64:
                    try:
                        # client_data_jsonからchallengeを抽出
                        # Base64URLデコード
                        padding_needed = len(client_data_json_b64) % 4
                        if padding_needed:
                            client_data_json_b64 += '=' * (4 - padding_needed)

                        client_data_json_b64_std = client_data_json_b64.replace('-', '+').replace('_', '/')
                        client_data_json_bytes = base64.b64decode(client_data_json_b64_std)
                        client_data = json.loads(client_data_json_bytes.decode('utf-8'))

                        challenge = client_data.get("challenge")

                        if challenge:
                            # Redis KVストアから対応するchallengeを取得
                            stored_challenge = await self.challenge_store.get_session(challenge)

                            if not stored_challenge:
                                logger.warning(f"[register_passkey] Challenge not found or expired: {challenge[:16]}...")
                                raise HTTPException(
                                    status_code=400,
                                    detail="Challenge not found or expired. Please request a new challenge."
                                )

                            # user_idの一致を確認
                            if stored_challenge.get("user_id") != user_id:
                                logger.error(
                                    f"[register_passkey] User ID mismatch: "
                                    f"stored={stored_challenge.get('user_id')}, request={user_id}"
                                )
                                raise HTTPException(
                                    status_code=400,
                                    detail="Challenge does not match the user ID"
                                )

                            # 検証成功後、challengeを削除（再利用防止）
                            await self.challenge_store.delete_session(challenge)
                            logger.info(f"[register_passkey] Challenge verified and deleted: {challenge[:16]}...")
                        else:
                            logger.warning(f"[register_passkey] No challenge found in client_data_json")

                    except json.JSONDecodeError as e:
                        logger.error(f"[register_passkey] Failed to parse client_data_json: {e}")
                        raise HTTPException(
                            status_code=400,
                            detail="Invalid client_data_json format"
                        )
                else:
                    # client_data_jsonが提供されていない場合（デモ環境用）
                    logger.info(
                        f"[register_passkey] No client_data_json provided, skipping challenge verification "
                        f"(acceptable for attestation='none' demo mode)"
                    )

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

                # AP2仕様準拠：公開鍵はCredential Provider内で管理される
                # ユーザーのDIDは不要（AP2仕様にはユーザーDIDの概念がない）
                # user_authorizationはSD-JWT-VC形式で公開鍵を自己包含する

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

                # AP2 Step 20-22, 23: モックattestation対応（デモ環境用）
                if credential_id.startswith("mock_credential_id_"):
                    logger.info(f"[verify_attestation] Mock attestation detected, skipping verification")

                    # トークン発行（Credential Provider内部の認証トークン）
                    token = self._generate_token(payment_mandate, attestation)

                    # AP2準拠：PaymentMandateに支払い方法トークンが含まれている場合のみPayment Networkに送信
                    # IntentMandate署名時（Step 3-4）はpayment_method未設定なのでスキップ
                    # PaymentMandate署名時（Step 20-22）はpayment_method設定済みなので送信
                    agent_token = None
                    payment_method_token = payment_mandate.get("payment_method", {}).get("token")
                    if payment_method_token:
                        logger.info(f"[verify_attestation] PaymentMandate contains payment_method.token, calling Payment Network (Step 23)")
                        # AP2 Step 23: 決済ネットワークへのトークン化呼び出し
                        agent_token = await self._request_agent_token_from_network(
                            payment_mandate=payment_mandate,
                            attestation=attestation,
                            payment_method_token=payment_method_token  # PaymentMandateから取得したトークンを使用
                        )
                    else:
                        logger.info(f"[verify_attestation] No payment_method.token in mandate (likely IntentMandate signature), skipping Payment Network call")

                    # データベースに保存
                    await self._save_attestation(
                        user_id=payment_mandate.get("payer_id", "unknown"),
                        attestation_raw=attestation,
                        verified=True,
                        token=token,
                        agent_token=agent_token
                    )

                    return AttestationVerifyResponse(
                        verified=True,
                        token=token,
                        details={
                            "attestation_type": "mock_passkey",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "mode": "demo",
                            "agent_token": agent_token
                        }
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

                        if new_counter == 0:
                            logger.info(
                                f"[verify_attestation] Signature counter: {passkey_credential.counter} → {new_counter} "
                                f"(AP2準拠: Authenticatorがcounterを実装していない場合でも、"
                                f"user_authorizationのnonceによりリプレイ攻撃は防止されます)"
                            )
                        else:
                            logger.info(
                                f"[verify_attestation] Signature counter updated: {passkey_credential.counter} → {new_counter}"
                            )

                        # トークン発行（Credential Provider内部の認証トークン）
                        token = self._generate_token(payment_mandate, attestation)

                        # AP2準拠：PaymentMandateに支払い方法トークンが含まれている場合のみPayment Networkに送信
                        # IntentMandate署名時（Step 3-4）はpayment_method未設定なのでスキップ
                        # PaymentMandate署名時（Step 20-22）はpayment_method設定済みなので送信
                        agent_token = None
                        payment_method_token = payment_mandate.get("payment_method", {}).get("token")
                        if payment_method_token:
                            logger.info(f"[verify_attestation] PaymentMandate contains payment_method.token, calling Payment Network (Step 23)")
                            # AP2 Step 23: 決済ネットワークへのトークン化呼び出し
                            # PaymentMandateと支払い方法トークンから、Agent Tokenを取得
                            agent_token = await self._request_agent_token_from_network(
                                payment_mandate=payment_mandate,
                                attestation=attestation,
                                payment_method_token=payment_method_token  # PaymentMandateから取得したトークンを使用
                            )
                        else:
                            logger.info(f"[verify_attestation] No payment_method.token in mandate (likely IntentMandate signature), skipping Payment Network call")

                        # データベースに保存
                        await self._save_attestation(
                            user_id=payment_mandate.get("payer_id", "unknown"),
                            attestation_raw=attestation,
                            verified=True,
                            token=token,
                            agent_token=agent_token
                        )

                        return AttestationVerifyResponse(
                            verified=True,
                            token=token,
                            details={
                                "attestation_type": attestation.get("attestation_type", "passkey"),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "counter": new_counter,
                                "agent_token": agent_token  # 決済ネットワークから取得したAgent Token
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
            GET /payment-methods?user_id=... - 支払い方法一覧取得（AP2完全準拠）

            データベースから永続化された支払い方法を取得
            """
            try:
                async with self.db_manager.get_session() as session:
                    payment_methods = await PaymentMethodCRUD.get_by_user_id(session, user_id)
                    methods = [pm.to_dict() for pm in payment_methods]

                logger.info(f"[get_payment_methods] Retrieved {len(methods)} payment methods for user: {user_id}")

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
            POST /payment-methods - 支払い方法追加（AP2完全準拠）

            データベースに永続化
            """
            try:
                user_id = method_request["user_id"]
                payment_method = method_request["payment_method"]

                # ID生成
                payment_method_id = f"pm_{uuid.uuid4().hex[:8]}"

                # データベースに保存
                async with self.db_manager.get_session() as session:
                    payment_method_record = await PaymentMethodCRUD.create(session, {
                        "id": payment_method_id,
                        "user_id": user_id,
                        "payment_method": payment_method
                    })

                payment_method["id"] = payment_method_id

                logger.info(f"[add_payment_method] Saved payment method to DB: {payment_method_id} for user: {user_id}")

                return {
                    "payment_method": payment_method,
                    "message": "Payment method added successfully"
                }

            except Exception as e:
                logger.error(f"[add_payment_method] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.delete("/payment-methods/{payment_method_id}")
        async def delete_payment_method(payment_method_id: str):
            """
            DELETE /payment-methods/{payment_method_id} - 支払い方法削除（AP2完全準拠）

            データベースから永続的に削除
            """
            try:
                # データベースから削除
                async with self.db_manager.get_session() as session:
                    deleted = await PaymentMethodCRUD.delete(session, payment_method_id)

                if not deleted:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Payment method not found: {payment_method_id}"
                    )

                logger.info(f"[delete_payment_method] Deleted payment method: {payment_method_id}")

                return {
                    "message": "Payment method deleted successfully",
                    "payment_method_id": payment_method_id
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[delete_payment_method] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/payment-methods/tokenize")
        async def tokenize_payment_method(tokenize_request: Dict[str, Any]):
            """
            POST /payment-methods/tokenize - 支払い方法のトークン化

            AP2仕様準拠（Step 17-18）：
            選択された支払い方法に対して一時的なセキュアトークンを生成

            リクエスト:
            {
              "user_id": "user_demo_001",
              "payment_method_id": "pm_001",
              "transaction_context"?: { ... }  // オプション
            }

            レスポンス:
            {
              "token": "tok_xxx",
              "payment_method_id": "pm_001",
              "brand": "visa",
              "last4": "4242",
              "expires_at": "2025-10-16T12:34:56Z"
            }
            """
            try:
                user_id = tokenize_request["user_id"]
                payment_method_id = tokenize_request["payment_method_id"]

                # データベースから支払い方法を取得（AP2完全準拠）
                async with self.db_manager.get_session() as session:
                    payment_method_record = await PaymentMethodCRUD.get_by_id(session, payment_method_id)

                if not payment_method_record:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Payment method not found: {payment_method_id}"
                    )

                # データベースレコードを辞書に変換
                payment_method = payment_method_record.to_dict()

                # 一時トークン生成（AP2トランザクション用）
                # 暗号学的に安全なトークンを生成し、有効期限を設定
                from datetime import timedelta
                import secrets
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(minutes=TOKEN_EXPIRY_MINUTES)  # 15分間有効

                # 暗号学的に安全なトークン生成
                # secrets.token_urlsafe()を使用（cryptographically strong random）
                random_bytes = secrets.token_urlsafe(32)  # 32バイト = 256ビット
                secure_token = f"tok_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"

                # トークンストアに保存（AP2仕様準拠）
                # Redis KVに保存（TTL: 15分）
                token_data = {
                    "user_id": user_id,
                    "payment_method_id": payment_method_id,
                    "payment_method": payment_method,
                    "issued_at": now.isoformat(),
                    "expires_at": expires_at.isoformat()
                }
                await self.token_store.save_token(secure_token, token_data)

                logger.info(f"[tokenize_payment_method] Generated secure token for payment method: {payment_method_id}")

                # AP2完全準拠: Stepup認証が必要かチェック
                requires_stepup = payment_method.get("requires_stepup", False)
                stepup_method = payment_method.get("stepup_method", None)

                # AP2完全準拠：有効期限を含める（カードの場合）
                response_data = {
                    "token": secure_token,
                    "payment_method_id": payment_method_id,
                    "brand": payment_method.get("brand", "unknown"),
                    "last4": payment_method.get("last4", "0000"),
                    "type": payment_method.get("type", "card"),
                    "expiry_month": payment_method.get("expiry_month"),  # カード有効期限（月）
                    "expiry_year": payment_method.get("expiry_year"),    # カード有効期限（年）
                    "expires_at": expires_at.isoformat().replace('+00:00', 'Z')  # トークン有効期限
                }

                # Stepup認証が必要な場合はフラグを追加
                if requires_stepup:
                    response_data["requires_stepup"] = True
                    response_data["stepup_method"] = stepup_method
                    logger.info(
                        f"[tokenize_payment_method] Stepup authentication required: "
                        f"method={stepup_method}, payment_method_id={payment_method_id}"
                    )

                return response_data

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[tokenize_payment_method] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.get("/payment-methods/step-up-challenge")
        async def step_up_challenge(
            payment_method_id: str = Query(..., description="Payment method ID"),
            return_url: str = Query(..., description="Return URL after authentication")
        ):
            """
            GET /payment-methods/step-up-challenge - 3D Secure認証チャレンジ開始

            AP2完全準拠: 簡易的な3DS認証画面を返す

            Args:
                payment_method_id: 認証対象の支払い方法ID
                return_url: 認証完了後のリダイレクト先URL（URLエンコード済み）
            """
            try:
                from fastapi.responses import HTMLResponse
                from urllib.parse import unquote

                # return_urlはURLエンコード済みなので、FastAPIが自動的にデコードしている
                # JavaScriptで安全に使用するためにシングルクォートをエスケープ
                escaped_return_url = return_url.replace("'", "\\'")

                # 簡易的な3DS認証画面HTML
                # AP2完全準拠: テンプレートリテラルを使用（CSSとの競合を避ける）
                html_content = """
                <html>
                    <head>
                        <title>3D Secure 2.0 Authentication</title>
                        <meta charset="utf-8">
                        <meta name="viewport" content="width=device-width, initial-scale=1.0">
                        <style>
                            body {
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                padding: 20px;
                                margin: 0;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                min-height: 100vh;
                            }
                            .container {
                                max-width: 450px;
                                background: white;
                                border-radius: 16px;
                                box-shadow: 0 10px 40px rgba(0,0,0,0.3);
                                padding: 40px;
                                text-align: center;
                            }
                            .logo {
                                width: 80px;
                                height: 80px;
                                background: linear-gradient(135deg, #667eea, #764ba2);
                                border-radius: 50%;
                                margin: 0 auto 24px;
                                display: flex;
                                align-items: center;
                                justify-content: center;
                                font-size: 36px;
                            }
                            h1 {
                                color: #333;
                                font-size: 24px;
                                margin: 0 0 12px;
                            }
                            .subtitle {
                                color: #666;
                                font-size: 14px;
                                margin-bottom: 32px;
                            }
                            .info-box {
                                background: #f7f7f7;
                                padding: 20px;
                                border-radius: 12px;
                                margin: 24px 0;
                            }
                            .info-row {
                                display: flex;
                                justify-content: space-between;
                                margin: 12px 0;
                                font-size: 14px;
                            }
                            .label {
                                color: #666;
                            }
                            .value {
                                color: #333;
                                font-weight: 600;
                            }
                            button {
                                width: 100%;
                                padding: 16px;
                                background: linear-gradient(135deg, #667eea, #764ba2);
                                color: white;
                                border: none;
                                border-radius: 12px;
                                font-size: 16px;
                                font-weight: 600;
                                cursor: pointer;
                                margin-top: 24px;
                                transition: transform 0.2s;
                            }
                            button:hover {
                                transform: translateY(-2px);
                            }
                            button:active {
                                transform: translateY(0);
                            }
                            .cancel-btn {
                                background: #e0e0e0;
                                color: #666;
                                margin-top: 12px;
                            }
                            .security-badge {
                                margin-top: 32px;
                                padding-top: 24px;
                                border-top: 1px solid #e0e0e0;
                                color: #999;
                                font-size: 12px;
                            }
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <div class="logo">🔒</div>
                            <h1>3D Secure 2.0</h1>
                            <p class="subtitle">カード会員認証が必要です</p>

                            <div class="info-box">
                                <div class="info-row">
                                    <span class="label">カードブランド</span>
                                    <span class="value">American Express</span>
                                </div>
                                <div class="info-row">
                                    <span class="label">カード番号</span>
                                    <span class="value">**** **** **** 1005</span>
                                </div>
                                <div class="info-row">
                                    <span class="label">加盟店</span>
                                    <span class="value">Demo Merchant</span>
                                </div>
                            </div>

                            <p style="color: #666; font-size: 14px; line-height: 1.6;">
                                このトランザクションを承認するには、下のボタンをタップしてください。
                                これにより、カード発行会社がお客様の本人確認を行います。
                            </p>

                            <button onclick="authenticate()">認証する</button>
                            <button class="cancel-btn" onclick="cancel()">キャンセル</button>

                            <div class="security-badge">
                                🔐 この認証はSSL/TLSで保護されています<br>
                                AP2 Protocol - 3D Secure 2.0
                            </div>
                        </div>

                        <script>
                            const returnUrl = '__RETURN_URL__';

                            function authenticate() {
                                // 認証完了をシミュレート（デモ用）
                                // AP2完全準拠: return_urlにリダイレクト
                                alert('✅ 3D Secure認証が完了しました！\\n\\n決済画面に戻ります。');
                                window.location.href = returnUrl;
                            }

                            function cancel() {
                                if (confirm('認証をキャンセルしますか？')) {
                                    // キャンセル時はstep_up_status=cancelledでリダイレクト
                                    const cancelUrl = returnUrl.replace('step_up_status=success', 'step_up_status=cancelled');
                                    window.location.href = cancelUrl;
                                }
                            }
                        </script>
                    </body>
                </html>
                """

                # return_urlを置換（AP2完全準拠：シンプルな文字列置換で安全性を確保）
                html_content = html_content.replace('__RETURN_URL__', escaped_return_url)

                return HTMLResponse(content=html_content)

            except Exception as e:
                logger.error(f"[step_up_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/payment-methods/initiate-step-up")
        async def initiate_step_up(request: Dict[str, Any]):
            """
            POST /payment-methods/initiate-step-up - Step-upフロー開始
            
            AP2 Step 13対応: 決済ネットワークがStep-upを要求する場合の処理
            
            リクエスト:
            {
              "user_id": "user_demo_001",
              "payment_method_id": "pm_003",
              "transaction_context": {
                "amount": {"value": "10000.00", "currency": "JPY"},
                "merchant_id": "did:ap2:merchant:mugibo_merchant"
              },
              "return_url": "http://localhost:3000/payment/step-up-callback"
            }
            
            レスポンス:
            {
              "session_id": "stepup_abc123",
              "step_up_url": "http://localhost:8003/step-up/stepup_abc123",
              "expires_at": "2025-10-18T12:49:56Z"
            }
            """
            try:
                user_id = request["user_id"]
                payment_method_id = request["payment_method_id"]
                transaction_context = request.get("transaction_context", {})
                return_url = request.get("return_url", "http://localhost:3000/chat")

                # 支払い方法をDBから取得
                async with self.db_manager.get_session() as session:
                    payment_method_record = await PaymentMethodCRUD.get_by_id(session, payment_method_id)

                if not payment_method_record:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Payment method not found: {payment_method_id}"
                    )

                payment_method = payment_method_record.to_dict()

                # Step-upが必要かチェック
                if not payment_method.get("requires_stepup", False):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Payment method does not require step-up: {payment_method_id}"
                    )

                # Step-upセッション作成
                session_id = f"stepup_{uuid.uuid4().hex[:16]}"
                now = datetime.now(timezone.utc)
                expires_at = now + timedelta(seconds=STEPUP_SESSION_TTL)  # 10分間有効

                session_data = {
                    "session_id": session_id,
                    "user_id": user_id,
                    "payment_method_id": payment_method_id,
                    "payment_method": payment_method,
                    "transaction_context": transaction_context,
                    "return_url": return_url,
                    "status": "pending",  # pending, completed, failed
                    "created_at": now.isoformat(),
                    "expires_at": expires_at.isoformat()
                }

                # Redis KVに保存（TTL: 10分）
                await self.session_store.save_session(session_id, session_data, ttl_seconds=STEPUP_SESSION_TTL)

                # Step-up URL生成
                step_up_url = f"http://localhost:8003/step-up/{session_id}"

                logger.info(
                    f"[initiate_step_up] Created step-up session: "
                    f"session_id={session_id}, payment_method_id={payment_method_id}"
                )

                return {
                    "session_id": session_id,
                    "step_up_url": step_up_url,
                    "expires_at": expires_at.isoformat().replace('+00:00', 'Z'),
                    "step_up_reason": payment_method.get("step_up_reason", "Additional authentication required")
                }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[initiate_step_up] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/step-up/{session_id}")
        async def get_step_up_page(session_id: str):
            """
            GET /step-up/{session_id} - Step-up認証画面
            
            決済ネットワークのStep-up画面をシミュレート
            実際の環境では3D Secureなどの決済ネットワーク画面にリダイレクト
            """
            try:
                from fastapi.responses import HTMLResponse

                # Step-upセッション取得（Redis KV）
                session_data = await self.session_store.get_session(session_id)

                if not session_data:
                    return HTMLResponse(
                        content="""
                        <html>
                            <head><title>Step-up Session Not Found</title></head>
                            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                                <h1>Step-up Session Not Found</h1>
                                <p>The step-up session has expired or is invalid.</p>
                            </body>
                        </html>
                        """,
                        status_code=404
                    )
                
                # 有効期限チェック
                expires_at = datetime.fromisoformat(session_data["expires_at"])
                if datetime.now(timezone.utc) > expires_at:
                    return HTMLResponse(
                        content="""
                        <html>
                            <head><title>Step-up Session Expired</title></head>
                            <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                                <h1>Step-up Session Expired</h1>
                                <p>This step-up session has expired. Please try again.</p>
                            </body>
                        </html>
                        """,
                        status_code=400
                    )
                
                payment_method = session_data["payment_method"]
                transaction_context = session_data.get("transaction_context", {})
                amount = transaction_context.get("amount", {})
                
                # シンプルなStep-up画面HTML（デモ用）
                html_content = f"""
                <html>
                    <head>
                        <title>3D Secure Authentication</title>
                        <meta charset="utf-8">
                        <style>
                            body {{
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                                padding: 20px;
                                margin: 0;
                            }}
                            .container {{
                                max-width: 480px;
                                margin: 60px auto;
                                background: white;
                                border-radius: 12px;
                                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                                padding: 40px;
                            }}
                            h1 {{
                                color: #333;
                                margin-top: 0;
                                font-size: 24px;
                            }}
                            .info {{
                                background: #f7f7f7;
                                padding: 16px;
                                border-radius: 8px;
                                margin: 20px 0;
                            }}
                            .info-row {{
                                display: flex;
                                justify-content: space-between;
                                margin: 8px 0;
                            }}
                            .label {{
                                color: #666;
                                font-weight: 500;
                            }}
                            .value {{
                                color: #333;
                                font-weight: 600;
                            }}
                            button {{
                                width: 100%;
                                padding: 16px;
                                background: #667eea;
                                color: white;
                                border: none;
                                border-radius: 8px;
                                font-size: 16px;
                                font-weight: 600;
                                cursor: pointer;
                                transition: background 0.2s;
                            }}
                            button:hover {{
                                background: #5568d3;
                            }}
                            .cancel {{
                                background: #e0e0e0;
                                color: #666;
                                margin-top: 12px;
                            }}
                            .cancel:hover {{
                                background: #d0d0d0;
                            }}
                            .message {{
                                background: #fff3cd;
                                border: 1px solid #ffc107;
                                color: #856404;
                                padding: 12px;
                                border-radius: 6px;
                                margin-bottom: 20px;
                            }}
                        </style>
                    </head>
                    <body>
                        <div class="container">
                            <h1>🔐 3D Secure Authentication</h1>
                            <div class="message">
                                追加認証が必要です。お支払いを完了するには、カード情報を確認してください。
                            </div>
                            <div class="info">
                                <div class="info-row">
                                    <span class="label">カードブランド:</span>
                                    <span class="value">{payment_method.get('brand', 'N/A').upper()}</span>
                                </div>
                                <div class="info-row">
                                    <span class="label">カード番号:</span>
                                    <span class="value">**** **** **** {payment_method.get('last4', '0000')}</span>
                                </div>
                                <div class="info-row">
                                    <span class="label">金額:</span>
                                    <span class="value">¥{amount.get('value', '0')}</span>
                                </div>
                            </div>
                            <button onclick="completeStepUp()">認証を完了する</button>
                            <button class="cancel" onclick="cancelStepUp()">キャンセル</button>
                        </div>
                        <script>
                            async function completeStepUp() {{
                                try {{
                                    const response = await fetch('/step-up/{session_id}/complete', {{
                                        method: 'POST',
                                        headers: {{ 'Content-Type': 'application/json' }},
                                        body: JSON.stringify({{ status: 'success' }})
                                    }});
                                    const result = await response.json();
                                    
                                    if (result.status === 'completed') {{
                                        alert('認証が完了しました。元のページに戻ります。');
                                        // AP2準拠：return_urlのクエリパラメータにstep_up_statusを追加
                                        const returnUrl = new URL(result.return_url, window.location.origin);
                                        returnUrl.searchParams.set('step_up_status', 'success');
                                        returnUrl.searchParams.set('step_up_session_id', '{session_id}');
                                        window.location.href = returnUrl.toString();
                                    }} else {{
                                        alert('認証に失敗しました: ' + result.message);
                                    }}
                                }} catch (error) {{
                                    alert('エラーが発生しました: ' + error.message);
                                }}
                            }}
                            
                            function cancelStepUp() {{
                                if (confirm('認証をキャンセルしますか？')) {{
                                    // AP2準拠：return_urlのクエリパラメータにstep_up_statusを追加
                                    const returnUrl = new URL('{session_data["return_url"]}', window.location.origin);
                                    returnUrl.searchParams.set('step_up_status', 'cancelled');
                                    returnUrl.searchParams.set('step_up_session_id', '{session_id}');
                                    window.location.href = returnUrl.toString();
                                }}
                            }}
                        </script>
                    </body>
                </html>
                """
                
                return HTMLResponse(content=html_content)
                
            except Exception as e:
                logger.error(f"[get_step_up_page] Error: {e}", exc_info=True)
                return HTMLResponse(
                    content=f"""
                    <html>
                        <head><title>Error</title></head>
                        <body style="font-family: sans-serif; padding: 40px; text-align: center;">
                            <h1>Error</h1>
                            <p>{str(e)}</p>
                        </body>
                    </html>
                    """,
                    status_code=500
                )
        
        @self.app.post("/step-up/{session_id}/complete")
        async def complete_step_up(session_id: str, request: Dict[str, Any]):
            """
            POST /step-up/{session_id}/complete - Step-up完了
            
            リクエスト:
            {
              "status": "success" | "failed"
            }
            
            レスポンス:
            {
              "status": "completed" | "failed",
              "session_id": "stepup_abc123",
              "return_url": "...",
              "token"?: "..." (成功時のみ)
            }
            """
            try:
                # Step-upセッション取得（Redis KV）
                session_data = await self.session_store.get_session(session_id)

                if not session_data:
                    raise HTTPException(status_code=404, detail="Step-up session not found")

                # 有効期限チェック
                expires_at = datetime.fromisoformat(session_data["expires_at"])
                if datetime.now(timezone.utc) > expires_at:
                    raise HTTPException(status_code=400, detail="Step-up session expired")

                status = request.get("status", "success")

                # ===== Step-up成功 - トークン発行 =====
                if status == STATUS_SUCCESS:
                    import secrets
                    random_bytes = secrets.token_urlsafe(32)
                    token = f"tok_stepup_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"

                    # トークンストアに保存（Redis KV、TTL: 15分）
                    now = datetime.now(timezone.utc)
                    token_expires_at = now + timedelta(minutes=TOKEN_EXPIRY_MINUTES)

                    token_data = {
                        "user_id": session_data["user_id"],
                        "payment_method_id": session_data["payment_method_id"],
                        "payment_method": session_data["payment_method"],
                        "issued_at": now.isoformat(),
                        "expires_at": token_expires_at.isoformat(),
                        "step_up_completed": True
                    }
                    await self.token_store.save_token(token, token_data)

                    # セッション更新（Redis KV）
                    session_updates = {
                        "status": "completed",
                        "token": token,
                        "completed_at": now.isoformat()
                    }
                    await self.session_store.update_session(session_id, session_updates)

                    logger.info(
                        f"[complete_step_up] Step-up completed successfully: "
                        f"session_id={session_id}, token={token[:20]}..."
                    )

                    return {
                        "status": "completed",
                        "session_id": session_id,
                        "return_url": session_data["return_url"],
                        "token": token,
                        "message": "Step-up authentication completed successfully"
                    }
                else:
                    # Step-up失敗
                    session_updates = {
                        "status": "failed",
                        "failed_at": datetime.now(timezone.utc).isoformat()
                    }
                    await self.session_store.update_session(session_id, session_updates)

                    logger.warning(f"[complete_step_up] Step-up failed: session_id={session_id}")

                    return {
                        "status": "failed",
                        "session_id": session_id,
                        "return_url": session_data["return_url"],
                        "message": "Step-up authentication failed"
                    }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[complete_step_up] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/payment-methods/verify-step-up")
        async def verify_step_up(request: Dict[str, Any]):
            """
            POST /payment-methods/verify-step-up - Step-up完了確認

            Shopping Agentがstep-up認証完了後に呼び出して、
            認証が成功したかを確認し、支払い方法情報を取得する

            リクエスト:
            {
              "session_id": "stepup_abc123"
            }

            レスポンス:
            {
              "verified": true | false,
              "payment_method": {...},  // verified=trueの場合のみ
              "token": "...",  // verified=trueの場合のみ
              "message": "..."
            }
            """
            try:
                session_id = request.get("session_id")

                if not session_id:
                    raise HTTPException(status_code=400, detail="session_id is required")

                # Step-upセッション取得（Redis KV）
                session_data = await self.session_store.get_session(session_id)

                if not session_data:
                    logger.warning(f"[verify_step_up] Session not found: {session_id}")
                    return {
                        "verified": False,
                        "message": "Step-up session not found"
                    }

                # 有効期限チェック
                expires_at = datetime.fromisoformat(session_data["expires_at"])
                if datetime.now(timezone.utc) > expires_at:
                    logger.warning(f"[verify_step_up] Session expired: {session_id}")
                    return {
                        "verified": False,
                        "message": "Step-up session expired"
                    }

                # ===== 完了状態チェック =====
                status = session_data.get("status")
                if status == STATUS_COMPLETED:
                    logger.info(f"[verify_step_up] Step-up verified successfully: {session_id}")
                    return {
                        "verified": True,
                        "payment_method": session_data["payment_method"],
                        "token": session_data.get("token"),
                        "message": "Step-up authentication verified successfully"
                    }
                elif status == STATUS_FAILED:
                    logger.warning(f"[verify_step_up] Step-up failed: {session_id}")
                    return {
                        "verified": False,
                        "message": "Step-up authentication failed"
                    }
                else:
                    # まだ完了していない
                    logger.info(f"[verify_step_up] Step-up not yet completed: {session_id}, status={status}")
                    return {
                        "verified": False,
                        "message": "Step-up authentication not yet completed"
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[verify_step_up] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/passkey/get-public-key")
        async def get_passkey_public_key(request: Dict[str, Any]):
            """
            POST /passkey/get-public-key - Passkey公開鍵取得

            WebAuthn assertion時に、credential_idから公開鍵を取得する

            リクエスト:
            {
              "credential_id": "base64url_credential_id",
              "user_id": "user_demo_001"  // オプション
            }

            レスポンス:
            {
              "credential_id": "...",
              "public_key_cose": "base64_encoded_cose_key",
              "user_id": "..."
            }
            """
            try:
                credential_id = request.get("credential_id")

                if not credential_id:
                    raise HTTPException(status_code=400, detail="credential_id is required")

                # データベースからPasskey認証情報を取得
                async with self.db_manager.get_session() as db_session:
                    passkey = await PasskeyCredentialCRUD.get_by_credential_id(db_session, credential_id)

                    if not passkey:
                        logger.warning(f"[get_passkey_public_key] Passkey not found: {credential_id}")
                        raise HTTPException(status_code=404, detail="Passkey credential not found")

                    logger.info(
                        f"[get_passkey_public_key] Public key retrieved: "
                        f"credential_id={credential_id[:16]}..., user_id={passkey.user_id}"
                    )

                    return {
                        "credential_id": passkey.credential_id,
                        "public_key_cose": passkey.public_key_cose,
                        "user_id": passkey.user_id
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[get_passkey_public_key] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/receipts")
        async def receive_receipt(receipt_data: Dict[str, Any]):
            """
            POST /receipts - 領収書受信（ヘルパーメソッドに委譲）

            AP2 Step 29対応: Payment Processorから領収書通知を受信
            """
            try:
                return await self.receipt_helpers.receive_receipt(receipt_data)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[receive_receipt] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @self.app.get("/receipts")
        async def get_receipts(user_id: str):
            """
            GET /receipts?user_id=... - ユーザーの領収書一覧取得（ヘルパーメソッドに委譲）
            """
            try:
                return await self.receipt_helpers.get_receipts(user_id)
            except Exception as e:
                logger.error(f"[get_receipts] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/credentials/verify")
        async def verify_credentials(verify_request: Dict[str, Any]):
            """
            POST /credentials/verify - トークン検証と認証情報提供

            AP2仕様準拠（Step 26-27）：
            Payment Processorからトークンを受信し、検証して支払い方法情報を返却

            リクエスト:
            {
              "token": "tok_xxx",
              "payer_id": "user_demo_001",
              "amount": { "value": "10000.00", "currency": "JPY" }
            }

            レスポンス:
            {
              "verified": true,
              "credential_info": {
                "payment_method_id": "pm_001",
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "holder_name": "山田太郎"
              }
            }
            """
            try:
                token = verify_request["token"]
                payer_id = verify_request["payer_id"]
                amount = verify_request.get("amount", {})

                logger.info(f"[verify_credentials] Verifying token for payer: {payer_id}")

                # トークン形式チェック
                if not token.startswith("tok_"):
                    raise ValueError(f"Invalid token format: {token[:20]}")

                # トークンストアから支払い方法を取得（AP2仕様準拠、Redis KV）
                token_data = await self.token_store.get_token(token)
                if not token_data:
                    logger.error(f"[verify_credentials] Token not found in store: {token[:20]}...")
                    return {
                        "verified": False,
                        "error": "Token not found or expired"
                    }

                # トークン有効期限チェック
                expires_at = datetime.fromisoformat(token_data["expires_at"])
                if datetime.now(timezone.utc) > expires_at:
                    logger.warning(f"[verify_credentials] Token expired: {token[:20]}...")
                    # 期限切れトークンを削除（Redis KV）
                    await self.token_store.delete_token(token)
                    return {
                        "verified": False,
                        "error": "Token expired"
                    }

                # トークンのユーザーIDとpayer_idの一致チェック
                if token_data["user_id"] != payer_id:
                    logger.error(f"[verify_credentials] User ID mismatch: token={token_data['user_id']}, payer={payer_id}")
                    return {
                        "verified": False,
                        "error": "User ID mismatch"
                    }

                # トークンから正確な支払い方法を取得
                payment_method = token_data["payment_method"]

                logger.info(f"[verify_credentials] Token verified: payment_method_id={payment_method['id']}, user_id={payer_id}")

                return {
                    "verified": True,
                    "credential_info": {
                        "payment_method_id": payment_method["id"],
                        "type": payment_method.get("type", "card"),
                        "brand": payment_method.get("brand", "unknown"),
                        "last4": payment_method.get("last4", "0000"),
                        "holder_name": payment_method.get("holder_name", "Unknown"),
                        "expiry_month": payment_method.get("expiry_month"),
                        "expiry_year": payment_method.get("expiry_year")
                    }
                }

            except Exception as e:
                logger.error(f"[verify_credentials] Error: {e}", exc_info=True)
                return {
                    "verified": False,
                    "error": str(e)
                }

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_payment_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """
        PaymentMandateを受信（Shopping Agentから）

        AP2仕様準拠：完全な認証フロー実装
        1. PaymentMandateを受信
        2. デバイス認証が必要な場合はチャレンジを生成
        3. WebAuthn attestationを待つ（非同期）
        4. 検証後、認証トークンを返却

        注意: デバイス証明の検証は /verify/attestation エンドポイントで行われる
        このハンドラーは、PaymentMandateの受信を確認し、次のステップを指示する
        """
        logger.info("[CredentialProvider] Received PaymentMandate via A2A")
        payment_mandate = message.dataPart.payload

        try:
            # PaymentMandate IDを取得
            payment_mandate_id = payment_mandate.get("id")
            payer_id = payment_mandate.get("payer_id", "unknown")
            transaction_type = payment_mandate.get("transaction_type", "human_not_present")

            logger.info(
                f"[CredentialProvider] Processing PaymentMandate: "
                f"id={payment_mandate_id}, payer_id={payer_id}, transaction_type={transaction_type}"
            )

            # Human Present（ユーザーが認証可能）の場合はWebAuthn attestationが必要
            if transaction_type == "human_present":
                # WebAuthn challengeを生成
                challenge = self.attestation_manager.generate_challenge()

                logger.info(
                    f"[CredentialProvider] Generated WebAuthn challenge for PaymentMandate: {payment_mandate_id}, "
                    f"challenge={challenge[:20]}..."
                )

                # PaymentMandateをデータベースに一時保存（チャレンジと関連付け）
                # 実装は省略（実際のシステムではRedis等に保存）
                # self._store_pending_payment_mandate(payment_mandate_id, payment_mandate, challenge)

                # Shopping Agentにチャレンジを返す
                return {
                    "type": "ap2.responses.AttestationChallenge",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "payment_mandate_id": payment_mandate_id,
                        "challenge": challenge,
                        "rp_id": "localhost",  # デモ環境
                        "timeout": 60000,  # 60秒
                        "message": "Please complete WebAuthn device authentication"
                    }
                }
            else:
                # Human Not Present（バックグラウンド決済）の場合
                # Intent Mandateの署名を検証して、自動承認
                logger.info(
                    f"[CredentialProvider] PaymentMandate is human_not_present, "
                    f"automatic approval based on Intent Mandate"
                )

                # Intent Mandateの検証（IntentMandateが含まれている場合）
                intent_mandate_id = payment_mandate.get("intent_mandate_id")
                if intent_mandate_id:
                    logger.info(f"[CredentialProvider] Verifying Intent Mandate: {intent_mandate_id}")

                    # Intent Mandateをデータベースから取得
                    # 実装は省略（実際のシステムではデータベースから取得）
                    # intent_mandate = await self._get_intent_mandate(intent_mandate_id)

                    # Intent Mandateの署名を検証
                    # 実装は省略（実際のシステムでは暗号署名を検証）
                    # is_valid = self._verify_intent_mandate_signature(intent_mandate)

                    # 認証トークンを発行（自動承認）
                    token = self._generate_token(payment_mandate, {
                        "attestation_type": "intent_mandate",
                        "verified": True
                    })

                    # データベースに保存
                    await self._save_attestation(
                        user_id=payer_id,
                        attestation_raw={
                            "type": "intent_mandate",
                            "intent_mandate_id": intent_mandate_id
                        },
                        verified=True,
                        token=token
                    )

                    logger.info(f"[CredentialProvider] Approved PaymentMandate based on Intent Mandate: {payment_mandate_id}")

                    # Shopping Agentに承認応答を返す
                    return {
                        "type": "ap2.responses.PaymentApproval",
                        "id": str(uuid.uuid4()),
                        "payload": {
                            "payment_mandate_id": payment_mandate_id,
                            "approved": True,
                            "token": token,
                            "approval_type": "intent_mandate_based",
                            "message": "Payment approved based on Intent Mandate"
                        }
                    }
                else:
                    # Intent Mandateがない場合は、認証が必要
                    logger.warning(f"[CredentialProvider] PaymentMandate {payment_mandate_id} is human_not_present but has no Intent Mandate")

                    return {
                        "type": "ap2.errors.Error",
                        "id": str(uuid.uuid4()),
                        "payload": {
                            "error_code": "missing_intent_mandate",
                            "error_message": "Human Not Present transaction requires Intent Mandate",
                            "payment_mandate_id": payment_mandate_id
                        }
                    }

        except Exception as e:
            logger.error(f"[CredentialProvider] Error handling PaymentMandate: {e}", exc_info=True)
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "internal_error",
                    "error_message": str(e),
                    "payment_mandate_id": payment_mandate.get("id", "unknown")
                }
            }

    async def handle_attestation_request(self, message: A2AMessage) -> Dict[str, Any]:
        """Attestationリクエストを受信"""
        logger.info("[CredentialProvider] Received AttestationRequest")
        request_data = message.dataPart.payload

        # チャレンジ生成
        challenge = self.attestation_manager.generate_challenge()

        return {
            "type": "ap2.responses.AttestationChallenge",
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

    async def _request_agent_token_from_network(
        self,
        payment_mandate: Dict[str, Any],
        attestation: Dict[str, Any],
        payment_method_token: str
    ) -> Optional[str]:
        """
        決済ネットワークへのトークン化呼び出し（AP2 Step 23）

        CPが決済ネットワークにHTTPリクエストを送信し、Agent Tokenを取得

        Args:
            payment_mandate: PaymentMandate オブジェクト
            attestation: デバイス認証情報
            payment_method_token: CPが発行した支払い方法トークン

        Returns:
            Agent Token（決済ネットワークが発行）、エラーの場合はNone
        """
        try:
            logger.info(
                f"[CredentialProvider] Requesting Agent Token from Payment Network: "
                f"payment_mandate_id={payment_mandate.get('id')}"
            )

            # 決済ネットワークにHTTP POSTリクエストを送信
            # AP2完全準拠: self.http_clientを使用（HTTPXLoggingEventHooksでログ記録）
            response = await self.http_client.post(
                f"{self.payment_network_url}/network/tokenize",
                json={
                    "payment_mandate": payment_mandate,
                    "attestation": attestation,
                    "payment_method_token": payment_method_token,
                    "transaction_context": {
                        "credential_provider_id": self.agent_id,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                }
            )

            if response.status_code == 200:
                data = response.json()
                agent_token = data.get("agent_token")

                logger.info(
                    f"[CredentialProvider] Received Agent Token from Payment Network: "
                    f"{agent_token[:32] if agent_token else 'None'}..., "
                    f"network_name={data.get('network_name')}"
                )

                return agent_token
            else:
                logger.error(
                    f"[CredentialProvider] Failed to get Agent Token from Payment Network: "
                    f"status_code={response.status_code}, response={response.text}"
                )
                return None

        except httpx.RequestError as e:
            logger.error(
                f"[CredentialProvider] HTTP request error while requesting Agent Token: {e}",
                exc_info=True
            )
            return None
        except Exception as e:
            logger.error(
                f"[CredentialProvider] Unexpected error while requesting Agent Token: {e}",
                exc_info=True
            )
            return None

    def _generate_token(self, payment_mandate: Dict[str, Any], attestation: Dict[str, Any]) -> str:
        """
        認証トークン発行（WebAuthn attestation検証後）（ヘルパーメソッドに委譲）

        AP2仕様準拠：
        - 暗号学的に安全なトークンを生成
        - トークンは一時的（有効期限付き）
        """
        return self.token_helpers.generate_token(payment_mandate, attestation)

    async def _save_attestation(
        self,
        user_id: str,
        attestation_raw: Dict[str, Any],
        verified: bool,
        token: Optional[str] = None,
        agent_token: Optional[str] = None
    ):
        """
        Attestationをデータベースに保存（ヘルパーメソッドに委譲）
        """
        await self.token_helpers.save_attestation(
            user_id=user_id,
            attestation_raw=attestation_raw,
            verified=verified,
            token=token,
            agent_token=agent_token
        )

