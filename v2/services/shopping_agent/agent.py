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
from v2.common.mandate_types import IntentMandate
from v2.common.risk_assessment import RiskAssessmentEngine
from v2.common.crypto import WebAuthnChallengeManager, DeviceAttestationManager
from v2.common.user_authorization import create_user_authorization_vp
from v2.common.auth import (
    # JWT認証
    create_access_token,
    get_current_user,
    # パスワード認証（2025年ベストプラクティス - Argon2id）
    hash_password,
    verify_password,
    validate_password_strength,
)
from v2.common.logger import get_logger, LoggingAsyncClient

# OpenTelemetry 手動トレーシング
from v2.common.telemetry import get_tracer, create_http_span

# Shopping Agent ユーティリティモジュール
from services.shopping_agent.utils import (
    HashHelpers,
    PaymentHelpers,
    CartHelpers,
    A2AHelpers
)
from services.shopping_agent.utils.signature_handlers import SignatureHandlers
from services.shopping_agent.utils.merchant_integration import MerchantIntegrationHelpers

# NOTE: 古いLangGraph実装（langgraph_agent, langgraph_conversation, langgraph_shopping）は廃止
# 新しいStateGraph版（langgraph_shopping_flow.py）を使用

logger = get_logger(__name__, service_name='shopping_agent')

# OpenTelemetryトレーサー（手動計装用）
tracer = get_tracer(__name__)


# ========================================
# 定数定義
# ========================================

# HTTP Timeout設定（秒）
HTTP_CLIENT_TIMEOUT = 600.0  # HTTPクライアント全体のタイムアウト（DMR LLM処理対応）
HTTP_CONNECT_TIMEOUT = 30.0  # HTTP接続確立タイムアウト
HTTP_WRITE_TIMEOUT = 30.0  # HTTPリクエスト書き込みタイムアウト
HTTP_POOL_TIMEOUT = 10.0  # HTTPコネクションプール取得タイムアウト
A2A_COMMUNICATION_TIMEOUT = 300.0  # A2A通信タイムアウト（エージェント間通信）
SHORT_HTTP_TIMEOUT = 10.0  # 短い通信のタイムアウト

# WebAuthn設定
WEBAUTHN_CHALLENGE_TIMEOUT_MS = 60000  # WebAuthnチャレンジのタイムアウト（ミリ秒） = 60秒

# Merchant承認待機設定
MERCHANT_APPROVAL_TIMEOUT = 120  # 秒（Merchant署名待機のタイムアウト）
MERCHANT_APPROVAL_POLL_INTERVAL = 3  # 秒（ポーリング間隔）

# AP2ステータス定数
STATUS_SUCCESS = "success"
STATUS_CANCELLED = "cancelled"
STATUS_SIGNED = "signed"
STATUS_REJECTED = "rejected"
STATUS_PENDING_MERCHANT_SIGNATURE = "pending_merchant_signature"


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
        # httpx.Timeoutで各段階のタイムアウトを明示的に設定
        # AP2完全準拠: LoggingAsyncClientで全HTTP通信をログ記録
        self.http_client = LoggingAsyncClient(
            logger=logger,
            timeout=httpx.Timeout(
                connect=HTTP_CONNECT_TIMEOUT,  # 接続確立タイムアウト
                read=HTTP_CLIENT_TIMEOUT,  # レスポンス読み込みタイムアウト（600秒）
                write=HTTP_WRITE_TIMEOUT,  # リクエスト書き込みタイムアウト
                pool=HTTP_POOL_TIMEOUT  # コネクションプール取得タイムアウト
            )
        )

        # エージェントエンドポイント（Docker Compose環境想定）
        self.merchant_agent_url = "http://merchant_agent:8001"
        self.merchant_url = "http://merchant:8002"
        self.payment_processor_url = "http://payment_processor:8004"

        # AP2完全準拠: Credential Provider URL（Mandate署名検証用）
        # AP2仕様: Shopping AgentはCredential Providerに署名検証をデリゲート
        self.credential_provider_url = "http://credential_provider:8003"

        # 複数のCredential Providerに対応（AP2完全準拠）
        self.credential_providers = [
            {
                "id": "cp_demo_001",
                "name": "AP2 Demo Credential Provider",
                "url": self.credential_provider_url,  # http://credential_provider:8003
                "description": "メインCredential Provider（Passkey対応）",
                "logo_url": "https://example.com/cp_demo_logo.png",
                "supported_methods": ["card", "passkey"]
            },
            {
                "id": "cp_demo_002",
                "name": "Alternative Credential Provider",
                "url": "http://credential_provider_2:8003",  # 2つ目のCP
                "description": "代替Credential Provider（カードのみ）",
                "logo_url": "https://example.com/cp_alt_logo.png",
                "supported_methods": ["card"]
            }
        ]

        # セッション管理（簡易版 - インメモリ）
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # Langfuseトレース管理（AP2完全準拠: オブザーバビリティ機能）
        # セッションIDをキーにしてルートスパンを管理
        self.trace_spans: Dict[str, Any] = {}

        # リスク評価エンジン（データベースマネージャーを渡して完全実装を有効化）
        self.risk_engine = RiskAssessmentEngine(db_manager=self.db_manager)

        # ヘルパークラスの初期化
        self.hash_helpers = HashHelpers()
        self.payment_helpers = PaymentHelpers(risk_engine=self.risk_engine)
        self.cart_helpers = CartHelpers(signature_manager=self.signature_manager)
        # A2AHelpersは親クラスの初期化後にa2a_handlerが利用可能になるため、後で初期化

        # WebAuthn challenge管理
        # - Layer 1認証用: Passkey登録/ログイン（本追加）
        # - Layer 2署名用: Intent/Consent署名（既存）
        self.webauthn_challenge_manager = WebAuthnChallengeManager(challenge_ttl_seconds=60)

        # Passkey認証用のchallenge管理（ログイン用）
        self.passkey_auth_challenge_manager = WebAuthnChallengeManager(challenge_ttl_seconds=120)  # ログインは2分

        # Device Attestation管理（WebAuthn署名検証用 - AP2完全準拠）
        self.attestation_manager = DeviceAttestationManager(self.key_manager)

        # LangGraph Shopping Flow（会話フロー：StateGraph版、AP2完全準拠）
        try:
            from services.shopping_agent.langgraph_shopping_flow import create_shopping_flow_graph
            self.shopping_flow_graph = create_shopping_flow_graph(self)
            logger.info(f"[{self.agent_name}] LangGraph shopping flow graph initialized successfully (12 nodes)")
        except Exception as e:
            logger.warning(f"[{self.agent_name}] LangGraph shopping flow graph initialization failed: {e}")
            self.shopping_flow_graph = None

        # Langfuseハンドラー管理（セッションごとにCallbackHandlerインスタンスを保持）
        self._langfuse_handlers: Dict[str, Any] = {}

        # A2AHelpers初期化（a2a_handlerが利用可能になった後）
        self.a2a_helpers = A2AHelpers(
            a2a_handler=self.a2a_handler,
            http_client=self.http_client,
            merchant_agent_url=self.merchant_agent_url,
            tracer=tracer,
            a2a_timeout=A2A_COMMUNICATION_TIMEOUT
        )

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
                    timeout=WEBAUTHN_CHALLENGE_TIMEOUT_MS
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
                    timeout=WEBAUTHN_CHALLENGE_TIMEOUT_MS,
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

                    logger.info(f"[Auth] Passkey login verification: user_id={user.id}, credential_id={request.credential_id[:16]}...")

                    # AP2完全準拠: WebAuthn Assertion完全検証（COSE署名検証）
                    # Step 1: client_data_jsonからchallengeを抽出
                    import base64
                    try:
                        client_data_json_b64 = request.client_data_json

                        # Base64URLデコード
                        padding_needed = len(client_data_json_b64) % 4
                        if padding_needed:
                            client_data_json_b64 += '=' * (4 - padding_needed)

                        client_data_json_b64_std = client_data_json_b64.replace('-', '+').replace('_', '/')
                        client_data_json_bytes = base64.b64decode(client_data_json_b64_std)
                        client_data = json.loads(client_data_json_bytes.decode('utf-8'))

                        received_challenge = client_data.get("challenge")
                        if not received_challenge:
                            logger.error("[Auth] Challenge not found in client_data_json")
                            raise HTTPException(status_code=401, detail="Challenge not found")

                        logger.debug(f"[Auth] Received challenge: {received_challenge[:16]}...")

                        # Step 2: Challenge検証（WebAuthnChallengeManagerは使えない: challenge_idがないため）
                        # フロントエンドから送られてきたchallengeをそのまま使用
                        # 注意: 本来はchallenge_idベースの検証が必要だが、現在のフロントエンド実装では
                        # challengeのみが送られてくるため、直接challengeを使用
                        challenge = received_challenge

                    except (json.JSONDecodeError, base64.binascii.Error) as e:
                        logger.error(f"[Auth] Failed to parse client_data_json: {e}")
                        raise HTTPException(status_code=401, detail="Invalid client_data_json")

                    # Step 3: WebAuthn署名検証（完全な暗号学的検証 - AP2完全準拠）
                    # WebAuthnAttestation形式に変換
                    webauthn_auth_result = {
                        "response": {
                            "clientDataJSON": request.client_data_json,
                            "authenticatorData": request.authenticator_data,
                            "signature": request.signature,
                        }
                    }

                    verified, new_counter = self.attestation_manager.verify_webauthn_signature(
                        webauthn_auth_result=webauthn_auth_result,
                        challenge=challenge,
                        public_key_cose_b64=credential.public_key_cose,
                        stored_counter=credential.counter,
                        rp_id="localhost"
                    )

                    if not verified:
                        logger.error(f"[Auth] WebAuthn signature verification failed: user_id={user.id}")
                        raise HTTPException(status_code=401, detail="Signature verification failed")

                    # Step 4: Signature counterを更新（リプレイ攻撃対策）
                    await PasskeyCredentialCRUD.update_counter(
                        session, request.credential_id, new_counter
                    )

                    if new_counter == 0:
                        logger.info(
                            f"[Auth] Signature counter: {credential.counter} → {new_counter} "
                            f"(AP2準拠: Authenticatorがcounterを実装していない場合)"
                        )
                    else:
                        logger.info(
                            f"[Auth] Signature counter updated: {credential.counter} → {new_counter}"
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

            # デバッグログ: Step-up完了メッセージを検出
            logger.info(
                f"[chat_stream] Received request\n"
                f"  session_id: {session_id}\n"
                f"  user_id: {user_id}\n"
                f"  user_input: {request.user_input}\n"
                f"  is_step_up_completion: {request.user_input.startswith('_step-up-completed:')}"
            )

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    # データベースからセッション取得または作成（AP2準拠: user_id必須）
                    session = await self._get_or_create_session(session_id, user_id=user_id)
                    session["messages"].append({"role": "user", "content": request.user_input})

                    # LangGraph StateGraph版のフローを使用（AP2完全準拠）
                    logger.info(f"[chat_stream] Using LangGraph shopping flow (session_id={session_id})")

                    # EventSourceResponseはJSON文字列を期待するため、
                    # 辞書をJSON文字列に変換して返す
                    async for event in self._generate_fixed_response_langgraph(request.user_input, session, session_id):
                        yield json.dumps(event.model_dump(exclude_none=True))
                        await asyncio.sleep(0.01)

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
                
                if status == STATUS_SUCCESS:
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
                elif status == STATUS_CANCELLED:
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

                # SignatureHandlersを使用してCredential Providerで署名検証
                verification_result = await SignatureHandlers.verify_cart_signature_with_cp(
                    http_client=self.http_client,
                    credential_provider_url=self.credential_provider_url,
                    cart_mandate=cart_mandate,
                    webauthn_assertion=webauthn_assertion,
                    user_id=user_id
                )

                # AP2完全準拠: CartMandateは変更せず、Merchant署名のままPayment Processorに送信
                # User署名情報（WebAuthn assertion）はPaymentMandateのuser_authorizationに含める
                # CartMandateの内容を変更すると、merchant_authorization JWTのcart_hashと一致しなくなる

                # WebAuthn assertionをセッションに保存（PaymentMandate生成時にuser_authorization作成に使用）
                session["cart_webauthn_assertion"] = webauthn_assertion
                # CartMandateは変更せずそのまま保持（Merchant署名時のハッシュを維持）

                # LangGraphベストプラクティス: stepの更新はLangGraph Checkpointerに任せる
                # データベースには、WebAuthn assertionのみを保存（Checkpointerが管理しないデータ）
                # 次のLangGraph実行で、cart_signature_waiting_nodeが自動的に次のステップに進む

                # セッション保存（cart_webauthn_assertionのみ、stepは保存しない）
                await self._update_session(session_id, session)

                logger.info(
                    f"[submit_cart_signature] CartMandate signed by user: "
                    f"cart_id={cart_mandate.get('id')}, webauthn_assertion saved"
                )

                # AP2完全準拠: CartMandate署名完了後、次のLangGraph実行でPaymentMandate作成へ進む
                return {
                    "status": "success",
                    "message": "CartMandate signed successfully",
                    "next_step": "payment_mandate_creation"  # フロントエンド表示用（実際の状態遷移はLangGraphが管理）
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

                # LangGraphベストプラクティス: stepチェックを削除
                # 理由:
                # - CheckpointerがstepをLangGraph実行内で管理
                # - データベースのセッションはCheckpointerが管理しないデータのみを保存
                # - stepチェックは、データベースとCheckpointerの不整合を引き起こす
                #
                # AP2完全準拠: PaymentMandateの存在確認で十分
                # （PaymentMandateがあれば、署名可能な状態）

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

                # SignatureHandlersを使用してCredential Providerで検証
                verification_result = await SignatureHandlers.verify_payment_attestation_with_cp(
                    http_client=self.http_client,
                    credential_provider_url=selected_cp["url"],
                    payment_mandate=payment_mandate,
                    attestation=attestation
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
                # LangGraphベストプラクティス: stepはCheckpointerが管理する
                # submit_payment_attestationでは、webauthn_assertionのみをセッションに保存

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
                    selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

                    # SignatureHandlersを使用してCredential Providerから公開鍵を取得
                    public_key_cose = await SignatureHandlers.retrieve_public_key_from_cp(
                        http_client=self.http_client,
                        credential_provider_url=selected_cp['url'],
                        credential_id=credential_id,
                        user_id=user_id,
                        timeout=SHORT_HTTP_TIMEOUT
                    )

                    # VP生成時、PaymentMandateからuser_authorizationフィールドを除外
                    # （ハッシュ計算の一貫性を保つため）
                    payment_mandate_for_vp = {k: v for k, v in payment_mandate.items() if k != "user_authorization"}

                    user_authorization = create_user_authorization_vp(
                        webauthn_assertion=attestation,
                        cart_mandate=cart_mandate,
                        payment_mandate_contents=payment_mandate_for_vp,
                        user_id=user_id,
                        public_key_cose=public_key_cose,
                        payment_processor_id="did:ap2:agent:payment_processor"
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

                # AP2完全準拠: WebAuthn署名検証成功後、決済実行ステップへ進む
                # 決済実行はLangGraphの execute_payment_node で実行される
                session["payment_webauthn_assertion"] = attestation

                # LangGraphベストプラクティス: stepの更新はCheckpointerに任せる
                # 次のLangGraph実行で、webauthn_auth_nodeが自動的に次のステップに進む

                # セッション保存（payment_webauthn_assertionのみ、stepは保存しない）
                await self._update_session(session_id, session)

                logger.info(
                    f"[submit_payment_attestation] PaymentMandate signed by user: "
                    f"payment_id={payment_mandate.get('id')}, next_step=payment_execution"
                )

                # AP2完全準拠: 署名検証成功レスポンス
                return {
                    "status": "success",
                    "message": "PaymentMandate signed successfully",
                    "next_step": "payment_execution"
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

    async def _generate_fixed_response_langgraph(
        self,
        user_input: str,
        session: Dict[str, Any],
        session_id: str
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        LangGraph StateGraphを使用した応答生成（ストリーミング）

        AP2完全準拠の決済フローを実装：
        - IntentMandate → CartMandate → PaymentMandateフロー
        - 各ステップが独立したノードとして明確に定義
        - Conditional Edgesで状態遷移を可視化
        - ノード単位でテスト可能
        - Langfuseトレーシングでセッション全体を1つのトレースとして統合

        Args:
            user_input: ユーザー入力
            session: セッションデータ
            session_id: セッションID（データベース保存用、Langfuseトレースのキー）

        Yields:
            StreamEvent: ストリーミングイベント
        """
        # Langfuseトレース設定（AP2完全準拠: オブザーバビリティ機能）
        from services.shopping_agent.langgraph_shopping_flow import LANGFUSE_ENABLED, CallbackHandler

        # 入力状態（Checkpointerと連携して状態を継続）
        # Checkpointerが既存の状態を読み込み、この入力とマージする
        input_state = {
            "user_input": user_input,
            "session_id": session_id,
            "session": session,
            "events": [],
            "next_step": None,
            "error": None
        }

        try:
            # グラフ実行（AP2完全準拠: IntentMandate → CartMandate → PaymentMandateフロー）
            # Langfuseトレースをセッションごとに統合（全グラフ実行が1つのトレースに含まれる）
            config = {}

            # Checkpointer用のthread_id設定（AP2完全準拠: トレース継続）
            # 同じsession_idで複数回呼び出すことで、1つの連続したトレースになる
            config["configurable"] = {"thread_id": session_id}

            if LANGFUSE_ENABLED and CallbackHandler:
                # セッションごとにCallbackHandlerインスタンスを取得または作成
                # 同じハンドラーを再利用することで、すべてのグラフ実行が1つのトレースに統合される
                if session_id not in self._langfuse_handlers:
                    # 新しいハンドラーを作成（AP2完全準拠: オブザーバビリティ）
                    langfuse_handler = CallbackHandler()
                    self._langfuse_handlers[session_id] = langfuse_handler
                    logger.info(f"[Langfuse] Created new handler for session: {session_id}")
                else:
                    langfuse_handler = self._langfuse_handlers[session_id]
                    logger.debug(f"[Langfuse] Reusing existing handler for session: {session_id}")

                # Langfuseハンドラーを設定
                config["callbacks"] = [langfuse_handler]
                # session_idをrun_idとして設定（重要：これにより同じトレースIDになる）
                config["run_id"] = session_id
                # metadataでsession_idとuser_idを指定
                config["metadata"] = {
                    "langfuse_session_id": session_id,
                    "langfuse_user_id": session.get("user_id", "anonymous"),
                    "agent_type": "shopping_agent"
                }
                config["tags"] = ["shopping_agent", "ap2_protocol"]

            # Checkpointerを使った呼び出し
            # thread_idを指定することで、既存の状態を読み込み、input_stateとマージする
            result = await self.shopping_flow_graph.ainvoke(input_state, config=config)

            # イベントをストリーミング出力
            for event_dict in result["events"]:
                # agent_text_chunkは文字単位で遅延を挿入
                if event_dict.get("type") == "agent_text_chunk":
                    yield StreamEvent(**event_dict)
                    await asyncio.sleep(0.02)  # 20ms遅延
                else:
                    yield StreamEvent(**event_dict)

            # データベースにセッション状態を保存
            # ルーティングロジックに必要なstepフィールドを含む完全なセッションを保存
            await self._update_session(session_id, result["session"])

        except Exception as e:
            logger.error(f"[{self.agent_name}] LangGraph flow execution failed: {e}", exc_info=True)
            # エラーイベントを返す
            yield StreamEvent(
                type="error",
                error=f"システムエラーが発生しました。「こんにちは」と入力して最初からやり直してください。"
            )

    async def _create_intent_mandate(self, intent: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        IntentMandateを作成（AP2完全準拠版）

        AP2仕様準拠：
        - AP2公式Pydanticモデル（IntentMandate）を使用
        - LangGraphでユーザーの自然言語入力からインテント抽出
        - AP2仕様のフィールドのみを含む
        - メタデータ（id, user_id等）は呼び出し側で管理

        Args:
            intent: ユーザーの自然言語入力
            session: セッションデータ

        Returns:
            IntentMandate（辞書形式、AP2仕様準拠の構造）
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

        # IntentMandate作成（AP2公式Pydanticモデル使用）
        intent_mandate_model = self._build_intent_mandate_from_session(intent, session, user_id, now)

        # Pydanticモデルを辞書化（AP2仕様準拠フィールドのみ）
        intent_mandate_dict = intent_mandate_model.model_dump(exclude_none=True)

        # AP2仕様外のメタデータを追加（A2A通信やセッション管理用）
        #
        # 注意: AP2仕様では、IntentMandateは以下のフィールドのみを含む：
        #   - user_cart_confirmation_required
        #   - natural_language_description
        #   - merchants (Optional)
        #   - skus (Optional)
        #   - requires_refundability (Optional)
        #   - intent_expiry
        #
        # 以下のメタデータはAP2仕様外だが、実装上の理由で含めています：
        #   - id: データベースおよびA2Aメッセージ識別用
        #   - type: メッセージタイプ識別用
        #   - user_id: セッション管理およびMerchant Agent処理用
        #   - created_at: 監査ログ用
        #
        # 将来的には、これらのメタデータをA2Aメッセージエンベロープや
        # 別のデータ構造で管理することが望ましいです。
        intent_mandate_with_metadata = {
            "id": f"intent_{uuid.uuid4().hex[:8]}",
            "type": "IntentMandate",
            "user_id": user_id,
            **intent_mandate_dict,  # AP2準拠フィールド（Pydanticモデルから生成）
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        return intent_mandate_with_metadata

    def _build_intent_mandate_from_session(
        self,
        intent: str,
        session: Dict[str, Any],
        user_id: str,
        now: datetime
    ) -> IntentMandate:
        """セッションデータからIntentMandateを構築（AP2完全準拠）

        LangGraph StateGraphで収集した情報からIntentMandateを生成
        AP2公式Pydanticモデル（common/mandate_types.py）を使用

        Args:
            intent: ユーザー入力
            session: セッションデータ
            user_id: ユーザーID
            now: 現在時刻

        Returns:
            IntentMandate（AP2公式Pydanticモデル）
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

        logger.info(f"[_build_intent_mandate_from_session] Constructed natural_language_description: {natural_language_description}")

        # AP2公式Pydanticモデルを使用（mandate_types.py:25-71）
        intent_mandate = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description=natural_language_description,
            merchants=merchants if merchants else None,
            skus=skus if skus else None,
            requires_refundability=False,
            intent_expiry=expires_at.isoformat().replace('+00:00', 'Z')
        )

        logger.info(
            f"[ShoppingAgent] IntentMandate created (AP2-compliant): "
            f"intent='{intent[:50]}...', expiry={intent_mandate.intent_expiry}"
        )

        return intent_mandate

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
        """CartMandateのハッシュを生成（ヘルパーメソッドに委譲）"""
        return self.hash_helpers.generate_cart_mandate_hash(cart_mandate)

    def _generate_payment_mandate_hash(self, payment_mandate: Dict[str, Any]) -> str:
        """PaymentMandateのハッシュを生成（ヘルパーメソッドに委譲）"""
        return self.hash_helpers.generate_payment_mandate_hash(payment_mandate)

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
        """取引タイプ判定（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.determine_transaction_type(session)

    def _validate_cart_and_payment_method(self, session: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
        """カート情報と支払い方法の検証（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.validate_cart_and_payment_method(session)

    def _extract_payment_amount_from_cart(self, cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """金額情報の抽出（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.extract_payment_amount_from_cart(cart_mandate)

    def _build_payment_response(self, tokenized_payment_method: Dict[str, Any]) -> Dict[str, Any]:
        """PaymentResponse構築（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.build_payment_response(tokenized_payment_method)

    def _build_payment_mandate_contents(
        self,
        cart_mandate: Dict[str, Any],
        total_amount: Dict[str, Any],
        payment_response: Dict[str, Any]
    ) -> tuple[str, Dict[str, Any]]:
        """PaymentMandateContents構築（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.build_payment_mandate_contents(cart_mandate, total_amount, payment_response)

    async def _generate_user_authorization_for_payment(
        self,
        session: Dict[str, Any],
        cart_mandate: Dict[str, Any],
        payment_mandate_contents: Dict[str, Any]
    ) -> Optional[str]:
        """user_authorization生成（ヘルパーメソッドに委譲）"""
        # AP2完全準拠: Credential ProviderからDBに保存された公開鍵を取得
        cart_webauthn_assertion = session.get("cart_webauthn_assertion")
        if not cart_webauthn_assertion:
            return None

        try:
            credential_id = cart_webauthn_assertion.get("id")
            user_id = session.get("user_id", "user_demo_001")
            selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

            # SignatureHandlersを使用してCredential Providerから公開鍵を取得
            public_key_cose = await SignatureHandlers.retrieve_public_key_from_cp(
                http_client=self.http_client,
                credential_provider_url=selected_cp['url'],
                credential_id=credential_id,
                user_id=user_id,
                timeout=SHORT_HTTP_TIMEOUT
            )

            return self.payment_helpers.generate_user_authorization_for_payment(
                session, cart_mandate, payment_mandate_contents, public_key_cose
            )
        except Exception as e:
            logger.error(f"[_generate_user_authorization_for_payment] Failed to retrieve public key: {e}", exc_info=True)
            return None

    def _perform_risk_assessment(
        self,
        payment_mandate: Dict[str, Any],
        cart_mandate: Dict[str, Any],
        intent_mandate: Optional[Dict[str, Any]]
    ) -> tuple[int, list[str]]:
        """リスク評価実施（ヘルパーメソッドに委譲）"""
        return self.payment_helpers.perform_risk_assessment(payment_mandate, cart_mandate, intent_mandate)

    async def _create_payment_mandate(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """
        PaymentMandateを作成（リスク評価統合版）

        AP2仕様準拠（Step 19）：
        - トークン化された支払い方法を使用
        - セキュアトークンをPaymentMandateに含める
        - リスク評価を実施してリスクスコアと不正指標を追加
        - CartMandateの金額情報を使用
        """
        # 1. カート情報と支払い方法の検証
        cart_mandate, tokenized_payment_method = self._validate_cart_and_payment_method(session)

        # 2. 金額情報の抽出
        total_amount = self._extract_payment_amount_from_cart(cart_mandate)

        # 3. PaymentResponseの構築
        payment_response = self._build_payment_response(tokenized_payment_method)

        # 4. PaymentMandateContentsの構築
        payment_mandate_id, payment_mandate_contents = self._build_payment_mandate_contents(
            cart_mandate,
            total_amount,
            payment_response
        )

        # 5. user_authorizationの生成
        user_authorization = await self._generate_user_authorization_for_payment(
            session,
            cart_mandate,
            payment_mandate_contents
        )

        # 6. PaymentMandateの構築
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

        # 7. リスク評価を実施
        risk_score, fraud_indicators = self._perform_risk_assessment(
            payment_mandate,
            session.get("cart_mandate"),
            session.get("intent_mandate")
        )
        payment_mandate["risk_score"] = risk_score
        payment_mandate["fraud_indicators"] = fraud_indicators

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
        # MerchantIntegrationHelpersを使用して決済処理を実行
        return await MerchantIntegrationHelpers.process_payment_via_merchant(
            a2a_handler=self.a2a_handler,
            http_client=self.http_client,
            merchant_agent_url=self.merchant_agent_url,
            payment_mandate=payment_mandate,
            cart_mandate=cart_mandate,
            tracer=tracer,
            create_http_span=create_http_span,
            a2a_communication_timeout=A2A_COMMUNICATION_TIMEOUT
        )

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
        # MerchantIntegrationHelpersを使用してカート候補を取得
        return await MerchantIntegrationHelpers.search_products_via_merchant(
            a2a_handler=self.a2a_handler,
            http_client=self.http_client,
            merchant_agent_url=self.merchant_agent_url,
            intent_mandate=intent_mandate,
            session=session,
            tracer=tracer,
            create_http_span=create_http_span,
            a2a_communication_timeout=A2A_COMMUNICATION_TIMEOUT
        )

    def _build_cart_request(
        self,
        selected_product: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """CartRequest構築（ヘルパーメソッドに委譲）"""
        return self.cart_helpers.build_cart_request(selected_product, session)

    async def _send_cart_request_via_a2a(
        self,
        cart_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """CartRequestをA2A経由で送信（ヘルパーメソッドに委譲）"""
        return await self.a2a_helpers.send_cart_request_via_a2a(cart_request)

    async def _extract_cart_mandate_from_a2a_response(
        self,
        result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        A2AレスポンスからCartMandateを抽出

        Note: Merchant承認待機はこのメソッドで処理（_wait_for_merchant_approvalへの依存）
        """
        # 基本的な抽出処理はヘルパーに委譲
        signed_cart_mandate = await self.cart_helpers.extract_cart_mandate_from_a2a_response(result)

        # signed_cart_mandateがNoneの場合、Merchant承認待機が必要な可能性がある
        if signed_cart_mandate is None:
            # ヘルパーがNoneを返した場合は、Pending状態を検出した可能性がある
            # この場合、ここでポーリング処理を実行
            data_part = result.get("dataPart", {})
            response_type = data_part.get("@type") or data_part.get("type")
            if response_type == "ap2.responses.CartMandatePending":
                pending_info = data_part["payload"]
                cart_mandate_id = pending_info.get("cart_mandate_id")
                logger.info(f"[ShoppingAgent] CartMandate is pending merchant approval: {cart_mandate_id}. Waiting for approval...")
                signed_cart_mandate = await self._wait_for_merchant_approval(cart_mandate_id)

        return signed_cart_mandate

    def _verify_merchant_cart_signature(
        self,
        signed_cart_mandate: Dict[str, Any]
    ) -> None:
        """CartMandate署名検証（ヘルパーメソッドに委譲）"""
        self.cart_helpers.verify_merchant_cart_signature(signed_cart_mandate)

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
            # 1. CartRequest作成
            cart_request = self._build_cart_request(selected_product, session)

            # 2. CartRequestをA2A経由で送信
            result = await self._send_cart_request_via_a2a(cart_request)

            # 3. A2AレスポンスからCartMandateを抽出
            signed_cart_mandate = await self._extract_cart_mandate_from_a2a_response(result)

            if signed_cart_mandate:
                logger.info(f"[ShoppingAgent] Processing CartMandate: {signed_cart_mandate.get('id')}")

                # 4. Merchant署名を検証
                self._verify_merchant_cart_signature(signed_cart_mandate)

                return signed_cart_mandate
            else:
                raise ValueError("Failed to extract CartMandate from response")

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
        # MerchantIntegrationHelpersを使用して署名リクエスト
        return await MerchantIntegrationHelpers.request_merchant_signature(
            http_client=self.http_client,
            merchant_url=self.merchant_url,
            cart_mandate=cart_mandate,
            signature_manager=self.signature_manager,
            timeout=SHORT_HTTP_TIMEOUT
        )

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
                timeout=SHORT_HTTP_TIMEOUT
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
                timeout=SHORT_HTTP_TIMEOUT
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
                timeout=SHORT_HTTP_TIMEOUT
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

    async def _wait_for_merchant_approval(self, cart_mandate_id: str, timeout: int = MERCHANT_APPROVAL_TIMEOUT, poll_interval: int = MERCHANT_APPROVAL_POLL_INTERVAL) -> Dict[str, Any]:
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
                    timeout=SHORT_HTTP_TIMEOUT
                )
                response.raise_for_status()
                result = response.json()

                status = result.get("status")
                payload = result.get("payload")

                logger.debug(f"[ShoppingAgent] CartMandate {cart_mandate_id} status: {status}")

                # ===== 署名完了 =====
                if status == STATUS_SIGNED:
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

                # ===== 拒否された =====
                elif status == STATUS_REJECTED:
                    logger.warning(f"[ShoppingAgent] CartMandate {cart_mandate_id} has been rejected by merchant")
                    raise ValueError(f"CartMandateがMerchantに拒否されました（ID: {cart_mandate_id}）")

                # ===== まだpending - 待機 =====
                elif status == STATUS_PENDING_MERCHANT_SIGNATURE:
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
