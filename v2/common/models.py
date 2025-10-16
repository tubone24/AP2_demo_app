"""
v2/common/models.py

FastAPI用のPydanticモデル
demo_app_v2.mdの要件に基づくA2AメッセージとAPIリクエスト/レスポンス型
"""

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum


# ========================================
# A2A Message Models (demo_app_v2.md準拠)
# ========================================

class A2ASignature(BaseModel):
    """
    A2Aメッセージの署名（旧形式：後方互換性のため保持）

    非推奨: 新規実装ではA2AProofを使用してください
    """
    algorithm: Literal["ed25519", "ecdsa"] = "ecdsa"
    public_key: str = Field(..., description="BASE64エンコードされた公開鍵")
    value: str = Field(..., description="BASE64エンコードされた署名値")


class A2AProof(BaseModel):
    """
    A2Aメッセージの署名証明（Proof）

    W3C Verifiable Credentials仕様に準拠したproof構造
    A2A仕様準拠：header.proof として使用

    Example:
    {
      "algorithm": "ecdsa",
      "signatureValue": "MEUCIQDx...",
      "publicKey": "LS0tLS1CRU...",
      "created": "2025-10-16T12:34:56Z",
      "proofPurpose": "authentication"
    }
    """
    algorithm: Literal["ed25519", "ecdsa"] = Field(default="ecdsa", description="署名アルゴリズム")
    signatureValue: str = Field(..., description="BASE64エンコードされた署名値")
    publicKey: str = Field(..., description="BASE64エンコードされた公開鍵")
    created: str = Field(..., description="署名作成日時（ISO 8601）")
    proofPurpose: Literal["authentication", "assertionMethod", "agreement"] = Field(
        default="authentication",
        description="証明の目的"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "algorithm": "ecdsa",
                "signatureValue": "MEUCIQDx8yZ...",
                "publicKey": "LS0tLS1CRU...",
                "created": "2025-10-16T12:34:56Z",
                "proofPurpose": "authentication"
            }
        }


# ========================================
# Cryptographic Models (AP2完全準拠)
# ========================================

class Signature(BaseModel):
    """
    暗号署名

    AP2仕様に準拠したECDSA署名
    """
    algorithm: str = Field(default="ECDSA", description="署名アルゴリズム")
    value: str = Field(..., description="BASE64エンコードされた署名値")
    public_key: str = Field(..., description="BASE64エンコードされた公開鍵（PEM形式）")
    signed_at: str = Field(..., description="署名日時（ISO 8601）")

    class Config:
        json_schema_extra = {
            "example": {
                "algorithm": "ECDSA",
                "value": "MEUCIQDx...",
                "public_key": "LS0tLS1CRU...",
                "signed_at": "2025-10-16T12:34:56Z"
            }
        }


class AttestationType(str, Enum):
    """デバイス証明のタイプ"""
    BIOMETRIC = "biometric"
    PIN = "pin"
    PATTERN = "pattern"
    DEVICE_CREDENTIAL = "device_credential"
    WEBAUTHN = "webauthn"


class DeviceAttestation(BaseModel):
    """
    デバイス証明

    AP2ステップ20-23で使用される、デバイスが信頼されており
    取引が改ざんされていないことを証明する暗号学的証拠
    """
    device_id: str = Field(..., description="デバイスの一意識別子")
    attestation_type: AttestationType = Field(..., description="認証タイプ")
    attestation_value: str = Field(..., description="BASE64エンコードされた証明値")
    timestamp: str = Field(..., description="証明日時（ISO 8601）")
    device_public_key: str = Field(..., description="デバイスの公開鍵（BASE64）")
    challenge: str = Field(..., description="リプレイ攻撃対策のチャレンジ値")
    platform: str = Field(..., description="プラットフォーム（iOS, Android, Web等）")
    os_version: Optional[str] = Field(None, description="OSバージョン")
    app_version: Optional[str] = Field(None, description="アプリバージョン")

    # WebAuthn固有フィールド
    webauthn_signature: Optional[str] = Field(None, description="WebAuthn署名データ")
    webauthn_authenticator_data: Optional[str] = Field(None, description="WebAuthn Authenticator Data")
    webauthn_client_data_json: Optional[str] = Field(None, description="WebAuthn Client Data JSON")

    class Config:
        use_enum_values = True
        json_schema_extra = {
            "example": {
                "device_id": "device_abc123",
                "attestation_type": "webauthn",
                "attestation_value": "MEUCIQDx...",
                "timestamp": "2025-10-16T12:34:56Z",
                "device_public_key": "LS0tLS1CRU...",
                "challenge": "random_challenge_abc123",
                "platform": "Web",
                "os_version": "macOS 14.0",
                "app_version": "1.0.0"
            }
        }


class UserConsent(BaseModel):
    """
    ユーザー同意メッセージ（Consent）

    AP2/A2A仕様準拠：
    - ユーザーがCartMandateを承認するための独立したメッセージ
    - スキーマ: a2a://consent/v0.1
    - ユーザーのPasskey署名を含む
    - Intent MandateとCart Mandateへの参照を持つ

    専門家の指摘：
    "Consent生成時にユーザーPasskey署名を取得し、IntentのintentフィールドとCartの内容に対してユーザー意思を確認する"
    """
    consent_id: str = Field(..., description="同意ID（uuid-v4）")
    cart_mandate_id: str = Field(..., description="対象のCartMandate ID")
    intent_message_id: str = Field(..., description="元のIntent MandateのA2AメッセージID（トレーサビリティ）")
    user_id: str = Field(..., description="ユーザーID")
    approved: bool = Field(..., description="ユーザーの承認（true=承認、false=拒否）")
    timestamp: str = Field(..., description="同意タイムスタンプ（ISO 8601）")

    # WebAuthn Passkey署名（ユーザー意思の暗号学的証明）
    passkey_signature: Optional[Dict[str, Any]] = Field(
        None,
        description="WebAuthn Passkey署名データ（clientDataJSON, authenticatorData, signature, challenge）"
    )

    # 署名対象データのハッシュ（検証用）
    signed_data_hash: Optional[str] = Field(
        None,
        description="署名対象データ（intent + cart内容）のSHA-256ハッシュ（hex形式）"
    )

    # 追加情報
    user_comment: Optional[str] = Field(None, description="ユーザーコメント（任意）")
    device_info: Optional[Dict[str, Any]] = Field(None, description="デバイス情報（任意）")

    class Config:
        json_schema_extra = {
            "example": {
                "consent_id": "consent_abc123",
                "cart_mandate_id": "cart_xyz789",
                "intent_message_id": "msg_intent_456",
                "user_id": "user_demo_001",
                "approved": True,
                "timestamp": "2025-10-16T12:34:56Z",
                "passkey_signature": {
                    "challenge": "random_challenge",
                    "clientDataJSON": "eyJ0eXBlIjoid2ViYXV0aG4uZ2V0Ii...",
                    "authenticatorData": "SZYN5YgOjGh0NBcPZ...",
                    "signature": "MEUCIQDx8yZ..."
                },
                "signed_data_hash": "a1b2c3d4e5f6..."
            }
        }


class A2AMessageHeader(BaseModel):
    """
    A2A Message Header

    A2A仕様準拠（2025年版）：
    {
      "message_id": "uuid-v4",
      "sender": "did:ap2:agent:shopping_agent",
      "recipient": "did:ap2:agent:merchant_agent",
      "timestamp": "2025-10-15T12:34:56Z",
      "schema_version": "0.2",
      "proof": {
        "algorithm": "ecdsa",
        "signatureValue": "...",
        "publicKey": "...",
        "created": "2025-10-15T12:34:56Z",
        "proofPurpose": "authentication"
      }
    }
    """
    message_id: str = Field(..., description="メッセージID (uuid-v4)")
    sender: str = Field(..., description="送信者エージェントDID (e.g., did:ap2:agent:shopping_agent)")
    recipient: str = Field(..., description="受信者エージェントDID (e.g., did:ap2:agent:merchant_agent)")
    timestamp: str = Field(..., description="ISO 8601タイムスタンプ (e.g., 2025-10-15T12:34:56Z)")
    schema_version: str = Field(default="0.2", description="スキーマバージョン")

    # A2A仕様準拠：proof構造を使用（推奨）
    proof: Optional[A2AProof] = Field(None, description="メッセージ全体の署名証明（A2A仕様準拠）")

    # 旧形式：後方互換性のため保持（非推奨）
    signature: Optional[A2ASignature] = Field(None, description="[非推奨] メッセージ全体の署名（後方互換性のため保持）")


class A2ADataPart(BaseModel):
    """
    A2A DataPart

    demo_app_v2.mdの仕様：
    {
      "@type": "ap2/IntentMandate" | "ap2/CartMandate" | "ap2/PaymentMandate",
      "id": "intent-123",
      "payload": { ... }
    }
    """
    type: Literal[
        "ap2.mandates.IntentMandate",
        "ap2.mandates.CartMandate",
        "ap2.requests.CartRequest",
        "ap2.responses.CartMandatePending",
        "ap2.mandates.PaymentMandate",
        "ap2.responses.PaymentResult",
        "ap2.requests.ProductSearch",
        "ap2.responses.ProductList",
        "ap2.requests.SignatureRequest",
        "ap2.responses.SignatureResponse",
        "ap2.consents.UserConsent",
        "ap2.errors.Error"
    ] = Field(..., alias="@type", description="データタイプ（AP2仕様準拠）")
    id: str = Field(..., description="データID")
    payload: Dict[str, Any] = Field(..., description="各タイプ固有のペイロード")

    class Config:
        populate_by_name = True


class A2AMessage(BaseModel):
    """
    A2A Message (完全な形式)

    demo_app_v2.md: 全エージェント共通のPOST /a2a/messageで使用
    """
    header: A2AMessageHeader
    dataPart: A2ADataPart


# ========================================
# Shopping Agent固有のAPI Models
# ========================================

class ChatStreamRequest(BaseModel):
    """
    POST /chat/stream リクエスト

    demo_app_v2.md:
    { "user_input": string, "session_id"?: string }
    """
    user_input: str = Field(..., description="ユーザーの入力テキスト")
    session_id: Optional[str] = Field(None, description="セッションID（継続対話用）")


class StreamEvent(BaseModel):
    """
    SSE Streaming Event

    demo_app_v2.md:
    { "type": "agent_text", "content": "..." }
    { "type": "signature_request", "mandate": { ...IntentMandate... }, "mandate_type": "intent" }
    { "type": "cart_options", "items": [...] }
    { "type": "shipping_form_request", "form_schema": {...} }
    { "type": "payment_method_selection", "payment_methods": [...] }
    { "type": "credential_provider_selection", "providers": [...] }
    { "type": "webauthn_request", "challenge": "...", "rp_id": "...", "timeout": 60000 }
    """
    type: Literal[
        "agent_text",
        "signature_request",
        "cart_options",
        "shipping_form_request",
        "payment_method_selection",
        "credential_provider_selection",
        "webauthn_request",
        "error",
        "done"
    ]
    content: Optional[str] = None
    mandate: Optional[Dict[str, Any]] = None
    mandate_type: Optional[Literal["intent", "cart", "payment"]] = None
    items: Optional[List[Dict[str, Any]]] = None

    # リッチコンテンツ用フィールド
    form_schema: Optional[Dict[str, Any]] = None  # 配送先フォームスキーマ
    payment_methods: Optional[List[Dict[str, Any]]] = None  # 支払い方法リスト
    providers: Optional[List[Dict[str, Any]]] = None  # Credential Providerリスト

    # WebAuthn用フィールド
    challenge: Optional[str] = None
    rp_id: Optional[str] = None
    timeout: Optional[int] = None

    error: Optional[str] = None


# ========================================
# Merchant Agent固有のAPI Models
# ========================================

class ProductSearchRequest(BaseModel):
    """商品検索リクエスト"""
    query: str = Field(..., description="検索クエリ")
    category: Optional[str] = None
    max_results: int = Field(default=10, ge=1, le=100)


class ProductResponse(BaseModel):
    """商品情報レスポンス"""
    id: str
    sku: str
    name: str
    description: str
    price: int = Field(..., description="価格（cents）")
    inventory_count: int
    image_url: Optional[str] = None
    category: Optional[str] = None
    brand: Optional[str] = None


class InventoryUpdateRequest(BaseModel):
    """在庫更新リクエスト"""
    product_id: str
    quantity_delta: int = Field(..., description="在庫変動量（正=追加、負=削減）")


# ========================================
# Merchant固有のAPI Models
# ========================================

class CartSignRequest(BaseModel):
    """
    POST /sign/cart リクエスト

    Merchant AgentからMerchantへCartMandateの署名を依頼
    """
    cart_mandate: Dict[str, Any] = Field(..., description="署名対象のCartMandate")


class CartSignResponse(BaseModel):
    """POST /sign/cart レスポンス"""
    signed_cart_mandate: Dict[str, Any] = Field(..., description="署名済みCartMandate")
    merchant_signature: A2ASignature


# ========================================
# Credential Provider固有のAPI Models
# ========================================

class AttestationVerifyRequest(BaseModel):
    """
    POST /verify/attestation リクエスト

    demo_app_v2.md:
    { "payment_mandate": {...}, "attestation": {...} }
    """
    payment_mandate: Dict[str, Any]
    attestation: Dict[str, Any] = Field(..., description="WebAuthn attestation")


class AttestationVerifyResponse(BaseModel):
    """POST /verify/attestation レスポンス"""
    verified: bool
    token: Optional[str] = Field(None, description="検証成功時のトークン")
    details: Optional[Dict[str, Any]] = None


class PaymentMethodsResponse(BaseModel):
    """GET /payment-methods レスポンス"""
    user_id: str
    payment_methods: List[Dict[str, Any]]


# ========================================
# Payment Processor固有のAPI Models
# ========================================

class ProcessPaymentRequest(BaseModel):
    """
    POST /process リクエスト

    支払い実行（モック）
    """
    payment_mandate: Dict[str, Any]
    credential_token: Optional[str] = None


class ProcessPaymentResponse(BaseModel):
    """POST /process レスポンス"""
    transaction_id: str
    status: Literal["authorized", "captured", "failed"]
    receipt_url: Optional[str] = None
    error: Optional[str] = None


# ========================================
# Database Models (SQLite用)
# ========================================

class ProductDB(BaseModel):
    """productsテーブル"""
    id: str
    sku: str
    name: str
    description: str
    price: int  # cents
    inventory_count: int
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


class UserDB(BaseModel):
    """usersテーブル"""
    id: str
    display_name: str
    email: str
    created_at: datetime


class MandateDB(BaseModel):
    """mandatesテーブル"""
    id: str
    type: Literal["Intent", "Cart", "Payment"]
    status: Literal["draft", "pending_signature", "signed", "submitted", "completed", "failed"]
    payload: Dict[str, Any]
    issuer: str
    issued_at: datetime
    updated_at: datetime
    related_transaction_id: Optional[str] = None


class TransactionDB(BaseModel):
    """transactionsテーブル"""
    id: str
    intent_id: Optional[str]
    cart_id: Optional[str]
    payment_id: Optional[str]
    status: str
    events: List[Dict[str, Any]]
    created_at: datetime
    updated_at: datetime


class AttestationDB(BaseModel):
    """attestationsテーブル"""
    id: str
    user_id: str
    attestation_raw: Dict[str, Any]
    verified: bool
    verification_details: Optional[Dict[str, Any]]
    created_at: datetime
