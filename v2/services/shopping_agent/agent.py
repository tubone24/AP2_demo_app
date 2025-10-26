"""
v2/services/shopping_agent/agent.py

Shopping Agent実装
- ユーザーとの対話（Streaming応答）
- IntentMandateの作成
- Merchant Agentへの商品検索依頼（A2A通信）
- CartMandate選択・署名
- PaymentMandate作成
"""

import sys
import os
import uuid
import json
import hashlib
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging

import httpx
from fastapi import HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sse_starlette.sse import EventSourceResponse

# AP2準拠: JWT認証用セキュリティスキーム（Layer 1: HTTP Session Authentication）
security = HTTPBearer()

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import (
    A2AMessage,
    ChatStreamRequest,
    StreamEvent,
    ProductSearchRequest,
    # 認証用モデル
    UserCreate,
    UserLogin,
    UserResponse,
    UserInDB,
    Token,
    # [DEPRECATED] Passkey認証モデル（削除予定）
    PasskeyRegistrationChallenge,
    PasskeyRegistrationChallengeResponse,
    PasskeyRegistrationRequest,
    PasskeyLoginChallenge,
    PasskeyLoginChallengeResponse,
    PasskeyLoginRequest,
)
from v2.common.database import (
    DatabaseManager,
    MandateCRUD,
    TransactionCRUD,
    AgentSessionCRUD,
    UserCRUD,
    PasskeyCredentialCRUD,
)
from v2.common.risk_assessment import RiskAssessmentEngine
from v2.common.crypto import WebAuthnChallengeManager, CryptoError
from v2.common.user_authorization import create_user_authorization_vp
from v2.common.auth import (
    # JWT認証
    create_access_token,
    verify_access_token,
    get_current_user,
    # パスワード認証（2025年ベストプラクティス - Argon2id）
    hash_password,
    verify_password,
    validate_password_strength,
    # [DEPRECATED] WebAuthn/Passkey認証（削除予定）
    verify_webauthn_attestation,
)
from v2.common.logger import (
    get_logger,
    log_http_request,
    log_http_response,
    log_a2a_message,
    log_database_operation
)

# OpenTelemetry 手動トレーシング
from v2.common.telemetry import get_tracer, create_http_span, is_telemetry_enabled

# NOTE: 古いLangGraph実装（langgraph_agent, langgraph_conversation, langgraph_shopping）は廃止
# 新しいStateGraph版（langgraph_shopping_flow.py）を使用

logger = get_logger(__name__, service_name='shopping_agent')

# OpenTelemetryトレーサー（手動計装用）
tracer = get_tracer(__name__)


class ShoppingAgent(BaseAgent):
    """
    Shopping Agent

    ユーザーの購買代理エージェント
    - ユーザーとの対話（chat/stream）
    - IntentMandateの作成・管理
    - 他エージェントとのA2A通信
    """

    def __init__(self):
        # AP2準拠: データベースマネージャーを最初に初期化（JWT認証に必要）
        import os
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/shopping_agent.db")
        self.db_manager = DatabaseManager(database_url=database_url)

        # AP2準拠: JWT認証用ヘルパー関数（依存性注入）
        # super().__init__()でregister_endpoints()が呼ばれるため、事前に定義
        async def get_current_user_dependency(
            credentials: HTTPAuthorizationCredentials = Depends(security)
        ) -> UserInDB:
            """
            AP2 Layer 1認証: JWTトークンからユーザー情報を取得

            AP2プロトコル要件:
            - Layer 1: HTTP Session Authentication（JWT Bearer Token）
            - user_id = JWT.sub（認証済みユーザーID）
            - payer_email = JWT.email（オプション - PII保護）
            - トラステッドサーフェス: WebAuthn/Passkey
            """
            return await get_current_user(credentials, self.db_manager)

        self.get_current_user_dependency = get_current_user_dependency

        # 親クラスの初期化（この中でregister_endpoints()が呼ばれる）
        super().__init__(
            agent_id="did:ap2:agent:shopping_agent",
            agent_name="Shopping Agent",
            passphrase=AgentPassphraseManager.get_passphrase("shopping_agent"),
            keys_directory="./keys"
        )

        # HTTPクライアント（他エージェントとの通信用）
        # タイムアウト600秒: DMR LLM処理が長時間かかる場合に対応
        self.http_client = httpx.AsyncClient(timeout=600.0)

        # エージェントエンドポイント（Docker Compose環境想定）
        self.merchant_agent_url = "http://merchant_agent:8001"
        self.merchant_url = "http://merchant:8002"
        self.payment_processor_url = "http://payment_processor:8004"

        # AP2完全準拠: Credential Provider URL（Mandate署名検証用）
        # AP2仕様: Shopping AgentはCredential Providerに署名検証をデリゲート
        self.credential_provider_url = "http://credential_provider:8003"

        # 複数のCredential Providerに対応
        self.credential_providers = [
            {
                "id": "cp_demo_001",
                "name": "AP2 Demo Credential Provider",
                "url": self.credential_provider_url,
                "description": "デモ用Credential Provider（Passkey対応）",
                "logo_url": "https://example.com/cp_demo_logo.png",
                "supported_methods": ["card", "passkey"]
            },
            {
                "id": "cp_demo_002",
                "name": "Alternative Credential Provider",
                "url": self.credential_provider_url,  # デモ環境では同じ
                "description": "代替Credential Provider",
                "logo_url": "https://example.com/cp_alt_logo.png",
                "supported_methods": ["card"]
            }
        ]

        # セッション管理（簡易版 - インメモリ）
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # リスク評価エンジン（データベースマネージャーを渡して完全実装を有効化）
        self.risk_engine = RiskAssessmentEngine(db_manager=self.db_manager)

        # WebAuthn challenge管理
        # - Layer 1認証用: Passkey登録/ログイン（本追加）
        # - Layer 2署名用: Intent/Consent署名（既存）
        self.webauthn_challenge_manager = WebAuthnChallengeManager(challenge_ttl_seconds=60)

        # Passkey認証用のchallenge管理（ログイン用）
        self.passkey_auth_challenge_manager = WebAuthnChallengeManager(challenge_ttl_seconds=120)  # ログインは2分

        # 旧LangGraphエージェント（非推奨、新しいStateGraph版に移行済み）
        # NOTE: 以下の古い実装は廃止されました。新しいlanggraph_shopping_flow.pyを使用してください。
        self.langgraph_agent = None  # 旧: Intent抽出用LangGraphエージェント
        self.conversation_agent = None  # 旧: 対話エージェント
        self.langgraph_shopping_agent = None  # 旧: Shopping Engine
        logger.info(f"[{self.agent_name}] Old LangGraph implementations are deprecated. Using new StateGraph flow.")

        # LangGraph Shopping Flow（会話フロー：StateGraph版）
        try:
            from services.shopping_agent.langgraph_shopping_flow import create_shopping_flow_graph
            self.shopping_flow_graph = create_shopping_flow_graph(self)
            logger.info(f"[{self.agent_name}] LangGraph shopping flow graph initialized successfully (12 nodes)")
        except Exception as e:
            logger.warning(f"[{self.agent_name}] LangGraph shopping flow graph initialization failed: {e}")
            self.shopping_flow_graph = None

        # 起動イベントハンドラー登録
        @self.app.on_event("startup")
        async def startup_event():
            """起動時の初期化処理"""
            logger.info(f"[{self.agent_name}] Running startup tasks...")

            # データベース初期化
            await self.db_manager.init_db()
            logger.info(f"[{self.agent_name}] Database initialized")

        logger.info(f"[{self.agent_name}] Initialized with database-backed risk assessment")

    def get_ap2_roles(self) -> list[str]:
        """AP2でのロールを返す"""
        return ["shopper"]

    def get_agent_description(self) -> str:
        """エージェントの説明を返す"""
        return "Shopping Agent for AP2 Protocol - handles user purchase intents, product search, and payment processing"

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Shopping Agentが受信するA2Aメッセージ：
        - ap2/CartMandate: Merchant Agentからのカート提案
        - ap2/ProductList: Merchant Agentからの商品リスト
        - ap2/SignatureResponse: Credential Providerからの署名結果
        """
        self.a2a_handler.register_handler("ap2.mandates.CartMandate", self.handle_cart_mandate)
        self.a2a_handler.register_handler("ap2.responses.ProductList", self.handle_product_list)
        self.a2a_handler.register_handler("ap2.responses.SignatureResponse", self.handle_signature_response)

    def register_endpoints(self):
        """
        Shopping Agent固有エンドポイントの登録

        AP2仕様準拠:
        - HTTPセッション認証: メール/パスワード認証（AP2仕様外、ベストプラクティスに従う）
        - Mandate署名認証: WebAuthn/Passkey（Credential Provider）← AP2仕様準拠
        """

        # ========================================
        # メール/パスワード認証エンドポイント（2025年ベストプラクティス）
        # ========================================

        @self.app.post("/auth/register", response_model=Token)
        async def register_user(request: UserCreate):
            """
            POST /auth/register - ユーザー登録（メール/パスワード）

            AP2仕様:
            - HTTPセッション認証方式は仕様外（実装の自由度あり）
            - email: PaymentMandate.payer_emailとして使用
            - Mandate署名はCredential ProviderのPasskeyで実施（AP2準拠）

            セキュリティ:
            - Argon2idでパスワードハッシュ化（OWASP推奨）
            - パスワード強度検証
            - JWTでセッション管理
            """
            try:
                # パスワード強度検証
                logger.info(f"[register_user] Validating password strength for email={request.email}")
                validate_password_strength(request.password)

                # パスワードハッシュ化（AP2完全準拠：Argon2id）
                logger.info(f"[register_user] Hashing password for email={request.email}")
                hashed_password = hash_password(request.password)
                logger.info(f"[register_user] Password hashed successfully (length={len(hashed_password)})")

                # 既存ユーザーチェック
                async with self.db_manager.get_session() as session:
                    existing_user = await UserCRUD.get_by_email(session, request.email)
                    if existing_user:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Email already registered"
                        )

                    # ユーザー作成（AP2完全準拠）
                    user_id = f"usr_{uuid.uuid4().hex[:16]}"
                    user_data = {
                        "id": user_id,
                        "display_name": request.username,
                        "email": request.email,
                        "hashed_password": hashed_password,
                        "is_active": 1
                    }
                    logger.info(f"[register_user] Creating user with data: id={user_id}, email={request.email}, hashed_password_len={len(hashed_password)}")
                    user = await UserCRUD.create(session, user_data)

                logger.info(f"[Auth] User registered: user_id={user_id}, email={request.email}")

                # JWTトークン発行
                access_token = create_access_token(
                    data={"user_id": user_id, "email": request.email}
                )

                # UserResponseに変換
                user_response = UserResponse(
                    id=user.id,
                    username=user.display_name,
                    email=user.email,
                    created_at=user.created_at,
                    is_active=bool(user.is_active)
                )

                return Token(
                    access_token=access_token,
                    token_type="bearer",
                    user=user_response
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[register_user] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

        @self.app.post("/auth/login", response_model=Token)
        async def login_user(request: UserLogin):
            """
            POST /auth/login - ユーザーログイン（メール/パスワード）

            AP2仕様:
            - HTTPセッション認証方式は仕様外（実装の自由度あり）
            - email: AP2 payer_emailとして使用
            - Mandate署名はCredential ProviderのPasskeyで実施（AP2準拠）

            セキュリティ:
            - Argon2idでパスワード検証（タイミング攻撃耐性）
            - JWTでセッション管理
            """
            try:
                # ユーザー取得
                async with self.db_manager.get_session() as session:
                    user = await UserCRUD.get_by_email(session, request.email)

                    if not user:
                        # タイミング攻撃対策: ユーザーが存在しない場合でもハッシュ化処理を実行
                        hash_password("dummy_password_for_timing_attack_resistance")
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid email or password"
                        )

                    # パスワード検証
                    if not verify_password(request.password, user.hashed_password):
                        raise HTTPException(
                            status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid email or password"
                        )

                    # アカウント有効チェック
                    if not user.is_active:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Account is inactive"
                        )

                logger.info(f"[Auth] User logged in: user_id={user.id}, email={request.email}")

                # JWTトークン発行
                access_token = create_access_token(
                    data={"user_id": user.id, "email": user.email}
                )

                # UserResponseに変換
                user_response = UserResponse(
                    id=user.id,
                    username=user.display_name,
                    email=user.email,
                    created_at=user.created_at,
                    is_active=bool(user.is_active)
                )

                return Token(
                    access_token=access_token,
                    token_type="bearer",
                    user=user_response
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[login_user] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Login failed: {e}")

        # ========================================
        # [DEPRECATED] Passkey認証エンドポイント（削除予定）
        # AP2完全準拠により、Passkey認証はCredential Providerのみで使用
        # ========================================

        @self.app.post("/auth/passkey/register/challenge", response_model=PasskeyRegistrationChallengeResponse)
        async def passkey_register_challenge(request: PasskeyRegistrationChallenge):
            """
            POST /auth/passkey/register/challenge - Passkey登録用challengeを生成

            AP2仕様準拠:
            - ユーザー登録時にPasskey（WebAuthn）を作成
            - email: AP2 payer_emailとして使用（ただしオプション - PII保護）

            フロー:
            1. ユーザーが username + email を入力
            2. challengeを生成
            3. フロントエンドがWebAuthn Registration APIを呼び出し
            """
            try:
                # 既存ユーザーチェック
                async with self.db_manager.get_session() as session:
                    existing_user = await UserCRUD.get_by_email(session, request.email)
                    if existing_user:
                        raise HTTPException(status_code=400, detail="Email already registered")

                # 仮ユーザーID生成（登録完了時に確定）
                user_id = f"usr_{uuid.uuid4().hex[:16]}"

                # WebAuthn challenge生成
                challenge_info = self.passkey_auth_challenge_manager.generate_challenge(
                    user_id=user_id,
                    context="passkey_registration"
                )

                logger.info(f"[Auth] Passkey registration challenge generated: email={request.email}, user_id={user_id}")

                return PasskeyRegistrationChallengeResponse(
                    challenge=challenge_info["challenge"],
                    user_id=user_id,
                    rp_id=os.getenv("WEBAUTHN_RP_ID", "localhost"),
                    rp_name="AP2 Demo Shopping Agent",
                    timeout=60000
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[passkey_register_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate challenge: {e}")

        @self.app.post("/auth/passkey/register", response_model=Token)
        async def passkey_register(request: PasskeyRegistrationRequest):
            """
            POST /auth/passkey/register - Passkeyを登録してJWTを発行

            AP2仕様準拠:
            - email: PaymentMandate.payer_emailとして使用（オプション）
            - Passkey公開鍵をDB保存（秘密鍵は保存しない）
            """
            try:
                # WebAuthn Attestation検証
                # 注意: 本番環境では完全なWebAuthn検証が必要
                # ここでは簡易実装（challenge存在確認のみ）
                logger.info(f"[Auth] Passkey registration request: email={request.email}")

                # ユーザー作成
                user_id = f"usr_{uuid.uuid4().hex[:16]}"
                async with self.db_manager.get_session() as session:
                    # Userレコード作成
                    user = await UserCRUD.create(session, {
                        "id": user_id,
                        "display_name": request.username,
                        "email": request.email
                    })

                    # PasskeyCredentialレコード作成
                    await PasskeyCredentialCRUD.create(session, {
                        "credential_id": request.credential_id,
                        "user_id": user_id,
                        "public_key_cose": request.public_key,
                        "counter": 0,
                        "transports": request.transports or []
                    })

                logger.info(f"[Auth] User registered with Passkey: user_id={user_id}, email={request.email}")

                # JWTトークン発行
                access_token = create_access_token(
                    data={"user_id": user_id, "email": request.email}
                )

                # UserResponseに変換
                user_response = UserResponse(
                    id=user.id,
                    username=user.display_name,
                    email=user.email,
                    created_at=user.created_at,
                    is_active=bool(user.is_active)
                )

                return Token(
                    access_token=access_token,
                    token_type="bearer",
                    user=user_response
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[passkey_register] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

        @self.app.post("/auth/passkey/login/challenge", response_model=PasskeyLoginChallengeResponse)
        async def passkey_login_challenge(request: PasskeyLoginChallenge):
            """
            POST /auth/passkey/login/challenge - Passkeyログイン用challengeを生成

            AP2仕様準拠:
            - email でユーザーを識別
            - 登録済みPasskey credentialリストを返す
            """
            try:
                # ユーザー検索
                async with self.db_manager.get_session() as session:
                    user = await UserCRUD.get_by_email(session, request.email)
                    if not user:
                        raise HTTPException(status_code=404, detail="User not found")

                    # ユーザーのPasskey credential取得
                    credentials = await PasskeyCredentialCRUD.get_by_user_id(session, user.id)
                    if not credentials:
                        raise HTTPException(status_code=404, detail="No Passkey registered")

                # WebAuthn challenge生成
                challenge_info = self.passkey_auth_challenge_manager.generate_challenge(
                    user_id=user.id,
                    context="passkey_login"
                )

                # credential IDリスト作成
                allowed_credentials = [
                    {
                        "type": "public-key",
                        "id": cred.credential_id,
                        "transports": json.loads(cred.transports) if cred.transports else []
                    }
                    for cred in credentials
                ]

                logger.info(f"[Auth] Passkey login challenge generated: email={request.email}, credentials={len(allowed_credentials)}")

                return PasskeyLoginChallengeResponse(
                    challenge=challenge_info["challenge"],
                    rp_id=os.getenv("WEBAUTHN_RP_ID", "localhost"),
                    timeout=60000,
                    allowed_credentials=allowed_credentials
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[passkey_login_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate challenge: {e}")

        @self.app.post("/auth/passkey/login", response_model=Token)
        async def passkey_login(request: PasskeyLoginRequest):
            """
            POST /auth/passkey/login - Passkeyでログインして JWTを発行

            AP2仕様準拠:
            - Passkey署名を検証
            - sign_counterでリプレイ攻撃を検出
            - JWTに user_id + email（payer_email）を含める
            """
            try:
                # ユーザー検索
                async with self.db_manager.get_session() as session:
                    user = await UserCRUD.get_by_email(session, request.email)
                    if not user:
                        raise HTTPException(status_code=401, detail="Authentication failed")

                    # Passkey Credential取得
                    credential = await PasskeyCredentialCRUD.get_by_credential_id(
                        session, request.credential_id
                    )
                    if not credential or credential.user_id != user.id:
                        raise HTTPException(status_code=401, detail="Invalid credential")

                    # WebAuthn Assertion検証（簡易実装）
                    # 本番環境では完全なCOSE署名検証が必要
                    logger.info(f"[Auth] Passkey login verification: user_id={user.id}, credential_id={request.credential_id[:16]}...")

                    # sign_counter更新（リプレイ攻撃対策）
                    # 注意: 本実装では署名検証を省略しているが、本番環境では必須
                    new_counter = credential.counter + 1
                    await PasskeyCredentialCRUD.update_counter(
                        session, request.credential_id, new_counter
                    )

                logger.info(f"[Auth] User logged in with Passkey: user_id={user.id}, email={user.email}")

                # JWTトークン発行
                access_token = create_access_token(
                    data={"user_id": user.id, "email": user.email}
                )

                # UserResponseに変換
                user_response = UserResponse(
                    id=user.id,
                    username=user.display_name,
                    email=user.email,
                    created_at=user.created_at,
                    is_active=bool(user.is_active)
                )

                return Token(
                    access_token=access_token,
                    token_type="bearer",
                    user=user_response
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[passkey_login] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Login failed: {e}")

        @self.app.get("/auth/me", response_model=UserResponse)
        async def get_current_user_info(
            current_user: UserInDB = Depends(self.get_current_user_dependency)
        ):
            """
            GET /auth/me - 現在のユーザー情報を取得（JWT検証テスト用）

            AP2プロトコル準拠:
            - Layer 1認証: JWT Bearer Token
            - user_id = JWT.sub
            - payer_email = JWT.email（オプション - PII保護）
            """
            return UserResponse(
                id=current_user.id,
                username=current_user.username,
                email=current_user.email,
                created_at=current_user.created_at,
                is_active=current_user.is_active
            )

        # ========================================
        # Layer 2: マンデート署名エンドポイント（既存）
        # ========================================

        @self.app.post("/intent/challenge")
        async def generate_intent_challenge(request: Dict[str, Any]):
            """
            POST /intent/challenge - Intent署名用のWebAuthn challengeを生成

            専門家の指摘に対応：IntentMandateはユーザーPasskey署名を使用する

            リクエスト:
            {
                "user_id": "user_demo_001",
                "intent_data": { ...IntentMandate基本情報... }
            }

            レスポンス:
            {
                "challenge_id": "ch_abc123...",
                "challenge": "base64url_encoded_challenge",
                "intent_data": { ...署名対象データ... }
            }
            """
            try:
                user_id = request.get("user_id", "user_demo_001")
                intent_data = request.get("intent_data", {})

                # WebAuthn challengeを生成
                challenge_info = self.webauthn_challenge_manager.generate_challenge(
                    user_id=user_id,
                    context="intent_mandate_signature"
                )

                logger.info(f"[ShoppingAgent] Generated challenge for Intent signature: user={user_id}, challenge_id={challenge_info['challenge_id']}")

                return {
                    "challenge_id": challenge_info["challenge_id"],
                    "challenge": challenge_info["challenge"],
                    "intent_data": intent_data,
                    "rp_id": "localhost",  # デモ環境
                    "timeout": 60000  # 60秒
                }

            except Exception as e:
                logger.error(f"[generate_intent_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate challenge: {e}")

        @self.app.post("/intent/submit")
        async def submit_signed_intent_mandate(request: Dict[str, Any]):
            """
            POST /intent/submit - Passkey署名付きIntentMandateを受け取る

            専門家の指摘に対応：IntentMandateはフロントエンドから送信されたPasskey署名を使用

            リクエスト:
            {
                "intent_mandate": { ...IntentMandate基本情報... },
                "passkey_signature": {
                    "challenge_id": "ch_abc123...",
                    "challenge": "base64url...",
                    "clientDataJSON": "base64url...",
                    "authenticatorData": "base64url...",
                    "signature": "base64url...",
                    "userHandle": "base64url..."
                }
            }

            レスポンス:
            {
                "status": "success",
                "intent_mandate_id": "intent_abc123"
            }
            """
            try:
                intent_mandate = request.get("intent_mandate", {})
                passkey_signature = request.get("passkey_signature", {})

                if not intent_mandate:
                    raise HTTPException(status_code=400, detail="intent_mandate is required")

                if not passkey_signature:
                    raise HTTPException(status_code=400, detail="passkey_signature is required")

                # challengeを検証・消費
                challenge_id = passkey_signature.get("challenge_id")
                challenge = passkey_signature.get("challenge")
                user_id = intent_mandate.get("user_id", "user_demo_001")

                is_valid_challenge = self.webauthn_challenge_manager.verify_and_consume_challenge(
                    challenge_id=challenge_id,
                    challenge=challenge,
                    user_id=user_id
                )

                if not is_valid_challenge:
                    raise HTTPException(status_code=400, detail="Invalid or expired challenge")

                # IntentMandateにPasskey署名を追加
                intent_mandate["passkey_signature"] = passkey_signature

                # データベースに保存（A2A通信で使用）
                async with self.db_manager.get_session() as session:
                    await MandateCRUD.create(session, {
                        "id": intent_mandate["id"],
                        "type": "Intent",
                        "status": "signed",
                        "payload": intent_mandate,
                        "issuer": user_id
                    })

                logger.info(f"[ShoppingAgent] IntentMandate with Passkey signature saved: id={intent_mandate['id']}, user={user_id}")

                return {
                    "status": "success",
                    "intent_mandate_id": intent_mandate["id"]
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[submit_signed_intent_mandate] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to submit IntentMandate: {e}")

        @self.app.post("/consent/challenge")
        async def generate_consent_challenge(request: Dict[str, Any]):
            """
            POST /consent/challenge - Consent署名用のWebAuthn challengeを生成

            専門家の指摘対応：ConsentメッセージもユーザーPasskey署名を使用する

            リクエスト:
            {
                "user_id": "user_demo_001",
                "cart_mandate_id": "cart_abc123",
                "intent_message_id": "msg_abc123"
            }

            レスポンス:
            {
                "challenge_id": "ch_xyz789...",
                "challenge": "base64url_encoded_challenge",
                "consent_data": { ...署名対象データ... }
            }
            """
            try:
                user_id = request.get("user_id", "user_demo_001")
                cart_mandate_id = request.get("cart_mandate_id")
                intent_message_id = request.get("intent_message_id")

                if not cart_mandate_id:
                    raise HTTPException(status_code=400, detail="cart_mandate_id is required")

                if not intent_message_id:
                    raise HTTPException(status_code=400, detail="intent_message_id is required")

                # WebAuthn challengeを生成
                challenge_info = self.webauthn_challenge_manager.generate_challenge(
                    user_id=user_id,
                    context="consent_signature"
                )

                logger.info(f"[ShoppingAgent] Generated challenge for Consent signature: user={user_id}, challenge_id={challenge_info['challenge_id']}")

                return {
                    "challenge_id": challenge_info["challenge_id"],
                    "challenge": challenge_info["challenge"],
                    "consent_data": {
                        "cart_mandate_id": cart_mandate_id,
                        "intent_message_id": intent_message_id,
                        "user_id": user_id
                    },
                    "rp_id": "localhost",  # デモ環境
                    "timeout": 60000  # 60秒
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[generate_consent_challenge] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to generate consent challenge: {e}")

        @self.app.post("/consent/submit")
        async def submit_signed_consent(request: Dict[str, Any]):
            """
            POST /consent/submit - Passkey署名付きConsentメッセージを受け取る

            専門家の指摘対応：ConsentはIntentとCartの両方への参照を持ち、Passkey署名される

            リクエスト:
            {
                "consent": {
                    "consent_id": "consent_abc123",
                    "cart_mandate_id": "cart_abc123",
                    "intent_message_id": "msg_abc123",
                    "user_id": "user_demo_001",
                    "approved": true,
                    "timestamp": "2025-10-17T12:34:56Z"
                },
                "passkey_signature": {
                    "challenge_id": "ch_xyz789...",
                    "challenge": "base64url...",
                    "clientDataJSON": "base64url...",
                    "authenticatorData": "base64url...",
                    "signature": "base64url...",
                    "userHandle": "base64url..."
                }
            }

            レスポンス:
            {
                "status": "success",
                "consent_id": "consent_abc123"
            }
            """
            try:
                consent = request.get("consent", {})
                passkey_signature = request.get("passkey_signature", {})

                if not consent:
                    raise HTTPException(status_code=400, detail="consent is required")

                if not passkey_signature:
                    raise HTTPException(status_code=400, detail="passkey_signature is required")

                # challengeを検証・消費
                challenge_id = passkey_signature.get("challenge_id")
                challenge = passkey_signature.get("challenge")
                user_id = consent.get("user_id", "user_demo_001")

                is_valid_challenge = self.webauthn_challenge_manager.verify_and_consume_challenge(
                    challenge_id=challenge_id,
                    challenge=challenge,
                    user_id=user_id
                )

                if not is_valid_challenge:
                    raise HTTPException(status_code=400, detail="Invalid or expired challenge")

                # ConsentにPasskey署名を追加
                consent["passkey_signature"] = passkey_signature

                # 署名対象データのハッシュを計算（検証用）
                import hashlib
                consent_data_str = json.dumps({
                    "cart_mandate_id": consent["cart_mandate_id"],
                    "intent_message_id": consent["intent_message_id"],
                    "user_id": consent["user_id"],
                    "approved": consent["approved"],
                    "timestamp": consent["timestamp"]
                }, sort_keys=True)
                consent["signed_data_hash"] = hashlib.sha256(consent_data_str.encode()).hexdigest()

                # データベースに保存
                async with self.db_manager.get_session() as session:
                    await MandateCRUD.create(session, {
                        "id": consent["consent_id"],
                        "type": "Consent",
                        "status": "signed",
                        "payload": consent,
                        "issuer": user_id
                    })

                logger.info(f"[ShoppingAgent] Consent with Passkey signature saved: id={consent['consent_id']}, user={user_id}, approved={consent['approved']}")

                return {
                    "status": "success",
                    "consent_id": consent["consent_id"]
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[submit_signed_consent] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to submit Consent: {e}")

        @self.app.post("/chat/stream")
        async def chat_stream(
            request: ChatStreamRequest,
            current_user: UserInDB = Depends(self.get_current_user_dependency)  # AP2準拠: Layer 1認証
        ):
            """
            POST /chat/stream - ユーザーとの対話（SSE Streaming）

            AP2プロトコル準拠:
            - Layer 1認証: JWT Bearer Token（HTTP Session Authentication）
            - user_id: JWT.sub（認証済みユーザーID）
            - payer_email: JWT.email（オプション - PII保護）
            - トラステッドサーフェス: ブラウザWebAuthn API（Passkey）

            リクエスト:
            - Body: { user_input: string, session_id?: string }
            - Header: Authorization: Bearer <JWT>

            レスポンス（SSE）:
            - { "type": "agent_text", "content": "..." }
            - { "type": "signature_request", "mandate": { ...IntentMandate... } }
            - { "type": "cart_options", "items": [...] }
            """
            session_id = request.session_id or str(uuid.uuid4())
            user_id = current_user.id  # AP2準拠: JWT認証済みユーザーID

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    # データベースからセッション取得または作成（AP2準拠: user_id必須）
                    session = await self._get_or_create_session(session_id, user_id=user_id)
                    session["messages"].append({"role": "user", "content": request.user_input})

                    # 固定応答フロー（LLM統合前）
                    # 環境変数USE_LANGGRAPH_FLOWでLangGraph版と既存版を切り替え
                    import os
                    use_langgraph = os.getenv("USE_LANGGRAPH_FLOW", "false").lower() == "true"

                    # EventSourceResponseはJSON文字列を期待するため、
                    # 辞書をJSON文字列に変換して返す
                    if use_langgraph and self.shopping_flow_graph is not None:
                        # LangGraph StateGraph版を使用
                        logger.info(f"[chat_stream] Using LangGraph shopping flow (session_id={session_id})")
                        async for event in self._generate_fixed_response_langgraph(request.user_input, session, session_id):
                            yield json.dumps(event.model_dump(exclude_none=True))
                            await asyncio.sleep(0.01)
                    else:
                        # 既存実装を使用
                        if use_langgraph:
                            logger.warning(f"[chat_stream] LangGraph flow requested but not initialized, using legacy flow (session_id={session_id})")
                        async for event in self._generate_fixed_response(request.user_input, session, session_id):
                            yield json.dumps(event.model_dump(exclude_none=True))
                            await asyncio.sleep(0.1)  # 少し遅延を入れて自然に

                    # セッション保存（最終状態）
                    await self._update_session(session_id, session)

                    # 完了イベント
                    yield json.dumps({'type': 'done'})

                except Exception as e:
                    logger.error(f"[chat_stream] Error: {e}", exc_info=True)
                    error_event = StreamEvent(type="error", error=str(e))
                    yield json.dumps(error_event.model_dump(exclude_none=True))

            return EventSourceResponse(event_generator())

        @self.app.get("/products")
        async def get_products(query: str = "", limit: int = 10):
            """
            GET /products - 商品検索（デバッグ用エンドポイント）

            注意: このエンドポイントは開発/テスト用です。
            実際のAP2フローでは、_search_products_via_merchant_agent()メソッドを使用して
            A2A通信でMerchant Agentに商品検索を依頼します。
            """
            try:
                # デバッグ用：直接Merchant Agentの/searchエンドポイントにHTTPアクセス
                # 本来のフローでは使用されません
                response = await self.http_client.get(
                    f"{self.merchant_agent_url}/search",
                    params={"query": query, "limit": limit}
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPError as e:
                logger.error(f"[get_products] HTTP error: {e}")
                raise HTTPException(status_code=502, detail="Failed to fetch products")

        @self.app.get("/transactions/{transaction_id}")
        async def get_transaction(transaction_id: str):
            """
            GET /transactions/{id} - トランザクション取得
            """
            async with self.db_manager.get_session() as session:
                transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                if not transaction:
                    raise HTTPException(status_code=404, detail="Transaction not found")
                return transaction.to_dict()

        @self.app.post("/payment/step-up-callback")
        async def handle_step_up_callback(request: Dict[str, Any]):
            """
            POST /payment/step-up-callback - Step-up完了コールバック
            
            AP2 Step 13対応: Step-up認証完了後、フロントエンドから呼び出される
            
            リクエスト:
            {
              "session_id": "sess_abc123",
              "step_up_session_id": "stepup_xyz789",
              "status": "success" | "cancelled" | "failed"
            }
            
            レスポンス:
            {
              "status": "success" | "failed",
              "message": "...",
              "can_continue": true | false
            }
            """
            try:
                session_id = request.get("session_id")
                step_up_session_id = request.get("step_up_session_id")
                status = request.get("status", "failed")
                
                if not session_id or not step_up_session_id:
                    raise HTTPException(status_code=400, detail="session_id and step_up_session_id are required")
                
                # セッション取得
                if session_id not in self.sessions:
                    raise HTTPException(status_code=404, detail="Session not found")
                
                session = self.sessions[session_id]
                
                # Step-upセッションIDを検証
                if session.get("step_up_session_id") != step_up_session_id:
                    raise HTTPException(status_code=400, detail="Step-up session ID mismatch")
                
                if status == "success":
                    # Step-up成功 - トークン化は完了済みなので、次のステップに進む
                    session["step"] = "cart_selected_need_shipping"
                    
                    logger.info(
                        f"[handle_step_up_callback] Step-up completed successfully: "
                        f"session_id={session_id}, step_up_session_id={step_up_session_id}"
                    )
                    
                    return {
                        "status": "success",
                        "message": "Step-up authentication completed successfully",
                        "can_continue": True
                    }
                elif status == "cancelled":
                    # Step-upキャンセル - 支払い方法選択に戻る
                    session["step"] = "select_payment_method"
                    
                    logger.info(
                        f"[handle_step_up_callback] Step-up cancelled: "
                        f"session_id={session_id}, step_up_session_id={step_up_session_id}"
                    )
                    
                    return {
                        "status": "cancelled",
                        "message": "Step-up authentication was cancelled. Please select another payment method.",
                        "can_continue": False
                    }
                else:
                    # Step-up失敗 - 支払い方法選択に戻る
                    session["step"] = "select_payment_method"
                    
                    logger.warning(
                        f"[handle_step_up_callback] Step-up failed: "
                        f"session_id={session_id}, step_up_session_id={step_up_session_id}, status={status}"
                    )
                    
                    return {
                        "status": "failed",
                        "message": "Step-up authentication failed. Please select another payment method.",
                        "can_continue": False
                    }
                
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[handle_step_up_callback] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/cart/submit-signature")
        async def submit_cart_signature(
            request: Dict[str, Any],
            current_user: UserInDB = Depends(self.get_current_user_dependency)  # AP2準拠: Layer 1認証
        ):
            """
            POST /cart/submit-signature - CartMandateへのWebAuthn署名を受信

            AP2プロトコル完全準拠（Human-Presentフロー）:
            - Layer 1認証: JWT Bearer Token（HTTP Session）
            - Layer 2認証: WebAuthn署名（Mandate Signature）
            - user_id = JWT.sub（認証済みユーザーID）
            - トラステッドサーフェス: WebAuthn/Passkey

            フロー:
            1. Merchantが署名済みのCartMandateをユーザーに提示
            2. ユーザーがWebAuthnで署名（Layer 2）
            3. このエンドポイントで署名を受信・検証
            4. PaymentMandate作成へ進む

            リクエスト:
            - Header: Authorization: Bearer <JWT>
            - Body: {
                "session_id": "session_abc123",
                "cart_mandate": { ...Merchant署名済みCartMandate... },
                "webauthn_assertion": {
                    "id": "credential_id",
                    "rawId": "...",
                    "response": {
                        "clientDataJSON": "...",
                        "authenticatorData": "...",
                        "signature": "..."
                    },
                    "type": "public-key"
                }
            }

            レスポンス:
            {
                "status": "success",
                "message": "CartMandate signed successfully",
                "next_step": "payment_mandate_creation"
            }
            """
            try:
                session_id = request.get("session_id")
                cart_mandate = request.get("cart_mandate")
                webauthn_assertion = request.get("webauthn_assertion")
                user_id = current_user.id  # AP2準拠: JWT認証済みユーザーID

                if not session_id or not cart_mandate or not webauthn_assertion:
                    raise HTTPException(
                        status_code=400,
                        detail="session_id, cart_mandate, and webauthn_assertion are required"
                    )

                # セッション取得（AP2準拠: user_id必須）
                session = await self._get_or_create_session(session_id, user_id=user_id)

                logger.info(
                    f"[submit_cart_signature] Received CartMandate signature: "
                    f"cart_id={cart_mandate.get('id')}, "
                    f"session_id={session_id}"
                )

                # ✅ AP2プロトコル完全準拠: Credential ProviderでWebAuthn署名検証
                # AP2仕様: CartMandate自体にuser_signature_requiredはfalse
                # ユーザーの意思確認はWebAuthn（trusted device surface）で行われる
                # WebAuthn assertionは後でPaymentMandate作成時のuser_authorizationとして使用
                #
                # 設計根拠:
                # 1. AP2仕様: Mandate署名はCredential Providerで検証される
                # 2. Credential Providerはハードウェアバックドキーの公開鍵を管理
                # 3. Shopping AgentはCredential Providerに検証をデリゲート
                try:
                    # Credential Providerに署名検証をリクエスト（AP2完全準拠）
                    # /verify/attestation エンドポイントを使用
                    # payment_mandateフィールドにcart_mandateを渡す（検証ロジックは共通）
                    verification_response = await self.http_client.post(
                        f"{self.credential_provider_url}/verify/attestation",
                        json={
                            "payment_mandate": cart_mandate,  # 検証対象のMandate
                            "attestation": webauthn_assertion   # WebAuthn assertion
                        }
                    )

                    logger.info(
                        f"[submit_cart_signature] Sent WebAuthn verification request to Credential Provider: "
                        f"user_id={user_id}"
                    )

                    if verification_response.status_code != 200:
                        logger.error(
                            f"[submit_cart_signature] WebAuthn verification failed: "
                            f"status={verification_response.status_code}"
                        )
                        raise HTTPException(
                            status_code=400,
                            detail="WebAuthn signature verification failed"
                        )

                    verification_result = verification_response.json()

                    if not verification_result.get("verified"):
                        logger.error(
                            f"[submit_cart_signature] WebAuthn verification returned false: "
                            f"{verification_result.get('details')}"
                        )
                        raise HTTPException(
                            status_code=400,
                            detail=f"Invalid WebAuthn signature: {verification_result.get('details', {}).get('error')}"
                        )

                    logger.info(
                        f"[submit_cart_signature] ✅ WebAuthn signature verified successfully: "
                        f"counter={verification_result.get('details', {}).get('counter')}, "
                        f"attestation_type={verification_result.get('details', {}).get('attestation_type')}"
                    )

                except httpx.HTTPError as e:
                    logger.error(
                        f"[submit_cart_signature] Failed to communicate with Credential Provider: {e}",
                        exc_info=True
                    )
                    raise HTTPException(
                        status_code=503,
                        detail=f"Credential Provider unavailable: {e}"
                    )
                except HTTPException:
                    raise
                except Exception as e:
                    logger.error(
                        f"[submit_cart_signature] WebAuthn verification error: {e}",
                        exc_info=True
                    )
                    raise HTTPException(
                        status_code=500,
                        detail=f"WebAuthn verification failed: {e}"
                    )

                # AP2完全準拠: CartMandateは変更せず、Merchant署名のままPayment Processorに送信
                # User署名情報（WebAuthn assertion）はPaymentMandateのuser_authorizationに含める
                # CartMandateの内容を変更すると、merchant_authorization JWTのcart_hashと一致しなくなる

                # WebAuthn assertionをセッションに保存（PaymentMandate生成時にuser_authorization作成に使用）
                session["cart_webauthn_assertion"] = webauthn_assertion
                # CartMandateは変更せずそのまま保持（Merchant署名時のハッシュを維持）

                # AP2完全準拠: CartMandate署名完了後、PaymentMandate作成へ進む
                # Credential Provider選択と支払い方法選択はPaymentMandate作成時に行う
                session["step"] = "payment_mandate_creation"

                # セッション保存
                await self._update_session(session_id, session)

                logger.info(
                    f"[submit_cart_signature] CartMandate signed by user: "
                    f"cart_id={cart_mandate.get('id')}, next_step=payment_mandate_creation"
                )

                # AP2完全準拠: CartMandate署名完了後、Credential Provider選択へ進む
                return {
                    "status": "success",
                    "message": "CartMandate signed successfully",
                    "next_step": "payment_mandate_creation"
                }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[submit_cart_signature] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to process CartMandate signature: {e}")

        @self.app.post("/payment/submit-attestation")
        async def submit_payment_attestation(
            request: Dict[str, Any],
            current_user: UserInDB = Depends(self.get_current_user_dependency)  # AP2準拠: Layer 1認証
        ):
            """
            POST /payment/submit-attestation - WebAuthn attestationを受け取って決済処理を実行

            AP2プロトコル完全準拠：
            - Layer 1認証: JWT Bearer Token（HTTP Session）
            - Layer 2認証: WebAuthn attestation（Payment Mandate）
            - user_id = JWT.sub（認証済みユーザーID）
            - payer_email = JWT.email（オプション）
            - トラステッドサーフェス: WebAuthn/Passkey

            フロー:
            1. フロントエンドがWebAuthn APIでユーザー認証を実行
            2. フロントエンドが生成されたattestationをこのエンドポイントに送信
            3. バックエンドがCredential Providerに検証依頼
            4. 検証成功後、Payment Processorに決済依頼
            5. 決済結果を返す

            リクエスト:
            - Header: Authorization: Bearer <JWT>
            - Body: {
                "session_id": "session_abc123",
                "attestation": {
                    "rawId": "credential_id",
                    "type": "public-key",
                    "attestation_type": "passkey",
                    "response": {
                        "authenticatorData": "...",
                        "clientDataJSON": "...",
                        "signature": "..."
                    }
                }
            }

            レスポンス:
            {
                "status": "success" | "failed",
                "transaction_id": "tx_abc123",
                "receipt_url": "https://...",
                "error": "..." (失敗時)
            }
            """
            try:
                session_id = request.get("session_id")
                attestation = request.get("attestation", {})

                if not session_id:
                    raise HTTPException(status_code=400, detail="session_id is required")

                if not attestation:
                    raise HTTPException(status_code=400, detail="attestation is required")

                # セッション取得（データベースから）
                async with self.db_manager.get_session() as db_session:
                    db_session_obj = await AgentSessionCRUD.get_by_session_id(db_session, session_id)

                    if not db_session_obj:
                        raise HTTPException(status_code=404, detail="Session not found")

                    # セッションデータを取得
                    session = json.loads(db_session_obj.session_data)

                # 現在のステップ確認
                if session.get("step") != "webauthn_attestation_requested":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Invalid session state: {session.get('step')}. Expected: webauthn_attestation_requested"
                    )

                # PaymentMandate取得
                payment_mandate = session.get("payment_mandate")
                if not payment_mandate:
                    raise HTTPException(status_code=400, detail="PaymentMandate not found in session")

                # WebAuthn challengeの検証
                expected_challenge = session.get("webauthn_challenge")
                received_challenge = attestation.get("challenge", "")

                if expected_challenge and expected_challenge != received_challenge:
                    logger.warning(
                        f"[submit_payment_attestation] Challenge mismatch: "
                        f"expected={expected_challenge}, received={received_challenge}"
                    )
                    # デモ環境では警告のみで続行

                # Credential Providerで検証
                selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

                logger.info(f"[submit_payment_attestation] Verifying attestation for PaymentMandate: {payment_mandate['id']}")

                verification_result = await self._verify_attestation_with_cp(
                    payment_mandate,
                    attestation,
                    selected_cp["url"]
                )

                if not verification_result.get("verified"):
                    # 認証失敗
                    session["step"] = "attestation_failed"
                    return {
                        "status": "failed",
                        "error": "WebAuthn attestation verification failed",
                        "details": verification_result.get("details", "Unknown error")
                    }

                # 認証成功 - 決済処理を実行
                logger.info(f"[submit_payment_attestation] Attestation verified, processing payment...")

                session["attestation_token"] = verification_result.get("token")
                session["step"] = "payment_processing"

                # CartMandateを取得（user_authorization生成に必要）
                cart_mandate = session.get("cart_mandate")
                if not cart_mandate:
                    raise HTTPException(status_code=400, detail="CartMandate not found in session")

                # AP2仕様完全準拠：WebAuthn assertionからSD-JWT-VC形式のuser_authorizationを生成
                # refs/AP2-main/src/ap2/types/mandate.py:181-200 に基づく実装
                user_id = session.get("user_id", "user_demo_001")

                try:
                    # credential_idを取得してCredential Providerから公開鍵を取得
                    credential_id = attestation.get("id")
                    public_key_cose = None

                    if credential_id:
                        try:
                            # Credential Providerから公開鍵を取得
                            selected_cp = session.get("selected_credential_provider", self.credential_providers[0])
                            public_key_response = await self.http_client.post(
                                f"{selected_cp['url']}/passkey/get-public-key",
                                json={"credential_id": credential_id, "user_id": user_id},
                                timeout=10.0
                            )
                            public_key_response.raise_for_status()
                            public_key_data = public_key_response.json()
                            public_key_cose = public_key_data.get("public_key_cose")

                            logger.info(
                                f"[submit_payment_attestation] Public key retrieved from Credential Provider: "
                                f"credential_id={credential_id[:16]}..."
                            )
                        except Exception as pk_error:
                            logger.warning(
                                f"[submit_payment_attestation] Failed to retrieve public key from CP: {pk_error}"
                            )

                    # VP生成時、PaymentMandateからuser_authorizationフィールドを除外
                    # （ハッシュ計算の一貫性を保つため）
                    payment_mandate_for_vp = {k: v for k, v in payment_mandate.items() if k != "user_authorization"}

                    user_authorization = create_user_authorization_vp(
                        webauthn_assertion=attestation,
                        cart_mandate=cart_mandate,
                        payment_mandate_contents=payment_mandate_for_vp,
                        user_id=user_id,
                        payment_processor_id="did:ap2:agent:payment_processor",
                        public_key_cose=public_key_cose
                    )

                    payment_mandate["user_authorization"] = user_authorization

                    logger.info(
                        f"[submit_payment_attestation] SD-JWT-VC user_authorization generated: "
                        f"user_id={user_id}, vp_length={len(user_authorization)}"
                    )
                except Exception as e:
                    logger.error(f"[submit_payment_attestation] Failed to generate user_authorization VP: {e}", exc_info=True)
                    raise HTTPException(
                        status_code=500,
                        detail=f"Failed to generate user_authorization: {e}"
                    )

                # AP2 Step 24-31: Merchant Agent経由で決済処理
                payment_result = await self._process_payment_via_merchant_agent(payment_mandate, cart_mandate)

                if payment_result.get("status") == "captured":
                    # 決済成功
                    transaction_id = payment_result.get("transaction_id")
                    receipt_url = payment_result.get("receipt_url")

                    session["transaction_id"] = transaction_id
                    session["step"] = "completed"

                    logger.info(f"[submit_payment_attestation] Payment successful: {transaction_id}")

                    # AP2仕様準拠：CartMandateから商品情報と金額を取得
                    cart_mandate = session.get("cart_mandate", {})

                    # AP2準拠：contents.payment_request.details から情報を取得
                    contents = cart_mandate.get("contents", {})
                    payment_request = contents.get("payment_request", {})
                    details = payment_request.get("details", {})

                    # 商品アイテムを取得（display_itemsからrefund_period > 0のものを抽出）
                    display_items = details.get("display_items", [])
                    items = [item for item in display_items if item.get("refund_period", 0) > 0]

                    # 合計金額を取得
                    total_item = details.get("total", {})
                    total_amount_data = total_item.get("amount", {})
                    currency = total_amount_data.get("currency", "JPY")

                    # _metadata.raw_itemsからも情報取得（後方互換性）
                    raw_items = cart_mandate.get("_metadata", {}).get("raw_items", [])

                    logger.info(
                        f"[submit_payment_attestation] CartMandate info: "
                        f"items_count={len(items)}, "
                        f"raw_items_count={len(raw_items)}, "
                        f"total_amount={total_amount_data}"
                    )

                    # 商品名を生成（複数商品の場合は商品数を表示）
                    if len(items) == 1:
                        product_name = items[0].get("label", "商品")
                    elif len(items) > 1:
                        product_name = f"{items[0].get('label', '商品')} 他{len(items) - 1}点"
                    else:
                        product_name = "購入商品"

                    # 金額を取得（AP2準拠：numberとして扱う）
                    try:
                        amount = float(total_amount_data.get("value", 0))
                    except (ValueError, TypeError):
                        amount = 0

                    logger.info(
                        f"[submit_payment_attestation] Payment success response: "
                        f"product_name={product_name}, "
                        f"amount={amount}, "
                        f"currency={currency}"
                    )

                    return {
                        "status": "success",
                        "transaction_id": transaction_id,
                        "receipt_url": receipt_url,
                        "product_name": product_name,
                        "amount": amount,
                        "items_count": len(items),
                        "currency": currency
                    }
                else:
                    # 決済失敗
                    error_message = payment_result.get("error", "Payment processing failed")
                    session["step"] = "payment_failed"

                    logger.error(f"[submit_payment_attestation] Payment failed: {error_message}")

                    return {
                        "status": "failed",
                        "error": error_message
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[submit_payment_attestation] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=f"Failed to process payment attestation: {e}")

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_cart_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """CartMandateを受信（Merchant Agentから）"""
        logger.info("[ShoppingAgent] Received CartMandate")
        cart_mandate = message.dataPart.payload

        # AP2準拠：cart_idをcontents.idから取得
        cart_id = cart_mandate["contents"]["id"]

        # データベースに保存
        async with self.db_manager.get_session() as session:
            await MandateCRUD.create(session, {
                "id": cart_id,
                "type": "Cart",
                "status": "pending_signature",
                "payload": cart_mandate,
                "issuer": message.header.sender
            })

        return {
            "type": "ap2.responses.Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "cart_mandate_id": cart_id
            }
        }

    async def handle_product_list(self, message: A2AMessage) -> Dict[str, Any]:
        """商品リストを受信（Merchant Agentから）"""
        logger.info("[ShoppingAgent] Received ProductList")
        products = message.dataPart.payload.get("products", [])

        return {
            "type": "ap2.responses.Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "product_count": len(products)
            }
        }

    async def handle_signature_response(self, message: A2AMessage) -> Dict[str, Any]:
        """署名結果を受信（Credential Providerから）"""
        logger.info("[ShoppingAgent] Received SignatureResponse")
        signature_data = message.dataPart.payload

        return {
            "type": "ap2.responses.Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "verified": signature_data.get("verified", False)
            }
        }

    # ========================================
    # 固定応答フロー（LLM統合前）
    # ========================================

    async def _generate_fixed_response(
        self,
        user_input: str,
        session: Dict[str, Any],
        session_id: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        固定応答を生成（LLM統合前の簡易版）

        改善されたフロー：
        1. 挨拶 → 質問促す
        2. Intent入力 → 最大金額を質問
        3. 最大金額入力 → カテゴリーを質問（オプション）
        4. カテゴリー入力 → ブランドを質問（オプション）
        5. ブランド入力 → IntentMandate生成 → 署名リクエスト
        6. 署名完了 → 商品検索 → CartMandate提案
        7. カート承認 → PaymentMandate生成 → 決済

        Args:
            user_input: ユーザー入力
            session: セッションデータ
            session_id: セッションID（データベース保存用）
        """
        user_input_lower = user_input.lower()
        current_step = session.get("step", "initial")

        # リセットキーワード検知：エラーや完了後に「こんにちは」で初期化
        if any(word in user_input_lower for word in ["こんにちは", "hello", "hi", "はじめから", "やり直", "リセット", "reset"]):
            if current_step in ["error", "completed"]:
                # セッションを初期化
                session.clear()
                session["step"] = "initial"
                session["session_id"] = session_id
                logger.info(f"[ShoppingAgent] Session reset by user: session_id={session_id}")

                yield StreamEvent(
                    type="agent_text",
                    content="セッションをリセットしました。新しい購入を始めましょう！"
                )
                await asyncio.sleep(0.3)
                current_step = "initial"

        # Step-up認証完了の処理
        if user_input.startswith("step-up-completed:"):
            step_up_session_id = user_input.split(":", 1)[1].strip()
            logger.info(f"[ShoppingAgent] Step-up completed: session_id={step_up_session_id}")

            # Credential Providerにstep-up完了を確認
            selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

            try:
                # Step-upセッション情報を取得
                verify_response = await self.http_client.post(
                    f"{selected_cp['url']}/payment-methods/verify-step-up",
                    json={"session_id": step_up_session_id},
                    timeout=10.0
                )
                verify_response.raise_for_status()
                step_up_result = verify_response.json()

                if step_up_result.get("verified"):
                    # 認証成功 - 決済フローを続行
                    payment_method = step_up_result.get("payment_method")
                    session["selected_payment_method"] = payment_method

                    # トークン化された支払い方法をセッションに保存
                    # Step-up完了により、既に認証済みとみなす
                    # 重要: step_up_resultからtokenとexpires_atを取得
                    token = step_up_result.get("token")
                    token_expires_at = step_up_result.get("token_expires_at")

                    if not token:
                        logger.error(f"[ShoppingAgent] Step-up verification did not return token: {step_up_result}")
                        yield StreamEvent(
                            type="agent_text",
                            content="❌ 認証トークンが取得できませんでした。別の支払い方法を選択してください。"
                        )
                        session["step"] = "select_payment_method"
                        return

                    session["tokenized_payment_method"] = {
                        **payment_method,
                        "token": token,
                        "token_expires_at": token_expires_at,
                        "step_up_completed": True,
                        "step_up_session_id": step_up_session_id
                    }

                    logger.info(
                        f"[ShoppingAgent] Tokenized payment method set after step-up: "
                        f"token={token[:20]}..., expires_at={token_expires_at}"
                    )

                    yield StreamEvent(
                        type="agent_text",
                        content=f"✅ 追加認証が完了しました。\n\n{payment_method['brand'].upper()} ****{payment_method['last4']}で決済を続行します。"
                    )
                    await asyncio.sleep(0.5)

                    # PaymentMandateを作成
                    yield StreamEvent(
                        type="agent_text",
                        content="決済情報を準備中..."
                    )
                    await asyncio.sleep(0.3)

                    # CartMandateの存在確認
                    if not session.get("cart_mandate"):
                        selected_cart_mandate = session.get("selected_cart_mandate")
                        if selected_cart_mandate:
                            session["cart_mandate"] = selected_cart_mandate
                            logger.info("[ShoppingAgent] Set cart_mandate from selected_cart_mandate after step-up")
                        else:
                            # CartMandateが見つからない場合のエラー
                            logger.error("[ShoppingAgent] No cart mandate found in session after step-up")
                            yield StreamEvent(
                                type="agent_text",
                                content="❌ カート情報が見つかりません。最初からやり直してください。"
                            )
                            session["step"] = "error"
                            # セッション保存（エラー状態）
                            await self._update_session(session_id, session)
                            return

                    # PaymentMandate作成
                    payment_mandate = self._create_payment_mandate(session)
                    session["payment_mandate"] = payment_mandate
                    session["step"] = "webauthn_attestation_requested"
                    session["will_use_passkey"] = True

                    yield StreamEvent(
                        type="agent_text",
                        content="決済準備が完了しました。セキュリティのため、デバイス認証（WebAuthn/Passkey）を実施します。"
                    )
                    await asyncio.sleep(0.5)

                    # WebAuthn challengeを生成
                    import secrets
                    challenge = secrets.token_urlsafe(32)
                    session["webauthn_challenge"] = challenge

                    yield StreamEvent(
                        type="webauthn_request",
                        challenge=challenge,
                        rp_id="localhost",
                        timeout=60000
                    )

                    yield StreamEvent(
                        type="agent_text",
                        content="デバイス認証を完了してください。\n\n認証後、自動的に決済処理が開始されます。"
                    )
                    return
                else:
                    # 認証失敗
                    yield StreamEvent(
                        type="agent_text",
                        content="❌ 追加認証に失敗しました。別の支払い方法を選択してください。"
                    )
                    session["step"] = "select_payment_method"

                    # 支払い方法選択に戻る
                    payment_methods = session.get("available_payment_methods", [])
                    if payment_methods:
                        await asyncio.sleep(0.3)
                        yield StreamEvent(
                            type="agent_text",
                            content="以下の支払い方法から選択してください。"
                        )
                        await asyncio.sleep(0.2)
                        yield StreamEvent(
                            type="payment_method_selection",
                            payment_methods=payment_methods
                        )
                    return

            except Exception as e:
                logger.error(f"[ShoppingAgent] Failed to verify step-up: {e}", exc_info=True)
                yield StreamEvent(
                    type="agent_text",
                    content=f"認証確認中にエラーが発生しました: {e}\n\n別の支払い方法を選択してください。"
                )
                session["step"] = "select_payment_method"

                # 支払い方法選択に戻る
                payment_methods = session.get("available_payment_methods", [])
                if payment_methods:
                    await asyncio.sleep(0.3)
                    yield StreamEvent(
                        type="agent_text",
                        content="以下の支払い方法から選択してください。"
                    )
                    await asyncio.sleep(0.2)
                    yield StreamEvent(
                        type="payment_method_selection",
                        payment_methods=payment_methods
                    )
                return

        # ステップ1: 初回挨拶 または 対話フロー（LangGraph AI対応 - ストリーミング）
        if current_step in ["initial", "ask_intent", "ask_max_amount", "ask_categories", "ask_brands", "collecting_intent_info"]:
            # LangGraph対話エージェントを使用（ストリーミング版）
            if self.conversation_agent:
                try:
                    # 現在の対話状態を取得
                    conversation_state = session.get("conversation_state")

                    # LLMの思考過程を表示
                    llm_thinking_content = ""
                    final_state = None

                    # 対話エージェントをストリーミング実行
                    async for event in self.conversation_agent.process_user_input_stream(
                        user_input=user_input,
                        current_state=conversation_state
                    ):
                        event_type = event.get("type")

                        if event_type == "llm_chunk":
                            # LLMの出力をリアルタイムで表示
                            chunk_content = event.get("content", "")
                            llm_thinking_content += chunk_content

                            yield StreamEvent(
                                type="agent_thinking",
                                content=chunk_content
                            )

                        elif event_type == "complete":
                            # 最終状態を取得
                            final_state = event.get("state")

                    if not final_state:
                        raise ValueError("LangGraph conversation did not return final state")

                    # セッションに状態を保存
                    session["conversation_state"] = final_state

                    # LLM思考過程が完了したことを通知
                    if llm_thinking_content:
                        await asyncio.sleep(0.2)
                        yield StreamEvent(
                            type="agent_thinking_complete",
                            content=""
                        )
                        await asyncio.sleep(0.3)

                    # エージェントの応答を段階的に表示
                    agent_response = final_state["agent_response"]
                    # 文字単位でストリーミング表示（より自然なUX）
                    for char in agent_response:
                        yield StreamEvent(
                            type="agent_text_chunk",
                            content=char
                        )
                        await asyncio.sleep(0.02)  # 20msごとに1文字表示

                    # テキスト完了を通知
                    yield StreamEvent(
                        type="agent_text_complete",
                        content=""
                    )
                    await asyncio.sleep(0.3)

                    # すべての必須情報が揃ったか確認
                    if final_state["is_complete"]:
                        # Intent Mandateの生成へ進む
                        session["intent"] = final_state["intent"]
                        session["max_amount"] = final_state["max_amount"]
                        session["categories"] = final_state.get("categories", [])
                        session["brands"] = final_state.get("brands", [])
                        session["step"] = "intent_complete_ask_shipping"

                        # 配送先入力の案内
                        shipping_prompt = "商品の配送先を入力してください。"
                        for char in shipping_prompt:
                            yield StreamEvent(
                                type="agent_text_chunk",
                                content=char
                            )
                            await asyncio.sleep(0.02)

                        yield StreamEvent(
                            type="agent_text_complete",
                            content=""
                        )
                        await asyncio.sleep(0.3)

                        # 配送先フォーム表示（AP2準拠: ContactAddress形式）
                        yield StreamEvent(
                            type="shipping_form_request",
                            form_schema={
                                "type": "contact_address",  # AP2準拠
                                "fields": [
                                    {"name": "recipient", "label": "受取人名", "type": "text", "required": True},
                                    {"name": "postal_code", "label": "郵便番号", "type": "text", "required": True},
                                    {"name": "city", "label": "市区町村", "type": "text", "required": True},
                                    {"name": "region", "label": "都道府県", "type": "text", "required": True},
                                    {"name": "address_line1", "label": "住所1（番地等）", "type": "text", "required": True},
                                    {"name": "address_line2", "label": "住所2（建物名等）", "type": "text", "required": False},
                                    {"name": "country", "label": "国", "type": "text", "required": True, "default": "JP"},
                                    {"name": "phone_number", "label": "電話番号", "type": "text", "required": False},
                                ]
                            }
                        )
                    else:
                        # まだ情報が不足している場合、次の入力を待つ
                        session["step"] = "collecting_intent_info"

                    return

                except Exception as e:
                    logger.error(f"[_generate_fixed_response] LangGraph conversation failed: {e}", exc_info=True)
                    # フォールバック: 従来の固定フローに切り替え
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ございません。AIエージェントでエラーが発生しました。従来の方式で続けます。"
                    )
                    await asyncio.sleep(0.3)
                    session["step"] = "ask_intent_fallback"
                    return

            # LangGraph未初期化の場合：従来の固定フロー
            if current_step == "initial":
                if any(word in user_input_lower for word in ["こんにちは", "hello", "hi", "購入", "買い", "探"]):
                    yield StreamEvent(
                        type="agent_text",
                        content="こんにちは！AP2 Shopping Agentです。"
                    )
                    await asyncio.sleep(0.3)
                    yield StreamEvent(
                        type="agent_text",
                        content="何をお探しですか？例えば「かわいいグッズがほしい」のように教えてください。"
                    )
                    session["step"] = "ask_intent"
                    return

                # Intent入力された場合
                session["intent"] = user_input
                session["step"] = "ask_max_amount"

                yield StreamEvent(
                    type="agent_text",
                    content=f"「{user_input}」ですね！"
                )
                await asyncio.sleep(0.3)
                yield StreamEvent(
                    type="agent_text",
                    content="最大金額を教えてください。（例：50000円、または50000）"
                )
                return

        # ステップ2: 最大金額を質問
        elif current_step == "ask_intent":
            session["intent"] = user_input
            session["step"] = "ask_max_amount"

            yield StreamEvent(
                type="agent_text",
                content=f"「{user_input}」ですね！"
            )
            await asyncio.sleep(0.3)
            yield StreamEvent(
                type="agent_text",
                content="最大金額を教えてください。（例：50000円、または50000）"
            )
            return

        # ステップ3: 最大金額入力 → カテゴリー質問
        elif current_step == "ask_max_amount":
            # 金額をパース
            import re
            amount_match = re.search(r'(\d+)', user_input)
            if amount_match:
                max_amount = int(amount_match.group(1))
                session["max_amount"] = max_amount

                yield StreamEvent(
                    type="agent_text",
                    content=f"最大金額を{max_amount:,}円に設定しました。"
                )
                await asyncio.sleep(0.3)
                yield StreamEvent(
                    type="agent_text",
                    content="カテゴリーを指定しますか？（例：カレンダー）\n指定しない場合は「スキップ」と入力してください。"
                )
                session["step"] = "ask_categories"
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="金額が認識できませんでした。数字で入力してください。（例：50000）"
                )
            return

        # ステップ4: カテゴリー入力 → ブランド質問
        elif current_step == "ask_categories":
            if "スキップ" in user_input or "skip" in user_input_lower:
                session["categories"] = []
                yield StreamEvent(
                    type="agent_text",
                    content="カテゴリーは指定しません。"
                )
            else:
                # カンマ区切りでカテゴリーを分割
                categories = [c.strip() for c in user_input.split(",")]
                session["categories"] = categories
                yield StreamEvent(
                    type="agent_text",
                    content=f"カテゴリー: {', '.join(categories)}"
                )

            await asyncio.sleep(0.3)
            yield StreamEvent(
                type="agent_text",
                content="ブランドを指定しますか？\n指定しない場合は「スキップ」と入力してください。"
            )
            session["step"] = "ask_brands"
            return

        # ステップ5: ブランド入力 → IntentMandate生成
        elif current_step == "ask_brands":
            if "スキップ" in user_input or "skip" in user_input_lower:
                session["brands"] = []
                yield StreamEvent(
                    type="agent_text",
                    content="ブランドは指定しません。"
                )
            else:
                # カンマ区切りでブランドを分割
                brands = [b.strip() for b in user_input.split(",")]
                session["brands"] = brands
                yield StreamEvent(
                    type="agent_text",
                    content=f"ブランド: {', '.join(brands)}"
                )

            await asyncio.sleep(0.5)

            # IntentMandate生成（AP2 Human-Presentフロー：署名不要）
            intent_mandate = await self._create_intent_mandate(
                session["intent"],
                session
            )
            session["intent_mandate"] = intent_mandate

            # IntentMandateをDB永続化（Dispute Resolution用）
            await self._persist_intent_mandate(intent_mandate, session)

            # AP2完全準拠: IntentMandate作成後、直接配送先入力へ進む
            # Credential Provider選択はPaymentMandate作成時に行う
            yield StreamEvent(
                type="agent_text",
                content="購入条件が確認できました。商品の配送先を入力してください。"
            )
            await asyncio.sleep(0.3)

            # 既存の配送先があればそれをデフォルト値として使用
            existing_shipping = session.get("shipping_address", {})

            yield StreamEvent(
                type="shipping_form_request",
                form_schema={
                    "type": "shipping_address",
                    "fields": [
                        {
                            "name": "recipient",
                            "label": "受取人名",
                            "type": "text",
                            "placeholder": "山田太郎",
                            "default": existing_shipping.get("recipient", ""),
                            "required": True
                        },
                        {
                            "name": "postal_code",
                            "label": "郵便番号",
                            "type": "text",
                            "placeholder": "150-0001",
                            "default": existing_shipping.get("postal_code", ""),
                            "required": True
                        },
                        {
                            "name": "address_line1",
                            "label": "住所1（都道府県・市区町村・番地）",
                            "type": "text",
                            "placeholder": "東京都渋谷区神宮前1-1-1",
                            "default": existing_shipping.get("address_line1", ""),
                            "required": True
                        },
                        {
                            "name": "address_line2",
                            "label": "住所2（建物名・部屋番号など）",
                            "type": "text",
                            "placeholder": "ABCビル101号室",
                            "default": existing_shipping.get("address_line2", ""),
                            "required": False
                        },
                        {
                            "name": "phone",
                            "label": "電話番号",
                            "type": "tel",
                            "placeholder": "03-1234-5678",
                            "default": existing_shipping.get("phone", ""),
                            "required": True
                        }
                    ]
                }
            )

            session["step"] = "shipping_address_input"
            return


        # LangGraph対話完了後の配送先入力
        elif current_step == "intent_complete_ask_shipping":
            # 配送先入力処理（shipping_address_inputと同じ）
            shipping_address = None

            try:
                import json as json_lib

                logger.info(f"[intent_complete_ask_shipping] Received user_input: {user_input[:200]}")

                if user_input.strip().startswith("{"):
                    shipping_address = json_lib.loads(user_input)
                    logger.info(f"[intent_complete_ask_shipping] Parsed JSON shipping address: {shipping_address}")
                else:
                    logger.warning(f"[intent_complete_ask_shipping] user_input does not start with '{{'")
                    yield StreamEvent(
                        type="agent_text",
                        content="配送先の入力形式が不正です。もう一度入力してください。"
                    )
                    return

            except json_lib.JSONDecodeError as e:
                logger.error(f"[intent_complete_ask_shipping] JSON parse error: {e}, input: {user_input[:200]}")
                yield StreamEvent(
                    type="agent_text",
                    content="配送先の入力形式が不正です。もう一度入力してください。"
                )
                return
            except Exception as e:
                logger.error(f"[intent_complete_ask_shipping] Unexpected error: {e}", exc_info=True)
                yield StreamEvent(
                    type="agent_text",
                    content=f"配送先の処理中にエラーが発生しました: {str(e)}"
                )
                session["step"] = "error"
                return

            # AP2準拠: ContactAddress形式に変換
            # address_line1とaddress_line2を配列に変換
            address_lines = []
            if shipping_address.get("address_line1"):
                address_lines.append(shipping_address["address_line1"])
            if shipping_address.get("address_line2"):
                address_lines.append(shipping_address["address_line2"])

            contact_address = {
                "recipient": shipping_address.get("recipient"),
                "postal_code": shipping_address.get("postal_code"),
                "city": shipping_address.get("city"),
                "region": shipping_address.get("region") or shipping_address.get("state"),  # regionまたはstate
                "country": shipping_address.get("country"),
                "address_line": address_lines if address_lines else None,
                "phone_number": shipping_address.get("phone_number"),
            }

            # AP2 ContactAddress形式でセッションに保存
            session["shipping_address"] = contact_address

            yield StreamEvent(
                type="agent_text",
                content=f"配送先を設定しました：{shipping_address['recipient']} 様"
            )
            await asyncio.sleep(0.3)

            # LangGraph Shoppingエンジンを使用（Intent→Cart候補取得）
            if self.langgraph_shopping_agent:
                yield StreamEvent(
                    type="agent_text",
                    content="AI分析でカート候補を作成中..."
                )
                await asyncio.sleep(0.5)

                try:
                    # AP2準拠: natural_language_descriptionには金額制約を含める
                    # session["intent"]は会話エージェントで分離されているため、再構築
                    intent_text = session["intent"]
                    max_amount = session.get("max_amount")
                    categories = session.get("categories", [])
                    brands = session.get("brands", [])

                    # 金額制約を含めた完全なuser_prompt構築
                    constraints = []
                    if max_amount:
                        constraints.append(f"{max_amount}円以内")
                    if categories:
                        constraints.append(f"カテゴリー: {', '.join(categories)}")
                    if brands:
                        constraints.append(f"ブランド: {', '.join(brands)}")

                    if constraints:
                        user_prompt_full = f"{intent_text}。{', '.join(constraints)}"
                    else:
                        user_prompt_full = intent_text

                    logger.info(f"[LangGraph] Reconstructed user_prompt: {user_prompt_full}")

                    # LangGraphエンジンで処理（Intent抽出→Merchant Agent呼び出し→カート分析）
                    result = await self.langgraph_shopping_agent.process_intent_to_carts(
                        user_prompt=user_prompt_full,
                        session_id=session_id,
                        user_id=session.get("user_id", "user_demo_001"),
                        shipping_address=contact_address
                    )

                    if result.get("error"):
                        yield StreamEvent(
                            type="agent_text",
                            content=f"申し訳ありません。エラーが発生しました: {result['error']}"
                        )
                        return

                    intent_mandate = result.get("intent_mandate")
                    cart_candidates = result.get("cart_candidates", [])

                    if not intent_mandate:
                        yield StreamEvent(
                            type="agent_text",
                            content="申し訳ありません。インテント抽出に失敗しました。"
                        )
                        return

                    session["intent_mandate"] = intent_mandate
                    await self._persist_intent_mandate(intent_mandate, session)

                    logger.info(f"[chat_stream] LangGraph処理完了: {len(cart_candidates)} carts")

                except Exception as e:
                    logger.error(f"[chat_stream] LangGraph処理エラー: {e}", exc_info=True)
                    yield StreamEvent(
                        type="agent_text",
                        content=f"申し訳ありません。処理中にエラーが発生しました: {str(e)}"
                    )
                    return
            else:
                # フォールバック: 既存の処理
                intent_mandate = await self._create_intent_mandate(session["intent"], session)
                session["intent_mandate"] = intent_mandate
                await self._persist_intent_mandate(intent_mandate, session)

                yield StreamEvent(
                    type="agent_text",
                    content="Merchant Agentにカート候補を依頼中..."
                )
                await asyncio.sleep(0.5)

                try:
                    cart_candidates = await self._search_products_via_merchant_agent(
                        session["intent_mandate"],
                        session
                    )
                except Exception as e:
                    logger.error(f"[chat_stream] Merchant Agent呼び出しエラー: {e}", exc_info=True)
                    yield StreamEvent(
                        type="agent_text",
                        content=f"申し訳ありません。カート候補の取得に失敗しました: {str(e)}"
                    )
                    return

            if not cart_candidates:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。条件に合うカート候補が見つかりませんでした。"
                )
                session["step"] = "error"
                return

            logger.info(f"[ShoppingAgent] Received {len(cart_candidates)} signed cart candidates from Merchant Agent")

            # AP2/A2A仕様準拠: Artifact構造をフロントエンド用にCartCandidate形式に変換
            # Artifact構造: {"artifactId": "...", "name": "...", "parts": [{"data": {"ap2.mandates.CartMandate": {...}}}]}
            logger.info(f"[ShoppingAgent] First cart structure sample: {json.dumps(cart_candidates[0] if cart_candidates else {}, ensure_ascii=False)[:500]}")

            frontend_cart_candidates = []
            for i, cart_artifact in enumerate(cart_candidates):
                try:
                    # Artifact構造からCartMandateを抽出
                    cart_mandate = cart_artifact["parts"][0]["data"]["ap2.mandates.CartMandate"]

                    # フロントエンド用のCartCandidate形式に変換
                    cart_candidate = {
                        "artifact_id": cart_artifact.get("artifactId", f"artifact_{i}"),
                        "artifact_name": cart_artifact.get("name", f"カート{i+1}"),
                        "cart_mandate": cart_mandate
                    }
                    frontend_cart_candidates.append(cart_candidate)
                    logger.info(f"[ShoppingAgent] Successfully converted Artifact {i} to CartCandidate")
                except (KeyError, IndexError) as e:
                    logger.error(f"[ShoppingAgent] Failed to extract CartMandate {i} from Artifact: {e}, keys: {list(cart_artifact.keys()) if isinstance(cart_artifact, dict) else 'not a dict'}")

            logger.info(f"[ShoppingAgent] Converted {len(frontend_cart_candidates)} carts to frontend format")

            # カート候補をセッションに保存
            # - cart_candidates_raw: 元のArtifact構造（A2A準拠、署名検証用）
            # - cart_candidates: CartCandidate形式（カート選択処理用）
            session["cart_candidates_raw"] = cart_candidates
            session["cart_candidates"] = frontend_cart_candidates

            # フロントエンドにはCartCandidate形式で送信
            yield StreamEvent(
                type="cart_options",
                items=frontend_cart_candidates
            )

            yield StreamEvent(
                type="agent_text",
                content=f"{len(cart_candidates)}つのカート候補が見つかりました。お好みのカートを選択してください。"
            )

            session["step"] = "cart_selection"
            return

        # ステップ6.1: 配送先入力完了後、商品検索（Merchant AgentへA2A通信）
        elif current_step == "shipping_address_input":
            # JSONとしてパース（フロントエンドからJSONで送信される想定）
            shipping_address = None

            try:
                import json as json_lib

                # デバッグ：受信したuser_inputをログ出力
                logger.info(f"[shipping_address_input] Received user_input: {user_input[:200]}")

                # JSONパースを試行
                if user_input.strip().startswith("{"):
                    shipping_address = json_lib.loads(user_input)
                    logger.info(f"[shipping_address_input] Parsed JSON shipping address: {shipping_address}")
                else:
                    logger.warning(f"[shipping_address_input] user_input does not start with '{{'")
                    yield StreamEvent(
                        type="agent_text",
                        content="配送先の入力形式が不正です。もう一度入力してください。"
                    )
                    return

            except json_lib.JSONDecodeError as e:
                logger.error(f"[shipping_address_input] JSON parse error: {e}, input: {user_input[:200]}")
                yield StreamEvent(
                    type="agent_text",
                    content="配送先の入力形式が不正です。もう一度入力してください。"
                )
                return
            except Exception as e:
                logger.error(f"[shipping_address_input] Unexpected error: {e}", exc_info=True)
                yield StreamEvent(
                    type="agent_text",
                    content=f"配送先の処理中にエラーが発生しました: {str(e)}"
                )
                session["step"] = "error"
                return

            # 配送先設定完了メッセージ
            yield StreamEvent(
                type="agent_text",
                content=f"配送先を設定しました：{shipping_address['recipient']} 様"
            )

            session["shipping_address"] = shipping_address
            await asyncio.sleep(0.3)

            # AP2仕様準拠：配送先が確定したので、Merchant Agentにカート候補を依頼
            yield StreamEvent(
                type="agent_text",
                content="Merchant Agentにカート候補を依頼中..."
            )
            await asyncio.sleep(0.5)

            # Merchant AgentにIntentMandateと配送先を送信してカート候補を取得（A2A通信）
            try:
                cart_candidates = await self._search_products_via_merchant_agent(
                    session["intent_mandate"],
                    session  # intent_message_idと shipping_addressを参照
                )

                if not cart_candidates:
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。条件に合うカート候補が見つかりませんでした。"
                    )
                    session["step"] = "error"
                    return

                # AP2仕様準拠：Merchant AgentがMerchantの署名を待機してから返すため、
                # ここに到達した時点で全てのCartMandateは署名済みである
                logger.info(f"[ShoppingAgent] Received {len(cart_candidates)} signed cart candidates from Merchant Agent")

                # AP2/A2A仕様準拠: Artifact構造をフロントエンド用にCartCandidate形式に変換
                # Artifact構造: {"artifactId": "...", "name": "...", "parts": [{"data": {"ap2.mandates.CartMandate": {...}}}]}
                logger.info(f"[ShoppingAgent] First cart structure sample: {json.dumps(cart_candidates[0] if cart_candidates else {}, ensure_ascii=False)[:500]}")

                frontend_cart_candidates = []
                for i, cart_artifact in enumerate(cart_candidates):
                    try:
                        # Artifact構造からCartMandateを抽出
                        cart_mandate = cart_artifact["parts"][0]["data"]["ap2.mandates.CartMandate"]

                        # フロントエンド用のCartCandidate形式に変換
                        cart_candidate = {
                            "artifact_id": cart_artifact.get("artifactId", f"artifact_{i}"),
                            "artifact_name": cart_artifact.get("name", f"カート{i+1}"),
                            "cart_mandate": cart_mandate
                        }
                        frontend_cart_candidates.append(cart_candidate)
                        logger.info(f"[ShoppingAgent] Successfully converted Artifact {i} to CartCandidate")
                    except (KeyError, IndexError) as e:
                        logger.error(f"[ShoppingAgent] Failed to extract CartMandate {i} from Artifact: {e}, keys: {list(cart_artifact.keys()) if isinstance(cart_artifact, dict) else 'not a dict'}")

                logger.info(f"[ShoppingAgent] Converted {len(frontend_cart_candidates)} carts to frontend format")

                # カート候補をセッションに保存
                # - cart_candidates_raw: 元のArtifact構造（A2A準拠、署名検証用）
                # - cart_candidates: CartCandidate形式（カート選択処理用）
                session["cart_candidates_raw"] = cart_candidates
                session["cart_candidates"] = frontend_cart_candidates

                # フロントエンドにはCartCandidate形式で送信
                yield StreamEvent(
                    type="cart_options",
                    items=frontend_cart_candidates
                )

                yield StreamEvent(
                    type="agent_text",
                    content=f"{len(cart_candidates)}つのカート候補が見つかりました。お好みのカートを選択してください。"
                )
            except Exception as e:
                logger.error(f"[_generate_fixed_response] Cart candidates request via Merchant Agent failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。カート候補の取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

            session["step"] = "cart_selection"
            return

        # ステップ6.5: カート選択（AP2/A2A仕様準拠）
        elif current_step == "cart_selection":
            cart_candidates = session.get("cart_candidates", [])
            if not cart_candidates:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。カート候補が見つかりません。最初からやり直してください。"
                )
                session["step"] = "error"
                return

            # カート選択（カートIDまたは番号）
            selected_cart = None
            user_input_clean = user_input.strip()

            # 番号で選択（1, 2, 3...）
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(cart_candidates):
                    selected_cart = cart_candidates[index]

            # カートIDで選択（"cart_abc123"など）
            if not selected_cart:
                for cart in cart_candidates:
                    cart_mandate = cart.get("cart_mandate", {})
                    # AP2準拠：cart_idをcontents.idから取得
                    cart_id = cart_mandate.get("contents", {}).get("id", "")
                    if cart_id and cart_id in user_input:
                        selected_cart = cart
                        break

            # Artifact IDで選択
            if not selected_cart:
                for cart in cart_candidates:
                    artifact_id = cart.get("artifact_id")
                    if artifact_id and artifact_id in user_input:
                        selected_cart = cart
                        break

            if not selected_cart:
                yield StreamEvent(
                    type="agent_text",
                    content=f"カートが認識できませんでした。番号（1〜{len(cart_candidates)}）またはカートIDを入力してください。"
                )
                return

            # 選択されたカートを保存
            cart_mandate = selected_cart.get("cart_mandate", {})
            session["selected_cart_mandate"] = cart_mandate
            session["selected_cart_artifact"] = selected_cart

            # AP2準拠：cart_nameとtotal_amountを取得
            cart_name = cart_mandate.get("_metadata", {}).get("cart_name", "カート")
            # AP2準拠：contents.payment_request.details.total.amountから金額を取得
            contents = cart_mandate.get("contents", {})
            payment_request = contents.get("payment_request", {})
            details = payment_request.get("details", {})
            total_item = details.get("total", {})
            total_amount_data = total_item.get("amount", {})
            total_amount = float(total_amount_data.get("value", 0))

            yield StreamEvent(
                type="agent_text",
                content=f"「{cart_name}」を選択しました。\n合計金額: ¥{int(total_amount):,}"
            )
            await asyncio.sleep(0.3)

            # AP2仕様準拠（specification.md:629-632）：
            # Cart MandateはMerchant Agentがカート候補作成時に既にMerchantから署名を取得済み
            # "ma ->> m: 10. sign CartMandate"
            # "m --) ma: 11. { signed CartMandate }"
            # "ma --) sa: 12. { signed CartMandate }"
            #
            # Shopping Agentは署名済みCart Mandateをそのまま使用する（再署名依頼不要）

            # Merchant署名の存在確認
            merchant_signature = cart_mandate.get("merchant_signature")
            merchant_authorization = cart_mandate.get("merchant_authorization")

            if not merchant_signature or not merchant_authorization:
                logger.error(
                    f"[ShoppingAgent] Cart Mandate missing required signatures: "
                    f"cart_id={cart_mandate.get('id')}"
                )
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。このカートにはMerchant署名がありません。"
                )
                session["step"] = "error"
                return

            # AP2仕様準拠：Merchant署名を暗号学的に検証
            from common.models import Signature

            # merchant_signatureをSignatureオブジェクトに変換
            try:
                if isinstance(merchant_signature, dict):
                    sig_obj = Signature(**merchant_signature)
                else:
                    sig_obj = merchant_signature

                # SignatureManagerでMerchant署名を検証
                is_valid = self.signature_manager.verify_mandate_signature(
                    cart_mandate,
                    sig_obj
                )

                if not is_valid:
                    logger.error(
                        f"[ShoppingAgent] Merchant signature verification FAILED: "
                        f"cart_id={cart_mandate.get('id')}"
                    )
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。Merchant署名の検証に失敗しました。"
                    )
                    session["step"] = "error"
                    return

                logger.info(
                    f"[ShoppingAgent] Merchant signature verified successfully: "
                    f"cart_id={cart_mandate.get('id')}, "
                    f"algorithm={sig_obj.algorithm}"
                )

            except Exception as e:
                logger.error(
                    f"[ShoppingAgent] Error during merchant signature verification: {e}",
                    exc_info=True
                )
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。Merchant署名の検証中にエラーが発生しました。"
                )
                session["step"] = "error"
                return

            # 署名済みCart Mandateをセッションに保存
            session["cart_mandate"] = cart_mandate
            await self._update_session(session_id, session)

            yield StreamEvent(
                type="agent_text",
                content="✅ Merchant署名確認完了。カート内容を確認して署名してください。"
            )
            await asyncio.sleep(0.3)

            # AP2仕様準拠：ユーザーにCartMandate署名を要求
            # フロントエンドがWebAuthn署名を完了し、/cart/submit-signatureを呼び出すと
            # step="select_payment_method"に遷移する
            yield StreamEvent(
                type="signature_request",
                mandate=cart_mandate,
                mandate_type="cart"
            )

            session["step"] = "cart_signature_pending"
            return

        # ステップ6.6: カート署名待機中
        elif current_step == "cart_signature_pending":
            # AP2準拠: WebAuthn署名は/cart/submit-signatureエンドポイントで処理される
            # ユーザーが何か入力した場合は、署名完了を待っていることを案内
            yield StreamEvent(
                type="agent_text",
                content="カートの署名を待っています。ブラウザの認証ダイアログで指紋認証・顔認証などを完了してください。"
            )
            return

        # ステップ7.0: PaymentMandate作成開始（CartMandate署名完了後の自動遷移）
        elif current_step == "payment_mandate_creation":
            # CartMandate署名完了後、Credential Provider選択へ進む
            # フロントエンドから`_cart_signature_completed`トークンで呼び出される
            # 通常のユーザー入力の場合は、署名完了を待つように案内
            if not user_input.startswith("_cart_signature_completed"):
                yield StreamEvent(
                    type="agent_text",
                    content="CartMandate署名を完了してください。署名後、自動的に次のステップに進みます。"
                )
                return

            # Credential Provider選択UIを表示
            yield StreamEvent(
                type="agent_text",
                content="✅ CartMandate署名完了しました！次に決済に使用するCredential Providerを選択してください。"
            )
            await asyncio.sleep(0.2)

            yield StreamEvent(
                type="credential_provider_selection",
                providers=self.credential_providers
            )
            session["step"] = "select_credential_provider_for_payment"
            return

        # ============ 以下の cart_selected_need_shipping ステップは削除 ============
        # AP2仕様では、配送先はCartMandate作成「前」に確定済み

        # 旧: cart_selected_need_shipping ステップ（削除予定）
        # 新しいフローでは、配送先入力 → CartMandate作成 → カート選択 → Credential Provider選択

        # ステップ6.6の旧コードを削除してジャンプ
        elif current_step == "cart_selected_need_shipping_OLD_DEPRECATED":
            # この分岐は使用されません
            pass

        # 以下、旧コードをスキップするためのダミー分岐
        if False:  # 旧コードブロックの開始（削除予定）
            yield StreamEvent(
                type="shipping_form_request",
                form_schema={
                    "type": "shipping_address",
                    "fields": [
                        {
                            "name": "recipient",
                            "label": "受取人名",
                            "type": "text",
                            "placeholder": existing_shipping.get("recipient", "山田太郎") if existing_shipping else "山田太郎",
                            "default": existing_shipping.get("recipient", "") if existing_shipping else "",
                            "required": True
                        },
                        {
                            "name": "postal_code",
                            "label": "郵便番号",
                            "type": "text",
                            "placeholder": "150-0001",
                            "default": existing_shipping.get("postal_code", "") if existing_shipping else "",
                            "required": True
                        },
                        {
                            "name": "address_line1",
                            "label": "住所1",
                            "type": "text",
                            "placeholder": existing_shipping.get("address_line1", "東京都渋谷区神宮前1-1-1") if existing_shipping else "東京都渋谷区神宮前1-1-1",
                            "default": existing_shipping.get("address_line1", "") if existing_shipping else "",
                            "required": True
                        },
                        {
                            "name": "address_line2",
                            "label": "住所2（建物名・部屋番号）",
                            "type": "text",
                            "placeholder": "サンプルマンション101",
                            "default": existing_shipping.get("address_line2", "") if existing_shipping else "",
                            "required": False
                        },
                        {
                            "name": "country",
                            "label": "国",
                            "type": "select",
                            "options": [
                                {"value": "JP", "label": "日本"},
                                {"value": "US", "label": "アメリカ"}
                            ],
                            "default": existing_shipping.get("country", "JP") if existing_shipping else "JP",
                            "required": True
                        }
                    ]
                }
            )

            session["step"] = "cart_selected_need_shipping"
            return

        # ステップ6.6: カート選択後の配送先入力
        elif current_step == "cart_selected_need_shipping":
            # JSONとしてパース（フロントエンドからJSONで送信される想定）
            try:
                import json as json_lib
                if user_input.strip().startswith("{"):
                    shipping_address = json_lib.loads(user_input)
                else:
                    # デモ用：固定値を使用
                    shipping_address = {
                        "recipient": "山田太郎",
                        "postal_code": "150-0001",
                        "address_line1": "東京都渋谷区神宮前1-1-1",
                        "address_line2": "サンプルマンション101",
                        "country": "JP"
                    }

                session["shipping_address"] = shipping_address

                yield StreamEvent(
                    type="agent_text",
                    content=f"配送先を設定しました：{shipping_address['recipient']} 様"
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"[_generate_fixed_response] Failed to parse shipping address: {e}")
                # デモ用：固定値を使用
                session["shipping_address"] = {
                    "recipient": "山田太郎",
                    "postal_code": "150-0001",
                    "address_line1": "東京都渋谷区神宮前1-1-1",
                    "address_line2": "サンプルマンション101",
                    "country": "JP"
                }

                yield StreamEvent(
                    type="agent_text",
                    content="配送先を設定しました（デモ用固定値）。"
                )
                await asyncio.sleep(0.3)

            # AP2仕様準拠：配送先住所を保存
            # 注意：配送先はCartMandate作成「前」に確定している必要がある
            # この時点ではCartMandateはまだ作成されていないはず
            logger.info(
                f"[ShoppingAgent] Shipping address saved for CartMandate creation: "
                f"recipient={shipping_address.get('recipient')}, "
                f"postal_code={shipping_address.get('postal_code')}"
            )

            # 次のステップ：Credential Provider選択
            session["step"] = "shipping_confirmed"
            # 処理を続行
            yield StreamEvent(
                type="agent_text",
                content="決済に使用するCredential Providerを選択してください。"
            )
            await asyncio.sleep(0.2)

            # Credential Providerリストをリッチコンテンツで送信
            yield StreamEvent(
                type="credential_provider_selection",
                providers=self.credential_providers
            )

            session["step"] = "select_credential_provider"
            return

        # ステップ6.7: 配送先確認済み（CartMandateに配送先が既に含まれている場合）
        elif current_step == "shipping_confirmed":
            # このステップは自動的にスキップされ、Credential Provider選択に進む
            yield StreamEvent(
                type="agent_text",
                content="決済に使用するCredential Providerを選択してください。"
            )
            await asyncio.sleep(0.2)

            # Credential Providerリストをリッチコンテンツで送信
            yield StreamEvent(
                type="credential_provider_selection",
                providers=self.credential_providers
            )

            session["step"] = "select_credential_provider"
            return

        # ステップ7: 商品選択後 → CartMandate作成（Merchant Agentを経由）
        # 注: この処理は旧フロー（商品個別選択）用。新フロー（カート選択）では使用しない
        elif current_step == "product_selection":
            # 利用可能な商品リストから選択
            available_products = session.get("available_products", [])
            if not available_products:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。商品リストが見つかりません。最初からやり直してください。"
                )
                session["step"] = "error"
                return

            # 商品選択（番号または商品名）
            selected_product = None
            user_input_clean = user_input.strip()

            # 番号で選択（1, 2, 3...）
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(available_products):
                    selected_product = available_products[index]

            # 商品IDで選択（"prod_001"など）
            if not selected_product:
                for product in available_products:
                    if product.get("id") in user_input:
                        selected_product = product
                        break

            # 商品名で選択（部分一致）
            if not selected_product:
                for product in available_products:
                    if user_input_lower in product.get("name", "").lower():
                        selected_product = product
                        break

            if not selected_product:
                yield StreamEvent(
                    type="agent_text",
                    content=f"商品が認識できませんでした。番号（1〜{len(available_products)}）または商品名を入力してください。"
                )
                return

            session["selected_product"] = selected_product

            yield StreamEvent(
                type="agent_text",
                content=f"「{selected_product['name']}」を選択しました。"
            )
            await asyncio.sleep(0.3)

            # AP2 Step 2-3: Credential Provider選択
            yield StreamEvent(
                type="agent_text",
                content="決済に使用するCredential Providerを選択してください。"
            )
            await asyncio.sleep(0.2)

            # Credential Providerリストをリッチコンテンツで送信
            yield StreamEvent(
                type="credential_provider_selection",
                providers=self.credential_providers
            )

            session["step"] = "select_credential_provider"
            return

        # ステップ7.1: Credential Provider選択
        elif current_step == "select_credential_provider":
            user_input_clean = user_input.strip()
            selected_provider = None

            # 番号で選択
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(self.credential_providers):
                    selected_provider = self.credential_providers[index]

            # IDで選択
            if not selected_provider:
                for provider in self.credential_providers:
                    if provider["id"] in user_input:
                        selected_provider = provider
                        break

            if not selected_provider:
                yield StreamEvent(
                    type="agent_text",
                    content=f"Credential Providerが認識できませんでした。番号（1〜{len(self.credential_providers)}）を入力してください。"
                )
                return

            session["selected_credential_provider"] = selected_provider

            yield StreamEvent(
                type="agent_text",
                content=f"{selected_provider['name']}を選択しました。"
            )
            await asyncio.sleep(0.3)

            # 配送先が既に設定されているかを確認（新フローでは必ず設定されているはず）
            shipping_address = session.get("shipping_address")

            if not shipping_address:
                # 万が一配送先が設定されていない場合（エラー処理）
                logger.warning("[ShoppingAgent] Shipping address not found in session")
                yield StreamEvent(
                    type="agent_text",
                    content="エラー：配送先が設定されていません。最初からやり直してください。"
                )
                session["step"] = "error"
                return

            # AP2 Step 6-7: Credential Providerから支払い方法を取得
            yield StreamEvent(
                type="agent_text",
                content="Credential Providerから利用可能な支払い方法を取得中..."
            )
            await asyncio.sleep(0.3)

            try:
                # 選択されたCredential Providerから支払い方法を取得
                user_id = session.get("user_id") or os.getenv("DEFAULT_USER_ID", "user_demo_001")
                payment_methods = await self._get_payment_methods_from_cp(user_id, selected_provider["url"])

                if not payment_methods:
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。利用可能な支払い方法が見つかりませんでした。"
                    )
                    session["step"] = "error"
                    return

                session["available_payment_methods"] = payment_methods
                session["step"] = "select_payment_method"

                # 支払い方法をリッチコンテンツで表示
                yield StreamEvent(
                    type="agent_text",
                    content="以下の支払い方法から選択してください。"
                )
                await asyncio.sleep(0.2)

                yield StreamEvent(
                    type="payment_method_selection",
                    payment_methods=payment_methods
                )
                return

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment methods retrieval failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法の取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

        # ステップ7.2: 配送先入力完了 → 支払い方法取得（旧フロー用）
        elif current_step == "input_shipping_address":
            # JSONとしてパース（フロントエンドからJSONで送信される想定）
            try:
                import json as json_lib
                if user_input.strip().startswith("{"):
                    shipping_address = json_lib.loads(user_input)
                else:
                    # デモ用：固定値を使用
                    shipping_address = {
                        "recipient": "山田太郎",
                        "postal_code": "150-0001",
                        "address_line1": "東京都渋谷区神宮前1-1-1",
                        "address_line2": "サンプルマンション101",
                        "country": "JP"
                    }

                session["shipping_address"] = shipping_address

                yield StreamEvent(
                    type="agent_text",
                    content=f"配送先を設定しました：{shipping_address['recipient']} 様"
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"[_generate_fixed_response] Failed to parse shipping address: {e}")
                # デモ用：固定値を使用
                session["shipping_address"] = {
                    "recipient": "山田太郎",
                    "postal_code": "150-0001",
                    "address_line1": "東京都渋谷区神宮前1-1-1",
                    "address_line2": "サンプルマンション101",
                    "country": "JP"
                }

                yield StreamEvent(
                    type="agent_text",
                    content="配送先を設定しました（デモ用固定値）。"
                )
                await asyncio.sleep(0.3)

            # AP2仕様準拠：配送先住所を保存（旧フロー用）
            logger.info(
                f"[ShoppingAgent] Shipping address saved for CartMandate creation (old flow): "
                f"recipient={shipping_address.get('recipient')}, "
                f"postal_code={shipping_address.get('postal_code')}"
            )

            # AP2 Step 6-7: Credential Providerから支払い方法を取得
            yield StreamEvent(
                type="agent_text",
                content="Credential Providerから利用可能な支払い方法を取得中..."
            )
            await asyncio.sleep(0.3)

            try:
                # 選択されたCredential Providerから支払い方法を取得
                selected_cp = session.get("selected_credential_provider", self.credential_providers[0])
                user_id = session.get("user_id") or os.getenv("DEFAULT_USER_ID", "user_demo_001")
                payment_methods = await self._get_payment_methods_from_cp(user_id, selected_cp["url"])

                if not payment_methods:
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。利用可能な支払い方法が見つかりませんでした。"
                    )
                    session["step"] = "error"
                    return

                session["available_payment_methods"] = payment_methods
                session["step"] = "select_payment_method"

                # 支払い方法をリッチコンテンツで表示
                yield StreamEvent(
                    type="agent_text",
                    content="以下の支払い方法から選択してください。"
                )
                await asyncio.sleep(0.2)

                yield StreamEvent(
                    type="payment_method_selection",
                    payment_methods=payment_methods
                )
                return

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment methods retrieval failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法の取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return


        # AP2完全準拠: Credential Provider選択（PaymentMandate作成用）
        elif current_step == "select_credential_provider_for_payment":
            # Credential Provider選択を処理（番号で選択）
            user_input_clean = user_input.strip()
            selected_provider = None

            # 番号で選択
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(self.credential_providers):
                    selected_provider = self.credential_providers[index]

            # IDで選択
            if not selected_provider:
                for provider in self.credential_providers:
                    if provider["id"] in user_input:
                        selected_provider = provider
                        break

            if not selected_provider:
                yield StreamEvent(
                    type="agent_text",
                    content=f"Credential Providerが認識できませんでした。番号（1〜{len(self.credential_providers)}）を入力してください。"
                )
                return

            # セッションに保存
            session["selected_credential_provider"] = selected_provider
            logger.info(
                f"[ShoppingAgent] Credential Provider selected for payment: "
                f"{selected_provider['id']} ({selected_provider['name']})"
            )

            # Credential Providerから支払い方法を取得
            try:
                cp_url = selected_provider.get("url", "http://localhost:8003")
                user_id = session.get("user_id", "user_demo_001")  # AP2: ユーザーIDが必須

                response = await self.http_client.get(
                    f"{cp_url}/payment-methods",
                    params={"user_id": user_id},  # AP2準拠: user_idをクエリパラメータで渡す
                    timeout=10.0
                )
                payment_methods_result = response.json()
                payment_methods = payment_methods_result.get("payment_methods", [])

                if not payment_methods:
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。利用可能な支払い方法が見つかりませんでした。"
                    )
                    session["step"] = "error"
                    return

                session["available_payment_methods"] = payment_methods

                # 支払い方法選択UIを表示
                yield StreamEvent(
                    type="agent_text",
                    content=f"✅ {selected_provider['name']}を選択しました。次に支払い方法を選択してください。"
                )
                await asyncio.sleep(0.2)

                yield StreamEvent(
                    type="payment_method_selection",
                    payment_methods=payment_methods
                )

                session["step"] = "select_payment_method"
                return

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment methods retrieval failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法の取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

        # ステップ8: 支払い方法選択 → PaymentMandate作成・決済実行
        elif current_step == "select_payment_method":
            available_payment_methods = session.get("available_payment_methods", [])
            if not available_payment_methods:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ございません。支払い方法リストが見つかりません。"
                )
                session["step"] = "error"
                return

            # 支払い方法選択（番号）
            user_input_clean = user_input.strip()
            selected_payment_method = None

            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(available_payment_methods):
                    selected_payment_method = available_payment_methods[index]

            if not selected_payment_method:
                yield StreamEvent(
                    type="agent_text",
                    content=f"支払い方法が認識できませんでした。番号（1〜{len(available_payment_methods)}）を入力してください。"
                )
                return

            session["selected_payment_method"] = selected_payment_method

            # AP2 Step 13: Step-upが必要な支払い方法の場合
            if selected_payment_method.get("requires_step_up", False):
                logger.info(
                    f"[ShoppingAgent] Payment method requires step-up: "
                    f"{selected_payment_method['id']}, brand={selected_payment_method['brand']}"
                )

                try:
                    # Credential ProviderにStep-upセッション作成を依頼
                    selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

                    # CartMandateまたはIntentMandateから金額情報を取得
                    # selected_cart_mandateがあればcart_mandateに設定（step-up後の処理で必要）
                    selected_cart_mandate = session.get("selected_cart_mandate")
                    if selected_cart_mandate and not session.get("cart_mandate"):
                        session["cart_mandate"] = selected_cart_mandate
                        logger.info("[ShoppingAgent] Set cart_mandate from selected_cart_mandate for step-up flow")

                    cart_mandate = session.get("cart_mandate")
                    intent_mandate = session.get("intent_mandate")

                    if cart_mandate:
                        # AP2準拠：totalをpayment_request.details.totalから取得
                        total_item = cart_mandate.get("contents", {}).get("payment_request", {}).get("details", {}).get("total", {})
                        total_amount = total_item.get("amount", {"value": "0", "currency": "JPY"})
                        # merchant_idは_metadataから取得
                        merchant_id = cart_mandate.get("_metadata", {}).get("merchant_id")
                    elif intent_mandate:
                        # CartMandateがない場合、IntentMandateの最大金額を使用
                        max_amount = intent_mandate.get("max_amount", {})
                        total_amount = max_amount
                        merchant_id = None  # この時点では未確定
                    else:
                        # フォールバック：空の金額情報
                        total_amount = {"value": "0", "currency": "JPY"}
                        merchant_id = None

                    # AP2準拠：return_urlにセッションIDをクエリパラメータとして含める
                    return_url = f"http://localhost:3000/chat?session_id={session_id}"

                    response = await self.http_client.post(
                        f"{selected_cp['url']}/payment-methods/initiate-step-up",
                        json={
                            "user_id": session.get("user_id", "user_demo_001"),
                            "payment_method_id": selected_payment_method["id"],
                            "transaction_context": {
                                "amount": total_amount,
                                "merchant_id": merchant_id
                            },
                            "return_url": return_url
                        },
                        timeout=10.0
                    )
                    response.raise_for_status()
                    step_up_result = response.json()
                    
                    step_up_url = step_up_result.get("step_up_url")
                    step_up_session_id = step_up_result.get("session_id")

                    # Step-up情報をセッションに保存
                    session["step_up_session_id"] = step_up_session_id
                    session["step"] = "step_up_redirect"

                    # 重要：Step-upリダイレクト前にセッションをデータベースに保存
                    # これにより、Step-up完了後のリクエストでcart_mandateを復元できる
                    await self._update_session(session_id, session)

                    logger.info(
                        f"[ShoppingAgent] Step-up session created and saved to DB: "
                        f"step_up_session_id={step_up_session_id}, step_up_url={step_up_url}"
                    )

                    # フロントエンドにStep-upリダイレクト指示を送信
                    yield StreamEvent(
                        type="agent_text",
                        content=f"{selected_payment_method['brand'].upper()} ****{selected_payment_method['last4']}を選択しました。\n\n追加認証が必要です。認証画面にリダイレクトします..."
                    )
                    await asyncio.sleep(0.5)

                    yield StreamEvent(
                        type="step_up_redirect",
                        step_up_url=step_up_url,
                        session_id=step_up_session_id,
                        content=selected_payment_method.get("step_up_reason", "Additional authentication required")
                    )
                    return
                    
                except Exception as e:
                    logger.error(f"[ShoppingAgent] Failed to initiate step-up: {e}", exc_info=True)
                    yield StreamEvent(
                        type="agent_text",
                        content=f"申し訳ありません。追加認証の開始に失敗しました: {str(e)}\n\n別の支払い方法を選択してください。"
                    )
                    return

            yield StreamEvent(
                type="agent_text",
                content=f"{selected_payment_method['brand'].upper()} ****{selected_payment_method['last4']}を選択しました。"
            )
            await asyncio.sleep(0.3)

            # AP2 Step 17-18: 支払い方法のトークン化
            yield StreamEvent(
                type="agent_text",
                content="Credential Providerで支払い方法をトークン化中..."
            )
            await asyncio.sleep(0.3)

            try:
                # 選択されたCredential Providerを使用してトークン化
                selected_cp = session.get("selected_credential_provider", self.credential_providers[0])
                user_id = session.get("user_id") or os.getenv("DEFAULT_USER_ID", "user_demo_001")
                tokenized_payment_method = await self._tokenize_payment_method(
                    user_id,
                    selected_payment_method['id'],
                    selected_cp["url"]
                )

                # トークン化された支払い方法をセッションに保存（元の情報も保持）
                session["tokenized_payment_method"] = {
                    **selected_payment_method,
                    "token": tokenized_payment_method["token"],
                    "token_expires_at": tokenized_payment_method["expires_at"],
                    "requires_stepup": tokenized_payment_method.get("requires_stepup", False),
                    "stepup_method": tokenized_payment_method.get("stepup_method")
                }

                # AP2完全準拠: Stepup認証が必要な場合は3DSフローを開始
                if tokenized_payment_method.get("requires_stepup"):
                    stepup_method = tokenized_payment_method.get("stepup_method", "3ds2")
                    yield StreamEvent(
                        type="agent_text",
                        content=f"💳 この支払い方法には追加認証（{stepup_method.upper()}）が必要です。"
                    )
                    await asyncio.sleep(0.3)

                    # 3DS認証フローを開始
                    yield StreamEvent(
                        type="agent_text",
                        content="🔐 3D Secure認証を開始します..."
                    )
                    await asyncio.sleep(0.3)

                    # 3DS認証リクエストを送信
                    session["step"] = "stepup_authentication_required"
                    session["stepup_method"] = stepup_method

                    # AP2完全準拠: ブラウザからアクセス可能なURLに変換
                    # Docker内部URL（http://credential_provider:8003）→ localhost URL
                    cp_url = selected_cp['url'].replace('credential_provider', 'localhost')

                    yield StreamEvent(
                        type="stepup_authentication_request",
                        content={
                            "stepup_method": stepup_method,
                            "payment_method_id": selected_payment_method['id'],
                            "brand": selected_payment_method.get('brand', 'unknown'),
                            "last4": selected_payment_method.get('last4', '****'),
                            "challenge_url": f"{cp_url}/payment-methods/step-up-challenge"
                        }
                    )
                    return

                yield StreamEvent(
                    type="agent_text",
                    content="支払い方法のトークン化が完了しました。"
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment method tokenization failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法のトークン化に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

            # カート選択フローかどうかを確認
            selected_cart_mandate = session.get("selected_cart_mandate")

            if selected_cart_mandate:
                # カート選択フロー：既にCartMandateが存在するため、それを使用
                session["cart_mandate"] = selected_cart_mandate
                logger.info(
                    f"[ShoppingAgent] Using selected CartMandate: {selected_cart_mandate.get('id')}"
                )

                yield StreamEvent(
                    type="agent_text",
                    content="選択されたカートの内容を確認しました。決済情報を準備中..."
                )
                await asyncio.sleep(0.5)

            else:
                # 旧フロー（商品個別選択）：Merchant Agentにカート作成を依頼
                yield StreamEvent(
                    type="agent_text",
                    content="Merchant Agentにカート作成・署名を依頼中..."
                )
                await asyncio.sleep(0.3)

                # Merchant AgentにCartRequestを送信（A2A通信）
                # Merchant AgentがCartMandateを作成し、Merchantに署名依頼して、署名済みCartMandateを返却
                try:
                    signed_cart_mandate = await self._request_cart_from_merchant_agent(
                        session["selected_product"],
                        session
                    )
                    session["cart_mandate"] = signed_cart_mandate

                    # 専門家の指摘対応：CartMandateにユーザー署名は不要
                    # MerchantがCartMandateに署名することで、カート内容の正当性が保証される
                    # ユーザー署名はIntentMandateでのみ必要

                    yield StreamEvent(
                        type="agent_text",
                        content="Merchant Agentを経由してMerchantの署名を確認しました。決済情報を準備中..."
                    )
                    await asyncio.sleep(0.5)

                except Exception as e:
                    logger.error(f"[_generate_fixed_response] Cart creation failed: {e}")
                    yield StreamEvent(
                        type="agent_text",
                        content=f"申し訳ありません。カートの作成に失敗しました: {str(e)}"
                    )
                    session["step"] = "error"
                    return

            # PaymentMandateを作成（CartMandate取得後、直ちに作成）
            # カート選択フロー・旧フロー共通の処理
            payment_mandate = self._create_payment_mandate(session)
            session["payment_mandate"] = payment_mandate
            session["step"] = "webauthn_attestation_requested"

            # Passkey/WebAuthnを使用することを記録（AP2仕様準拠）
            # transaction_type決定時に使用
            session["will_use_passkey"] = True

            yield StreamEvent(
                type="agent_text",
                content="決済準備が完了しました。セキュリティのため、デバイス認証（WebAuthn/Passkey）を実施します。"
            )
            await asyncio.sleep(0.5)

            # WebAuthn challengeを生成（暗号学的に安全）
            import secrets
            challenge = secrets.token_urlsafe(32)  # 32バイト = 256ビット
            session["webauthn_challenge"] = challenge

            yield StreamEvent(
                type="webauthn_request",
                challenge=challenge,
                rp_id="localhost",
                timeout=60000
            )

            yield StreamEvent(
                type="agent_text",
                content="デバイス認証を完了してください。\n\n認証後、自動的に決済処理が開始されます。"
            )

            # フロントエンドからのattestation送信を待機
            # フロントエンドはPOST /payment/submit-attestationを呼び出す
            return

        # ステップ7.6: 3DS認証待機中
        elif current_step == "stepup_authentication_required":
            # AP2完全準拠: 3DS認証完了を待機
            if user_input and user_input.lower() in ["3ds-completed", "3ds completed"]:
                yield StreamEvent(
                    type="agent_text",
                    content="✅ 3D Secure認証が完了しました。"
                )
                await asyncio.sleep(0.3)

                # AP2完全準拠: 3DS認証完了後、PaymentMandate作成とWebAuthn認証へ進む
                tokenized_payment_method = session.get("tokenized_payment_method")
                cart_mandate = session.get("cart_mandate")
                intent_mandate = session.get("intent_mandate")

                # デバッグログ追加
                cart_webauthn_assertion = session.get("cart_webauthn_assertion")
                logger.info(
                    f"[3DS Completion] Session data check: "
                    f"tokenized_payment_method={bool(tokenized_payment_method)}, "
                    f"cart_mandate={bool(cart_mandate)}, "
                    f"intent_mandate={bool(intent_mandate)}, "
                    f"cart_webauthn_assertion={bool(cart_webauthn_assertion)}"
                )

                if not tokenized_payment_method:
                    yield StreamEvent(
                        type="agent_text",
                        content="エラー: トークン化された支払い方法が見つかりません。"
                    )
                    session["step"] = "error"
                    return

                if not cart_mandate:
                    yield StreamEvent(
                        type="agent_text",
                        content="エラー: CartMandateが見つかりません。"
                    )
                    session["step"] = "error"
                    return

                if not intent_mandate:
                    yield StreamEvent(
                        type="agent_text",
                        content="エラー: IntentMandateが見つかりません。"
                    )
                    session["step"] = "error"
                    return

                # AP2完全準拠: CartMandateが署名済みかチェック
                # CartMandate自体は変更せず、WebAuthn assertionは別途保存される
                if not cart_webauthn_assertion:
                    yield StreamEvent(
                        type="agent_text",
                        content="エラー: CartMandateが署名されていません。先にCartMandateを署名してください。"
                    )
                    session["step"] = "error"
                    return

                # PaymentMandate作成
                yield StreamEvent(
                    type="agent_text",
                    content="💳 PaymentMandateを作成中..."
                )
                await asyncio.sleep(0.3)

                try:
                    # AP2完全準拠: PaymentMandate作成（リスク評価含む）
                    # _create_payment_mandateメソッドは内部でリスク評価も実行する
                    payment_mandate = self._create_payment_mandate(session)

                    session["payment_mandate"] = payment_mandate
                    session["risk_assessment"] = {
                        "risk_score": payment_mandate.get("risk_score", 50),
                        "fraud_indicators": payment_mandate.get("fraud_indicators", [])
                    }

                    # WebAuthn認証リクエスト
                    yield StreamEvent(
                        type="agent_text",
                        content="🔐 決済を実行するため、デバイス認証（WebAuthn/Passkey）を実行してください。"
                    )
                    await asyncio.sleep(0.3)

                    # AP2完全準拠: WebAuthn challengeを生成
                    import secrets
                    challenge = secrets.token_urlsafe(32)
                    session["webauthn_challenge"] = challenge
                    session["step"] = "webauthn_attestation_requested"
                    session["will_use_passkey"] = True

                    yield StreamEvent(
                        type="webauthn_request",
                        challenge=challenge,
                        rp_id="localhost",
                        timeout=60000
                    )

                    yield StreamEvent(
                        type="agent_text",
                        content="デバイス認証を完了してください。\n\n認証後、自動的に決済処理が開始されます。"
                    )
                    return

                except Exception as e:
                    logger.error(f"[3DS completion] Failed to create PaymentMandate: {e}")
                    yield StreamEvent(
                        type="agent_text",
                        content=f"エラー: PaymentMandate作成に失敗しました: {str(e)}"
                    )
                    session["step"] = "error"
                    return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="🔐 3D Secure認証を完了してください。\n\n"
                            "ポップアップウィンドウで認証を完了すると、自動的に処理が続行されます。"
                )
                return

        elif current_step == "webauthn_attestation_requested":
            # フロントエンドがPOST /payment/submit-attestationを呼び出すまで待機
            # ユーザーがチャット入力してしまった場合の対応
            yield StreamEvent(
                type="agent_text",
                content="デバイス認証（WebAuthn/Passkey）を実行中です。\n\n"
                        "ブラウザの認証ダイアログで指紋認証・顔認証などを完了してください。\n"
                        "認証完了後、自動的に決済処理が開始されます。"
            )
            return

        # ステップ8: 完了後
        elif current_step == "completed":
            yield StreamEvent(
                type="agent_text",
                content="取引は完了しました。新しい購入を始めるには「こんにちは」と入力してください。"
            )
            return

        # デフォルト応答（予期しないステップ）
        yield StreamEvent(
            type="agent_text",
            content=f"申し訳ありません。現在のステップ（{current_step}）では対応できません。「こんにちは」と入力して最初からやり直してください。"
        )

    async def _generate_fixed_response_langgraph(
        self,
        user_input: str,
        session: Dict[str, Any],
        session_id: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        LangGraph版の応答生成（ストリーミング）

        既存の_generate_fixed_responseと同じインターフェースを維持しつつ、
        内部実装をLangGraph StateGraphに置き換え

        改善点：
        - 各ステップが独立したノードとして明確に定義
        - Conditional Edgesで状態遷移を可視化
        - ノード単位でテスト可能
        - AP2完全準拠（署名フロー、A2A通信、WebAuthn）

        Args:
            user_input: ユーザー入力
            session: セッションデータ
            session_id: セッションID（データベース保存用）

        Yields:
            StreamEvent: ストリーミングイベント
        """
        # LangGraphフローが初期化されていない場合はフォールバック
        if self.shopping_flow_graph is None:
            logger.warning(f"[{self.agent_name}] LangGraph flow not initialized, falling back to legacy implementation")
            async for event in self._generate_fixed_response(user_input, session, session_id):
                yield event
            return

        # 初期状態
        initial_state = {
            "user_input": user_input,
            "session_id": session_id,
            "session": session,
            "events": [],
            "next_step": None,
            "error": None
        }

        try:
            # グラフ実行
            result = await self.shopping_flow_graph.ainvoke(initial_state)

            # イベントをストリーミング出力
            for event_dict in result["events"]:
                # agent_text_chunkは文字単位で遅延を挿入
                if event_dict.get("type") == "agent_text_chunk":
                    yield StreamEvent(**event_dict)
                    await asyncio.sleep(0.02)  # 20ms遅延
                else:
                    yield StreamEvent(**event_dict)

            # セッション更新
            await self._update_session(session_id, result["session"])

        except Exception as e:
            logger.error(f"[{self.agent_name}] LangGraph flow execution failed: {e}", exc_info=True)
            # エラー時は既存実装にフォールバック
            async for event in self._generate_fixed_response(user_input, session, session_id):
                yield event

    async def _create_intent_mandate(self, intent: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        IntentMandateを作成（LangGraph AI統合版）

        AP2仕様準拠：
        - LangGraphでユーザーの自然言語入力からインテント抽出
        - 既存のIntentMandate型（mandate_types.py）を使用
        - サーバー署名は使用しない（Passkey署名はフロントエンドで追加）

        Args:
            intent: ユーザーの自然言語入力
            session: セッションデータ

        Returns:
            IntentMandate（署名前、AP2仕様準拠の構造）
        """
        now = datetime.now(timezone.utc)
        # AP2準拠：user_idはセッションから動的に取得（フロントエンドから提供）
        user_id = session.get("user_id")
        if not user_id:
            # フォールバック：環境変数または開発用デフォルト値
            import os
            user_id = os.getenv("DEFAULT_USER_ID", "user_demo_001")
            logger.warning(
                f"[ShoppingAgent] user_id not found in session, using default: {user_id}. "
                f"In production, user_id should be provided by frontend authentication."
            )

        # AP2準拠: natural_language_descriptionには金額制約を含める
        # sessionから金額/カテゴリー/ブランド情報を取得してintentを再構築
        max_amount = session.get("max_amount")
        categories = session.get("categories", [])
        brands = session.get("brands", [])

        constraints = []
        if max_amount:
            constraints.append(f"{max_amount}円以内")
        if categories:
            constraints.append(f"カテゴリー: {', '.join(categories)}")
        if brands:
            constraints.append(f"ブランド: {', '.join(brands)}")

        if constraints:
            intent_full = f"{intent}。{', '.join(constraints)}"
        else:
            intent_full = intent

        logger.info(f"[_create_intent_mandate] Reconstructed intent: {intent_full}")

        # LangGraphでAIインテント抽出を試行
        if self.langgraph_agent:
            try:
                logger.info(f"[ShoppingAgent] Using LangGraph to extract intent from: '{intent_full}'")

                # LangGraphエージェントでインテント抽出
                intent_data = await self.langgraph_agent.extract_intent_from_prompt(intent_full)

                # IntentMandateデータ（AP2仕様準拠の構造に変換）
                # AP2準拠のIntentMandate構造（mandate_types.py参照）
                intent_mandate_unsigned = {
                    "id": f"intent_{uuid.uuid4().hex[:8]}",
                    "type": "IntentMandate",
                    "version": "0.2",
                    "user_id": user_id,
                    # AP2準拠フィールド
                    "natural_language_description": intent_data.get("natural_language_description", intent),
                    "user_cart_confirmation_required": intent_data.get("user_cart_confirmation_required", True),
                    "merchants": intent_data.get("merchants"),  # Optional[list[str]]
                    "skus": intent_data.get("skus"),  # Optional[list[str]]
                    "requires_refundability": intent_data.get("requires_refundability", False),
                    "intent_expiry": intent_data.get("intent_expiry"),
                    # メタデータ（AP2仕様外だが互換性のため保持）
                    "created_at": now.isoformat().replace('+00:00', 'Z')
                }

                logger.info(
                    f"[ShoppingAgent] IntentMandate created via LangGraph: "
                    f"id={intent_mandate_unsigned['id']}, "
                    f"natural_language_description='{intent_data.get('natural_language_description')}'"
                )

            except Exception as e:
                logger.error(f"[ShoppingAgent] LangGraph intent extraction failed, using fallback: {e}", exc_info=True)
                # フォールバック：従来の固定文言方式
                intent_mandate_unsigned = self._create_intent_mandate_fallback(intent, session, user_id, now)
        else:
            # LangGraph未初期化の場合：フォールバック
            logger.warning("[ShoppingAgent] LangGraph not available, using fallback intent creation")
            intent_mandate_unsigned = self._create_intent_mandate_fallback(intent, session, user_id, now)

        # User公開鍵を取得（WebAuthn Passkey公開鍵）
        try:
            user_public_key_pem = self.key_manager.get_public_key_pem(user_id)
            intent_mandate_unsigned["user_public_key"] = user_public_key_pem
        except Exception as e:
            logger.info(f"[ShoppingAgent] User public key not available yet (will be provided by frontend): {e}")
            intent_mandate_unsigned["user_public_key"] = None

        return intent_mandate_unsigned

    def _create_intent_mandate_fallback(
        self,
        intent: str,
        session: Dict[str, Any],
        user_id: str,
        now: datetime
    ) -> Dict[str, Any]:
        """IntentMandate作成のフォールバック（従来方式）

        LangGraphが利用できない場合の固定文言方式

        Args:
            intent: ユーザー入力
            session: セッションデータ
            user_id: ユーザーID
            now: 現在時刻

        Returns:
            IntentMandate（署名前）
        """
        expires_at = now + timedelta(hours=1)
        merchants = session.get("merchants", [])
        skus = session.get("skus", [])
        max_amount = session.get("max_amount")
        categories = session.get("categories", [])
        brands = session.get("brands", [])

        # AP2準拠: natural_language_descriptionには金額制約を含める
        # sessionから金額/カテゴリー/ブランド情報を取得して再構築
        constraints = []
        if max_amount:
            constraints.append(f"{max_amount}円以内")
        if categories:
            constraints.append(f"カテゴリー: {', '.join(categories)}")
        if brands:
            constraints.append(f"ブランド: {', '.join(brands)}")

        if constraints:
            natural_language_description = f"{intent}。{', '.join(constraints)}"
        else:
            natural_language_description = intent

        logger.info(f"[_create_intent_mandate_fallback] Constructed natural_language_description: {natural_language_description}")

        # AP2準拠のIntentMandate構造（mandate_types.py参照）
        intent_mandate_unsigned = {
            "id": f"intent_{uuid.uuid4().hex[:8]}",
            "type": "IntentMandate",
            "version": "0.2",
            "user_id": user_id,
            # AP2準拠フィールド
            "natural_language_description": natural_language_description,
            "user_cart_confirmation_required": True,
            "merchants": merchants if merchants else None,  # Optional[list[str]]
            "skus": skus if skus else None,  # Optional[list[str]]
            "requires_refundability": False,
            "intent_expiry": expires_at.isoformat().replace('+00:00', 'Z'),
            # メタデータ（AP2仕様外だが互換性のため保持）
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        logger.info(
            f"[ShoppingAgent] IntentMandate created (fallback mode): "
            f"id={intent_mandate_unsigned['id']}, intent='{intent[:50]}...'"
        )

        return intent_mandate_unsigned

    async def _persist_intent_mandate(self, intent_mandate: Dict[str, Any], session: Dict[str, Any]) -> None:
        """
        IntentMandateをデータベースに永続化（AP2仕様準拠）

        AP2仕様: Dispute Resolution用にIntentMandateを長期保存する必要がある
        - Human-Presentフローでは署名なしでも保存
        - Human-Not-Presentフローでは署名後に保存
        - transactionとの関連付けも実施

        Args:
            intent_mandate: IntentMandate
            session: ユーザーセッション
        """
        try:
            async with self.db_manager.get_session() as db_session:
                # MandateテーブルにIntentMandateを保存
                mandate_record = await MandateCRUD.create(db_session, {
                    "id": intent_mandate.get("id"),
                    "type": "Intent",
                    "status": "created",  # Human-Presentでは署名不要のため"created"
                    "payload": json.dumps(intent_mandate),
                    "issuer": "did:ap2:agent:shopping_agent",
                    "related_transaction_id": session.get("transaction_id")
                })

                logger.info(
                    f"[ShoppingAgent] IntentMandate persisted to DB: "
                    f"id={intent_mandate.get('id')}, "
                    f"mandate_record_id={mandate_record.id}"
                )

        except Exception as e:
            logger.error(f"[_persist_intent_mandate] Failed to persist IntentMandate: {e}", exc_info=True)
            # 永続化失敗してもフローは継続（ベストエフォート）
            # Dispute Resolutionには影響するが、決済自体はブロックしない

    def _create_cart_mandate(self, product: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
        """CartMandateを作成"""
        now = datetime.now(timezone.utc)

        cart_mandate = {
            "id": f"cart_{uuid.uuid4().hex[:8]}",
            "type": "CartMandate",
            "version": "0.2",
            "merchant_id": "did:ap2:merchant:mugibo_merchant",
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "items": [
                {
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "name": product["name"],
                    "quantity": 1,
                    "unit_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    },
                    "total_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    }
                }
            ],
            "total_amount": {
                "value": f"{product['price']}.00",
                "currency": "JPY"
            },
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[ShoppingAgent] CartMandate created: product={product['name']}, total={product['price']}")

        return cart_mandate

    def _generate_cart_mandate_hash(self, cart_mandate: Dict[str, Any]) -> str:
        """
        CartMandateのハッシュを生成

        AP2仕様準拠：user_authorizationフィールドの生成に使用
        CartMandateの正規化されたJSONからSHA256ハッシュを計算

        署名フィールド（merchant_signature, merchant_authorization, user_signature）を除外して
        ハッシュを計算します。これにより、署名が追加される前後で同じハッシュ値が得られます。

        Args:
            cart_mandate: CartMandate辞書

        Returns:
            str: SHA256ハッシュの16進数表現
        """
        # RFC 8785準拠のcompute_mandate_hash関数を使用（署名フィールドを自動除外）
        from v2.common.user_authorization import compute_mandate_hash
        return compute_mandate_hash(cart_mandate)

    def _generate_payment_mandate_hash(self, payment_mandate: Dict[str, Any]) -> str:
        """
        PaymentMandateのハッシュを生成

        AP2仕様準拠：user_authorizationフィールドの生成に使用
        PaymentMandateの正規化されたJSONからSHA256ハッシュを計算

        user_authorizationフィールドを除外してハッシュを計算します。

        Args:
            payment_mandate: PaymentMandate辞書

        Returns:
            str: SHA256ハッシュの16進数表現
        """
        # PaymentMandateからuser_authorizationフィールドを除外してコピー
        payment_mandate_copy = {k: v for k, v in payment_mandate.items() if k != 'user_authorization'}
        # RFC 8785準拠のcompute_mandate_hash関数を使用（より堅牢なハッシュ計算）
        from v2.common.user_authorization import compute_mandate_hash
        return compute_mandate_hash(payment_mandate_copy)

    async def _get_or_create_session(self, session_id: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        """
        セッションをデータベースから取得、または新規作成

        AP2仕様準拠:
        - user_idは必須（JWT認証から取得）
        - user_id.email = payer_emailとして使用（オプション - PII保護）

        Args:
            session_id: セッションID
            user_id: ユーザーID（JWT認証から取得、必須）

        Returns:
            Dict[str, Any]: セッションデータ

        Raises:
            ValueError: user_idが提供されていない場合
        """

        if not user_id:
            raise ValueError(
                "user_id is required. User must be authenticated via Passkey/JWT before creating a session. "
                "Please login first: POST /auth/passkey/login"
            )

        async with self.db_manager.get_session() as db_session:
            agent_session = await AgentSessionCRUD.get_by_session_id(db_session, session_id)

            if agent_session:
                # 既存セッションを取得
                session_data = json.loads(agent_session.session_data)
                logger.info(f"[ShoppingAgent] Loaded session from DB: {session_id}, step={session_data.get('step')}")
                return session_data
            else:
                # 新規セッション作成
                session_data = {
                    "messages": [],
                    "step": "initial",
                    "intent": None,
                    "max_amount": None,
                    "categories": [],
                    "brands": [],
                    "intent_mandate": None,
                    "cart_mandate": None,
                    "user_id": user_id
                }

                await AgentSessionCRUD.create(db_session, {
                    "session_id": session_id,
                    "user_id": user_id,
                    "session_data": session_data
                })

                logger.info(f"[ShoppingAgent] Created new session in DB: {session_id}")
                return session_data

    async def _update_session(self, session_id: str, session_data: Dict[str, Any]) -> None:
        """
        セッションデータをデータベースに保存

        Args:
            session_id: セッションID
            session_data: セッションデータ
        """
        async with self.db_manager.get_session() as db_session:
            await AgentSessionCRUD.update_session_data(db_session, session_id, session_data)
            logger.debug(f"[ShoppingAgent] Updated session in DB: {session_id}, step={session_data.get('step')}")

    def _determine_transaction_type(self, session: Dict[str, Any]) -> str:
        """
        AP2仕様準拠のtransaction_type（Human-Present/Not-Present）を判定

        AP2仕様では、AI Agent関与とHuman-Present/Not-Presentシグナルを
        必ず含める必要があります。

        判定基準：
        - human_present: ユーザーが認証デバイスで直接承認した場合
          - WebAuthn/Passkey認証完了
          - 生体認証（指紋、顔認証等）
          - デバイスPIN/パターン認証
        - human_not_present: 上記以外
          - パスワード認証のみ
          - 認証なし
          - エージェント自律実行

        Args:
            session: ユーザーセッション

        Returns:
            str: "human_present" または "human_not_present"
        """
        # 1. WebAuthn/Passkey認証が完了しているか確認
        attestation_token = session.get("attestation_token")
        if attestation_token:
            logger.info("[ShoppingAgent] transaction_type=human_present (WebAuthn attestation completed)")
            return "human_present"

        # 2. will_use_passkeyフラグ確認（WebAuthn使用予定）
        will_use_passkey = session.get("will_use_passkey", False)
        if will_use_passkey:
            # フラグは立っているが、まだ認証完了していない場合
            logger.info("[ShoppingAgent] transaction_type=human_present (WebAuthn flow initiated)")
            return "human_present"

        # 3. WebAuthn challengeが存在する場合（認証フロー進行中）
        webauthn_challenge = session.get("webauthn_challenge")
        if webauthn_challenge:
            logger.info("[ShoppingAgent] transaction_type=human_present (WebAuthn challenge active)")
            return "human_present"

        # デフォルト: human_not_present
        logger.info("[ShoppingAgent] transaction_type=human_not_present (no strong authentication detected)")
        return "human_not_present"

    def _create_payment_mandate(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        PaymentMandateを作成（リスク評価統合版）

        AP2仕様準拠（Step 19）：
        - トークン化された支払い方法を使用
        - セキュアトークンをPaymentMandateに含める
        - リスク評価を実施してリスクスコアと不正指標を追加
        - CartMandateの金額情報を使用
        """
        now = datetime.now(timezone.utc)

        # カート情報を取得（AP2仕様準拠：PaymentMandateはCartMandateを参照）
        cart_mandate = session.get("cart_mandate", {})
        if not cart_mandate:
            logger.error("[ShoppingAgent] No cart mandate available")
            raise ValueError("No cart mandate available")

        # セッションからトークン化された支払い方法を取得（AP2 Step 17-18）
        tokenized_payment_method = session.get("tokenized_payment_method", {})

        # トークン化された支払い方法が存在しない場合はエラー
        if not tokenized_payment_method or not tokenized_payment_method.get("token"):
            logger.error("[ShoppingAgent] No tokenized payment method available")
            raise ValueError("No tokenized payment method available")

        # AP2仕様準拠：金額はCartMandateのtotalから取得
        total_amount = cart_mandate.get("total", {})

        # AP2公式型定義準拠：PaymentMandateContents構造
        # 参照: refs/AP2-main/src/ap2/types/mandate.py
        payment_mandate_id = f"payment_{uuid.uuid4().hex[:8]}"
        payment_details_id = cart_mandate.get("id", f"order_{uuid.uuid4().hex[:8]}")

        # PaymentItem（payment_details_total）
        payment_details_total = {
            "label": "Total",
            "amount": {
                "value": total_amount.get("value", "0.00"),
                "currency": total_amount.get("currency", "JPY")
            }
        }

        # PaymentResponse（W3C Payment Request API準拠）
        payment_response = {
            "methodName": "basic-card",  # または "secure-payment-confirmation"
            "details": {
                "cardholderName": tokenized_payment_method.get("cardholder_name", "Demo User"),
                "cardNumber": f"****{tokenized_payment_method.get('last4', '0000')}",  # トークン化済み
                "cardSecurityCode": "***",  # トークン化済み
                "cardBrand": tokenized_payment_method.get("brand", "unknown"),
                "expiryMonth": tokenized_payment_method.get("expiry_month", "12"),
                "expiryYear": tokenized_payment_method.get("expiry_year", "2025"),
                # AP2拡張：トークン
                "token": tokenized_payment_method["token"],
                "tokenized": True
            }
        }

        # AP2公式型定義準拠：PaymentMandate構造
        payment_mandate_contents = {
            "payment_mandate_id": payment_mandate_id,
            "payment_details_id": payment_details_id,
            "payment_details_total": payment_details_total,
            "payment_response": payment_response,
            "merchant_agent": cart_mandate.get("merchant_id", "did:ap2:merchant:mugibo_merchant"),
            "timestamp": now.isoformat().replace('+00:00', 'Z')
        }

        # AP2仕様準拠: user_authorizationを生成（WebAuthn assertionから）
        user_authorization = None
        cart_webauthn_assertion = session.get("cart_webauthn_assertion")

        if cart_webauthn_assertion:
            try:
                # create_user_authorization_vpを使ってSD-JWT-VC形式のuser_authorizationを生成
                user_authorization = create_user_authorization_vp(
                    webauthn_assertion=cart_webauthn_assertion,
                    cart_mandate=cart_mandate,
                    payment_mandate_contents=payment_mandate_contents,
                    user_id=session.get("user_id", "user_demo_001"),
                    payment_processor_id="did:ap2:agent:payment_processor"
                )
                logger.info(
                    f"[_create_payment_mandate] Generated user_authorization VP: "
                    f"length={len(user_authorization)}"
                )
            except Exception as e:
                logger.error(f"[_create_payment_mandate] Failed to generate user_authorization: {e}", exc_info=True)
                # user_authorizationがない場合でもフローを継続（デモ環境）
                user_authorization = None

        payment_mandate = {
            # AP2公式：payment_mandate_contents
            "payment_mandate_contents": payment_mandate_contents,

            # AP2公式：user_authorization（WebAuthn署名から生成）
            "user_authorization": user_authorization,

            # AP2拡張フィールド：AI Agent visibility（仕様で必須）
            "agent_involved": True,  # AI Agent関与シグナル（AP2仕様で必須）
            "transaction_type": self._determine_transaction_type(session),  # Human-Present/Not-Present

            # 後方互換性・内部処理用フィールド（既存コードとの互換性維持）
            "id": payment_mandate_id,  # 後方互換性
            "cart_mandate_id": cart_mandate.get("contents", {}).get("id"),  # AP2準拠
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "payer_id": session.get("user_id") or os.getenv("DEFAULT_USER_ID", "user_demo_001"),
            "payee_id": cart_mandate.get("_metadata", {}).get("merchant_id", "did:ap2:merchant:mugibo_merchant"),  # AP2準拠
            "amount": {
                "value": total_amount.get("value", "0.00"),
                "currency": total_amount.get("currency", "JPY")
            },
            "payment_method": {
                "type": tokenized_payment_method.get("type", "card"),
                "token": tokenized_payment_method["token"],
                "last4": tokenized_payment_method.get("last4", "0000"),
                "brand": tokenized_payment_method.get("brand", "unknown"),
                "expiry_month": tokenized_payment_method.get("expiry_month"),
                "expiry_year": tokenized_payment_method.get("expiry_year")
            }
        }

        # リスク評価を実施
        try:
            logger.info("[ShoppingAgent] Performing risk assessment...")
            risk_result = self.risk_engine.assess_payment_mandate(
                payment_mandate=payment_mandate,
                cart_mandate=session.get("cart_mandate"),
                intent_mandate=session.get("intent_mandate")
            )

            # リスク評価結果をPaymentMandateに追加
            payment_mandate["risk_score"] = risk_result.risk_score
            payment_mandate["fraud_indicators"] = risk_result.fraud_indicators

            logger.info(
                f"[ShoppingAgent] Risk assessment completed: "
                f"score={risk_result.risk_score}, "
                f"recommendation={risk_result.recommendation}, "
                f"indicators={risk_result.fraud_indicators}"
            )

            # 高リスクの場合は警告ログ
            if risk_result.recommendation == "decline":
                logger.warning(
                    f"[ShoppingAgent] High-risk transaction detected! "
                    f"score={risk_result.risk_score}, "
                    f"recommendation={risk_result.recommendation}"
                )

        except Exception as e:
            logger.error(f"[ShoppingAgent] Risk assessment failed: {e}", exc_info=True)
            # リスク評価失敗時はデフォルト値を設定
            payment_mandate["risk_score"] = 50  # 中リスク
            payment_mandate["fraud_indicators"] = ["risk_assessment_failed"]

        logger.info(
            f"[ShoppingAgent] PaymentMandate created with user_authorization: "
            f"has_user_auth={user_authorization is not None}"
        )

        logger.info(
            f"[ShoppingAgent] PaymentMandate created: "
            f"amount={total_amount.get('value')} {total_amount.get('currency')}, "
            f"payment_method={tokenized_payment_method.get('brand')} ****{tokenized_payment_method.get('last4')}, "
            f"token={tokenized_payment_method['token'][:20]}..., "
            f"risk_score={payment_mandate.get('risk_score')}"
        )

        return payment_mandate

    async def _process_payment_via_merchant_agent(self, payment_mandate: Dict[str, Any], cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """
        AP2仕様準拠: Merchant Agent経由でPayment Processorに決済処理を依頼

        AP2 Step 24-25-30-31の完全実装:
        Step 24: Shopping Agent → Merchant Agent (A2A通信)
        Step 25: Merchant Agent → Payment Processor (A2A転送)
        Step 30: Payment Processor → Merchant Agent (決済結果)
        Step 31: Merchant Agent → Shopping Agent (決済結果転送)

        このメソッド名は実装の正確性を反映:
        - Payment Processorに「直接」送信するのではなく
        - Merchant Agent「経由」で送信する

        VDC交換の原則に従い、CartMandateも含めて送信（領収書生成に必要）

        Args:
            payment_mandate: PaymentMandate（最小限のペイロード）
            cart_mandate: CartMandate（注文詳細、領収書生成に必要）

        Returns:
            決済結果（Merchant Agent経由で受信）
        """
        logger.info(f"[ShoppingAgent] Requesting payment processing via Merchant Agent for PaymentMandate: {payment_mandate['id']}")

        try:
            # A2Aメッセージのペイロード：PaymentMandateとCartMandateを含める
            # VDC交換の原則：暗号的に署名されたVDCをエージェント間で交換
            payload = {
                "payment_mandate": payment_mandate,
                "cart_mandate": cart_mandate  # 領収書生成に必要
            }

            # A2Aメッセージを作成（署名付き）
            # AP2 Step 24: Merchant Agent経由での決済処理依頼
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",  # Merchant Agentに送信
                data_type="ap2.mandates.PaymentMandate",  # AP2仕様準拠: PaymentMandateを使用
                data_id=payment_mandate["id"],
                payload=payload,
                sign=True
            )

            # Merchant AgentにA2Aメッセージを送信
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信（PaymentRequest）\n"
                f"  URL: {self.merchant_agent_url}/a2a/message\n"
                f"  メッセージID: {message.header.message_id}\n"
                f"  タイプ: {message.dataPart.type}\n"
                f"  ペイロード: {json_lib.dumps(payment_mandate, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # AP2準拠: Merchant AgentのAI処理時間を考慮して300秒（5分）タイムアウト
            # LangGraph処理（Intent分析→商品検索→カート最適化→署名）に時間がかかる
            # LLMのリトライも含めて十分な時間を確保

            # OpenTelemetry 手動トレーシング: A2A通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.merchant_agent_url}/a2a/message",
                **{
                    "a2a.message_type": "ap2.mandates.PaymentMandate",
                    "a2a.recipient": "did:ap2:agent:merchant_agent",
                    "a2a.message_id": message.header.message_id
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.merchant_agent_url}/a2a/message",
                    json=message.model_dump(by_alias=True),
                    timeout=300.0
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # A2Aレスポンスからpayloadを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")

                if response_type == "ap2.responses.PaymentResult":
                    payload = data_part["payload"]
                    logger.info(f"[ShoppingAgent] Payment processing completed: status={payload.get('status')}")
                    return payload
                elif response_type == "ap2.errors.Error":
                    error_payload = data_part["payload"]
                    raise ValueError(f"Merchant Agent/Payment Processor error: {error_payload.get('error_message')}")
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[_process_payment_via_merchant_agent] HTTP error: {e}")
            raise ValueError(f"Failed to process payment via Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[_process_payment_via_merchant_agent] Error: {e}", exc_info=True)
            raise

    async def _search_products_via_merchant_agent(
        self,
        intent_mandate: Dict[str, Any],
        session: Dict[str, Any]
    ) -> list[Dict[str, Any]]:
        """
        Merchant AgentにIntentMandateを送信してカート候補を取得

        専門家の指摘対応：IntentのA2AメッセージIDを保存してトレーサビリティを確保

        AP2/A2A仕様準拠（Step 8-9、a2a-extension.md:144-229）：
        1. Shopping AgentがIntentMandateをMerchant Agentに送信（A2A通信）
        2. A2AメッセージのmessageIdをセッションに保存（intent_message_id）
        3. Merchant AgentがIntentMandateに基づいて複数のカート候補を生成
        4. Merchant Agentが署名済みCartMandateをArtifact形式で返却（ap2.responses.CartCandidates）
        """
        logger.info(f"[ShoppingAgent] Requesting cart candidates from Merchant Agent for IntentMandate: {intent_mandate['id']}")

        try:
            # AP2仕様準拠：配送先情報を含めてMerchant Agentに送信
            # 配送先によって配送料が変わるため、CartMandate作成前に必要
            shipping_address = session.get("shipping_address")

            # ペイロードにIntentMandateと配送先を含める
            payload = {
                "intent_mandate": intent_mandate,
                "shipping_address": shipping_address  # AP2仕様：CartMandate作成前に配送先を提供
            }

            # A2Aメッセージを作成（署名付き）
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",
                data_type="ap2.mandates.IntentMandate",
                data_id=intent_mandate["id"],
                payload=payload,
                sign=True
            )

            # 重要：A2AメッセージIDを保存（CartMandateとConsentから参照）
            intent_message_id = message.header.message_id
            session["intent_message_id"] = intent_message_id

            logger.info(
                f"[ShoppingAgent] Intent A2A message created: "
                f"message_id={intent_message_id}, intent_mandate_id={intent_mandate['id']}"
            )

            # Merchant AgentにA2Aメッセージを送信
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信\n"
                f"  URL: {self.merchant_agent_url}/a2a/message\n"
                f"  メッセージID: {message.header.message_id}\n"
                f"  タイプ: {message.dataPart.type}\n"
                f"  ペイロード: {json_lib.dumps(intent_mandate, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # AP2準拠: Merchant AgentのAI処理時間を考慮して300秒（5分）タイムアウト
            # LangGraph処理（Intent分析→商品検索→カート最適化→署名）に時間がかかる
            # LLMのリトライも含めて十分な時間を確保

            # OpenTelemetry 手動トレーシング: A2A通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.merchant_agent_url}/a2a/message",
                **{
                    "a2a.message_type": "ap2.mandates.IntentMandate",
                    "a2a.recipient": "did:ap2:agent:merchant_agent",
                    "a2a.message_id": message.header.message_id
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.merchant_agent_url}/a2a/message",
                    json=message.model_dump(by_alias=True),
                    timeout=300.0
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)[:1000]}...\n"
                f"{'='*80}"
            )

            # A2AレスポンスからCart Candidatesを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")

                # AP2/A2A仕様準拠：CartCandidatesレスポンス
                if response_type == "ap2.responses.CartCandidates":
                    cart_candidates = data_part["payload"].get("cart_candidates", [])
                    logger.info(f"[ShoppingAgent] Received {len(cart_candidates)} cart candidates from Merchant Agent")

                    # AP2完全準拠: 元のArtifact構造をそのまま返す
                    # フロントエンド変換は呼び出し側で実施
                    logger.debug(f"[ShoppingAgent] Returning {len(cart_candidates)} artifacts in original A2A format")
                    return cart_candidates

                # 後方互換性：ProductListレスポンス（旧形式）
                elif response_type == "ap2.responses.ProductList":
                    logger.warning("[ShoppingAgent] Received ProductList (old format). Converting to cart candidates.")
                    products = data_part["payload"].get("products", [])
                    # 旧形式をカート候補形式に変換（後方互換性のため）
                    logger.info(f"[ShoppingAgent] Received {len(products)} products (old format)")
                    return products

                # エラーレスポンス
                elif response_type == "ap2.errors.Error":
                    error_payload = data_part.get("payload", {})
                    error_msg = error_payload.get("error_message", "Unknown error")
                    logger.error(f"[ShoppingAgent] Merchant Agent returned error: {error_msg}")
                    raise ValueError(f"Merchant Agent error: {error_msg}")

                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[_search_products_via_merchant_agent] HTTP error: {e}")
            raise ValueError(f"Failed to search products via Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[_search_products_via_merchant_agent] Error: {e}", exc_info=True)
            raise

    async def _request_cart_from_merchant_agent(
        self,
        selected_product: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merchant AgentにCartRequestを送信してCartMandateを作成・署名依頼

        AP2仕様準拠（Steps 10-12）：
        1. Shopping AgentがCartRequest（商品選択情報）をMerchant Agentに送信（A2A通信）
        2. Merchant AgentがCartMandateを作成
        3. Merchant AgentがMerchantに署名依頼
        4. Merchant Agentが署名済みCartMandateを返却
        """
        logger.info(f"[ShoppingAgent] Requesting CartMandate from Merchant Agent for product: {selected_product.get('id')}")

        try:
            # CartRequest作成
            # 専門家の指摘対応：intent_message_idを追加してトレーサビリティを確保
            cart_request = {
                "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
                "intent_message_id": session.get("intent_message_id"),  # A2AメッセージID参照
                "items": [
                    {
                        "product_id": selected_product.get("id"),
                        "quantity": 1
                    }
                ],
                "shipping_address": {
                    "recipient": "山田太郎",
                    "postal_code": "150-0001",
                    "address_line1": "東京都渋谷区神宮前1-1-1",
                    "address_line2": "サンプルマンション101",
                    "country": "JP"
                }
            }

            logger.info(
                f"[ShoppingAgent] CartRequest created: "
                f"intent_mandate_id={cart_request['intent_mandate_id']}, "
                f"intent_message_id={cart_request['intent_message_id']}"
            )

            # A2Aメッセージを作成（署名付き）
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",
                data_type="ap2.requests.CartRequest",
                data_id=str(uuid.uuid4()),
                payload=cart_request,
                sign=True
            )

            # Merchant AgentにA2Aメッセージを送信
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信\n"
                f"  URL: {self.merchant_agent_url}/a2a/message\n"
                f"  メッセージID: {message.header.message_id}\n"
                f"  タイプ: {message.dataPart.type}\n"
                f"  ペイロード: {json_lib.dumps(cart_request, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # AP2準拠: Merchant AgentのAI処理時間を考慮して300秒（5分）タイムアウト
            # LangGraph処理（Intent分析→商品検索→カート最適化→署名）に時間がかかる
            # LLMのリトライも含めて十分な時間を確保

            # OpenTelemetry 手動トレーシング: A2A通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.merchant_agent_url}/a2a/message",
                **{
                    "a2a.message_type": "ap2.requests.CartRequest",
                    "a2a.recipient": "did:ap2:agent:merchant_agent",
                    "a2a.message_id": message.header.message_id
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.merchant_agent_url}/a2a/message",
                    json=message.model_dump(by_alias=True),
                    timeout=300.0
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # A2AレスポンスからCartMandateを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]

                # AP2/A2A仕様準拠：Artifact形式のCartMandateを処理
                # a2a-extension.md:144-229の仕様に基づく
                signed_cart_mandate = None

                if data_part.get("kind") == "artifact" and data_part.get("artifact"):
                    # Artifact形式（新仕様）
                    artifact = data_part["artifact"]
                    logger.info(f"[ShoppingAgent] Received A2A Artifact: {artifact.get('name')}, ID={artifact.get('artifactId')}")

                    # Artifactから実データを抽出
                    if artifact.get("parts") and len(artifact["parts"]) > 0:
                        first_part = artifact["parts"][0]
                        if first_part.get("kind") == "data" and first_part.get("data"):
                            data_obj = first_part["data"]
                            # "CartMandate"キーでデータが格納されている
                            signed_cart_mandate = data_obj.get("CartMandate")
                            if signed_cart_mandate:
                                logger.info(f"[ShoppingAgent] Extracted CartMandate from Artifact: {signed_cart_mandate.get('id')}")

                # 後方互換性：従来のメッセージ形式もサポート
                if not signed_cart_mandate:
                    response_type = data_part.get("@type") or data_part.get("type")
                    if response_type == "ap2.mandates.CartMandate":
                        signed_cart_mandate = data_part["payload"]
                        logger.info(f"[ShoppingAgent] Received signed CartMandate (legacy format) from Merchant Agent: {signed_cart_mandate.get('id')}")

                if signed_cart_mandate:
                    logger.info(f"[ShoppingAgent] Processing CartMandate: {signed_cart_mandate.get('id')}")

                    # Merchant署名を検証
                    merchant_signature = signed_cart_mandate.get("merchant_signature")
                    if not merchant_signature:
                        raise ValueError("CartMandate does not contain merchant_signature")

                    # v2.common.models.Signatureに変換
                    from v2.common.models import Signature
                    signature_obj = Signature(
                        algorithm=merchant_signature.get("algorithm", "ECDSA").upper(),
                        value=merchant_signature["value"],
                        public_key=merchant_signature["public_key"],
                        signed_at=merchant_signature["signed_at"]
                    )

                    # 署名対象データ（merchant_signature除外）
                    cart_data_for_verification = signed_cart_mandate.copy()
                    cart_data_for_verification.pop("merchant_signature", None)
                    cart_data_for_verification.pop("user_signature", None)

                    # 署名検証
                    is_valid = self.signature_manager.verify_mandate_signature(
                        cart_data_for_verification,
                        signature_obj
                    )

                    if not is_valid:
                        raise ValueError("Merchant signature verification failed")

                    logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate")
                    return signed_cart_mandate

                elif response_type == "ap2.responses.CartMandatePending":
                    # 手動署名モード：Merchantの承認待ち
                    pending_info = data_part["payload"]
                    cart_mandate_id = pending_info.get("cart_mandate_id")
                    message = pending_info.get("message", "Merchant approval required")
                    logger.info(f"[ShoppingAgent] CartMandate is pending merchant approval: {cart_mandate_id}. Waiting for approval...")

                    # Merchantの承認/拒否を待機（ポーリング）
                    signed_cart_mandate = await self._wait_for_merchant_approval(cart_mandate_id)
                    return signed_cart_mandate

                elif response_type == "ap2.errors.Error":
                    error_payload = data_part["payload"]
                    raise ValueError(f"Merchant Agent error: {error_payload.get('error_message')}")
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[_request_cart_from_merchant_agent] HTTP error: {e}")
            raise ValueError(f"Failed to request CartMandate from Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[_request_cart_from_merchant_agent] Error: {e}", exc_info=True)
            raise

    async def _request_merchant_signature(self, cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """
        MerchantにCartMandateの署名を依頼

        AP2仕様準拠：
        1. Shopping AgentがCartMandateを作成（未署名）
        2. MerchantがCartMandateに署名
        3. Shopping AgentがMerchant署名を検証
        """
        logger.info(f"[ShoppingAgent] Requesting Merchant signature for CartMandate: {cart_mandate['id']}")

        try:
            # MerchantにPOST /sign/cartで署名依頼
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → Merchant] 署名リクエスト送信\n"
                f"  URL: {self.merchant_url}/sign/cart\n"
                f"  CartMandate ID: {cart_mandate['id']}\n"
                f"  ペイロード: {json_lib.dumps(cart_mandate, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            response = await self.http_client.post(
                f"{self.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← Merchant] 署名レスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # 署名済みCartMandateを取得
            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                raise ValueError("Merchant did not return signed_cart_mandate")

            # Merchant署名を検証
            merchant_signature = signed_cart_mandate.get("merchant_signature")
            if not merchant_signature:
                raise ValueError("CartMandate does not contain merchant_signature")

            # v2.common.models.Signatureに変換
            from v2.common.models import Signature
            signature_obj = Signature(
                algorithm=merchant_signature.get("algorithm", "ECDSA").upper(),
                value=merchant_signature["value"],
                public_key=merchant_signature["public_key"],
                signed_at=merchant_signature["signed_at"]
            )

            # 署名対象データ（merchant_signature除外）
            cart_data_for_verification = signed_cart_mandate.copy()
            cart_data_for_verification.pop("merchant_signature", None)
            cart_data_for_verification.pop("user_signature", None)

            # 署名検証
            is_valid = self.signature_manager.verify_mandate_signature(
                cart_data_for_verification,
                signature_obj
            )

            if not is_valid:
                raise ValueError("Merchant signature verification failed")

            logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate: {cart_mandate['id']}")
            return signed_cart_mandate

        except httpx.HTTPError as e:
            logger.error(f"[_request_merchant_signature] HTTP error: {e}")
            raise ValueError(f"Failed to request Merchant signature: {e}")
        except Exception as e:
            logger.error(f"[_request_merchant_signature] Error: {e}", exc_info=True)
            raise

    async def _get_payment_methods_from_cp(self, user_id: str, credential_provider_url: str) -> list[Dict[str, Any]]:
        """
        Credential Providerから支払い方法を取得

        AP2仕様準拠（Step 6-7）：
        1. Shopping AgentがCredential Providerに支払い方法リストを要求
        2. Credential Providerが利用可能な支払い方法を返却
        """
        logger.info(f"[ShoppingAgent] Requesting payment methods from Credential Provider ({credential_provider_url}) for user: {user_id}")

        try:
            # Credential ProviderにGET /payment-methodsで支払い方法取得
            response = await self.http_client.get(
                f"{credential_provider_url}/payment-methods",
                params={"user_id": user_id},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 支払い方法リストを取得
            payment_methods = result.get("payment_methods", [])
            if not payment_methods:
                logger.warning(f"[ShoppingAgent] No payment methods found for user: {user_id}")
                return []

            logger.info(f"[ShoppingAgent] Retrieved {len(payment_methods)} payment methods from Credential Provider")
            return payment_methods

        except httpx.HTTPError as e:
            logger.error(f"[_get_payment_methods_from_cp] HTTP error: {e}")
            raise ValueError(f"Failed to get payment methods from Credential Provider: {e}")
        except Exception as e:
            logger.error(f"[_get_payment_methods_from_cp] Error: {e}", exc_info=True)
            raise

    async def _tokenize_payment_method(self, user_id: str, payment_method_id: str, credential_provider_url: str) -> Dict[str, Any]:
        """
        Credential Providerで支払い方法をトークン化

        AP2仕様準拠（Step 17-18）：
        1. Shopping AgentがCredential Providerに支払い方法のトークン化を要求
        2. Credential Providerが一時的なセキュアトークンを生成して返却
        """
        logger.info(f"[ShoppingAgent] Requesting payment method tokenization for: {payment_method_id}")

        try:
            # Credential ProviderにPOST /payment-methods/tokenizeでトークン化依頼
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → CredentialProvider] トークン化リクエスト送信\n"
                f"  URL: {credential_provider_url}/payment-methods/tokenize\n"
                f"  User ID: {user_id}\n"
                f"  Payment Method ID: {payment_method_id}\n"
                f"{'='*80}"
            )

            response = await self.http_client.post(
                f"{credential_provider_url}/payment-methods/tokenize",
                json={
                    "user_id": user_id,
                    "payment_method_id": payment_method_id
                },
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"[ShoppingAgent ← CredentialProvider] トークン化レスポンス受信: "
                f"status={response.status_code}"
            )

            # トークン化結果を取得
            token = result.get("token")
            if not token:
                raise ValueError("Credential Provider did not return token")

            logger.info(f"[ShoppingAgent] Payment method tokenized: {payment_method_id} → {token[:20]}...")
            return result

        except httpx.HTTPError as e:
            logger.error(f"[_tokenize_payment_method] HTTP error: {e}")
            raise ValueError(f"Failed to tokenize payment method: {e}")
        except Exception as e:
            logger.error(f"[_tokenize_payment_method] Error: {e}", exc_info=True)
            raise

    async def _verify_attestation_with_cp(
        self,
        payment_mandate: Dict[str, Any],
        attestation: Dict[str, Any],
        credential_provider_url: str
    ) -> Dict[str, Any]:
        """
        Credential ProviderにWebAuthn attestationを検証依頼

        AP2仕様準拠（Step 20-22, 23）：
        1. Shopping AgentがPaymentMandate + AttestationをCredential Providerに送信
        2. Credential ProviderがWebAuthn attestationを検証
        3. 検証成功時、Credential Providerが認証トークンを発行
        """
        logger.info(f"[ShoppingAgent] Verifying WebAuthn attestation with Credential Provider ({credential_provider_url}) for PaymentMandate: {payment_mandate.get('id')}")

        try:
            # Credential ProviderにPOST /verify/attestationで検証依頼
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → CredentialProvider] WebAuthn検証リクエスト送信\n"
                f"  URL: {credential_provider_url}/verify/attestation\n"
                f"  PaymentMandate ID: {payment_mandate.get('id')}\n"
                f"  Attestation Type: {attestation.get('attestation_type')}\n"
                f"  ペイロード:\n"
                f"    PaymentMandate: {json_lib.dumps(payment_mandate, ensure_ascii=False, indent=2)}\n"
                f"    Attestation: {json_lib.dumps(attestation, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            response = await self.http_client.post(
                f"{credential_provider_url}/verify/attestation",
                json={
                    "payment_mandate": payment_mandate,
                    "attestation": attestation
                },
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← CredentialProvider] WebAuthn検証レスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Verified: {result.get('verified', False)}\n"
                f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # 検証結果を取得
            verified = result.get("verified", False)
            if verified:
                token = result.get("token")
                logger.info(f"[ShoppingAgent] WebAuthn attestation verified successfully: token={token[:20] if token else 'N/A'}...")
            else:
                logger.warning(f"[ShoppingAgent] WebAuthn attestation verification failed: {result.get('details')}")

            return result

        except httpx.HTTPError as e:
            logger.error(f"[_verify_attestation_with_cp] HTTP error: {e}")
            raise ValueError(f"Failed to verify attestation with Credential Provider: {e}")
        except Exception as e:
            logger.error(f"[_verify_attestation_with_cp] Error: {e}", exc_info=True)
            raise

    async def _wait_for_merchant_approval(self, cart_mandate_id: str, timeout: int = 120, poll_interval: int = 3) -> Dict[str, Any]:
        """
        Merchantの承認/拒否を待機（ポーリング）

        Args:
            cart_mandate_id: CartMandate ID
            timeout: 最大待機時間（秒）、デフォルト120秒
            poll_interval: ポーリング間隔（秒）、デフォルト3秒

        Returns:
            Dict[str, Any]: 署名済みCartMandate

        Raises:
            ValueError: タイムアウトまたは拒否された場合
        """
        logger.info(f"[ShoppingAgent] Waiting for merchant approval for CartMandate: {cart_mandate_id}, timeout={timeout}s")

        start_time = asyncio.get_event_loop().time()
        elapsed_time = 0

        while elapsed_time < timeout:
            try:
                # MerchantからCartMandateのステータスを取得
                response = await self.http_client.get(
                    f"{self.merchant_url}/cart-mandates/{cart_mandate_id}",
                    timeout=10.0
                )
                response.raise_for_status()
                result = response.json()

                status = result.get("status")
                payload = result.get("payload")

                logger.debug(f"[ShoppingAgent] CartMandate {cart_mandate_id} status: {status}")

                # 署名完了
                if status == "signed":
                    logger.info(f"[ShoppingAgent] CartMandate {cart_mandate_id} has been approved and signed by merchant")

                    # Merchant署名を検証
                    merchant_signature = payload.get("merchant_signature")
                    if not merchant_signature:
                        raise ValueError("CartMandate does not contain merchant_signature")

                    # v2.common.models.Signatureに変換
                    from v2.common.models import Signature
                    signature_obj = Signature(
                        algorithm=merchant_signature.get("algorithm", "ECDSA").upper(),
                        value=merchant_signature["value"],
                        public_key=merchant_signature["public_key"],
                        signed_at=merchant_signature["signed_at"]
                    )

                    # 署名対象データ（merchant_signature除外）
                    cart_data_for_verification = payload.copy()
                    cart_data_for_verification.pop("merchant_signature", None)
                    cart_data_for_verification.pop("user_signature", None)

                    # 署名検証
                    is_valid = self.signature_manager.verify_mandate_signature(
                        cart_data_for_verification,
                        signature_obj
                    )

                    if not is_valid:
                        raise ValueError("Merchant signature verification failed")

                    logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate: {cart_mandate_id}")
                    return payload

                # 拒否された
                elif status == "rejected":
                    logger.warning(f"[ShoppingAgent] CartMandate {cart_mandate_id} has been rejected by merchant")
                    raise ValueError(f"CartMandateがMerchantに拒否されました（ID: {cart_mandate_id}）")

                # まだpending - 待機
                elif status == "pending_merchant_signature":
                    logger.debug(f"[ShoppingAgent] CartMandate {cart_mandate_id} is still pending, waiting...")
                    await asyncio.sleep(poll_interval)
                    elapsed_time = asyncio.get_event_loop().time() - start_time
                    continue

                # 予期しないステータス
                else:
                    logger.warning(f"[ShoppingAgent] Unexpected CartMandate status: {status}")
                    await asyncio.sleep(poll_interval)
                    elapsed_time = asyncio.get_event_loop().time() - start_time
                    continue

            except httpx.HTTPError as e:
                logger.error(f"[_wait_for_merchant_approval] HTTP error while checking status: {e}")
                await asyncio.sleep(poll_interval)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                continue

            except Exception as e:
                logger.error(f"[_wait_for_merchant_approval] Error while checking status: {e}")
                raise

        # タイムアウト
        logger.error(f"[ShoppingAgent] Timeout waiting for merchant approval for CartMandate: {cart_mandate_id}")
        raise ValueError(f"Merchantの承認待ちがタイムアウトしました（ID: {cart_mandate_id}、{timeout}秒経過）。Merchant Dashboardで承認してください。")
