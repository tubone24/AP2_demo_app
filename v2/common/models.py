"""
v2/common/models.py

FastAPI用のPydanticモデル
demo_app_v2.mdの要件に基づくA2AメッセージとAPIリクエスト/レスポンス型

AP2型定義統合:
- W3C Payment Request API型（11型）: common/payment_types.py
- AP2 Mandate型（5型）: common/mandate_types.py
- JWT生成・検証: common/jwt_utils.py
"""

from typing import Any, Dict, List, Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime
from enum import Enum

# AP2公式型定義をインポート（AP2プロトコル完全準拠）
from common.payment_types import (
    ContactAddress,
    PaymentCurrencyAmount,
    PaymentItem,
    PaymentShippingOption,
    PaymentOptions,
    PaymentMethodData,
    PaymentDetailsModifier,
    PaymentDetailsInit,
    PaymentRequest,
    PaymentResponse,
)

from common.mandate_types import (
    IntentMandate,
    CartContents,
    CartMandate,
    PaymentMandateContents,
    PaymentMandate,
)

# JWT Utilsは循環インポート回避のため、必要な箇所で直接インポートしてください
# from common.jwt_utils import compute_canonical_hash, MerchantAuthorizationJWT, UserAuthorizationSDJWT


# ========================================
# A2A Message Models (demo_app_v2.md準拠)
# ========================================

class A2AProof(BaseModel):
    """
    A2Aメッセージの署名証明（Proof）

    W3C Verifiable Credentials仕様に準拠したproof構造
    A2A仕様準拠：header.proof として使用

    AP2完全準拠：
    - publicKeyMultibase形式を使用（W3C DID仕様推奨）
    - 'z6Mk...'（Ed25519）または 'z...'（P-256）形式
    - kid（鍵ID）でDIDベースの鍵解決を可能に
    - algorithmの検証を強化（Ed25519/ES256のみ許可）

    Example:
    {
      "algorithm": "ed25519",
      "signatureValue": "MEUCIQDx...",
      "publicKeyMultibase": "z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",
      "kid": "did:ap2:agent:shopping_agent#key-1",
      "created": "2025-10-16T12:34:56Z",
      "proofPurpose": "authentication"
    }
    """
    algorithm: Literal["ed25519", "ecdsa"] = Field(default="ed25519", description="署名アルゴリズム（EdDSA/ES256）")
    signatureValue: str = Field(..., description="BASE64エンコードされた署名値")
    publicKeyMultibase: str = Field(..., description="Multibase形式の公開鍵（W3C DID仕様準拠）")
    kid: Optional[str] = Field(None, description="鍵ID（DIDフラグメント）例: did:ap2:agent:shopping_agent#key-1")
    created: str = Field(..., description="署名作成日時（ISO 8601）")
    proofPurpose: Literal["authentication", "assertionMethod", "agreement"] = Field(
        default="authentication",
        description="証明の目的"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "algorithm": "ed25519",
                "signatureValue": "MEUCIQDx8yZ...",
                "publicKeyMultibase": "z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",
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

    AP2完全準拠：
    - Ed25519/ECDSA署名をサポート
    - publicKeyMultibase形式を使用（W3C DID仕様推奨）
    - デフォルト: Ed25519（2025年推奨アルゴリズム）
    """
    algorithm: str = Field(default="Ed25519", description="署名アルゴリズム（Ed25519/ECDSA）")
    value: str = Field(..., description="BASE64エンコードされた署名値")
    publicKeyMultibase: str = Field(..., description="Multibase形式の公開鍵（W3C DID仕様準拠）")
    signed_at: str = Field(..., description="署名日時（ISO 8601）")
    key_id: Optional[str] = Field(None, description="署名に使用した鍵のID")

    class Config:
        json_schema_extra = {
            "example": {
                "algorithm": "Ed25519",
                "value": "MEUCIQDx...",
                "publicKeyMultibase": "z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",
                "signed_at": "2025-10-16T12:34:56Z",
                "key_id": "shopping_agent"
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


# ========================================
# DID Document Models (W3C DID仕様準拠)
# ========================================

class VerificationMethod(BaseModel):
    """
    DIDドキュメントの検証メソッド

    W3C DID仕様準拠：公開鍵とその用途を定義
    専門家の指摘対応：DIDベースの公開鍵解決を実現

    Example:
    {
      "id": "did:ap2:agent:shopping_agent#key-1",
      "type": "EcdsaSecp256k1VerificationKey2019",
      "controller": "did:ap2:agent:shopping_agent",
      "publicKeyPem": "-----BEGIN PUBLIC KEY-----..."
    }
    """
    id: str = Field(..., description="検証メソッドID（DIDフラグメント形式）")
    type: str = Field(..., description="公開鍵タイプ（例: EcdsaSecp256k1VerificationKey2019）")
    controller: str = Field(..., description="コントローラーDID")
    publicKeyPem: str = Field(..., description="PEM形式の公開鍵")

    class Config:
        json_schema_extra = {
            "example": {
                "id": "did:ap2:agent:shopping_agent#key-1",
                "type": "EcdsaSecp256k1VerificationKey2019",
                "controller": "did:ap2:agent:shopping_agent",
                "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...\n-----END PUBLIC KEY-----"
            }
        }


class ServiceEndpoint(BaseModel):
    """
    DIDドキュメントのサービスエンドポイント

    W3C DID仕様準拠：エンティティが提供するサービスの情報

    Example:
    {
      "id": "did:ap2:merchant:nike#merchant-agent",
      "type": "AP2MerchantAgent",
      "serviceEndpoint": "https://merchant-agent.nike.com",
      "name": "Nike Merchant Agent",
      "description": "Nike公式ストアのMerchant Agent"
    }

    Credential Provider の場合:
    {
      "id": "did:ap2:cp:demo_cp#credential-provider",
      "type": "AP2CredentialProvider",
      "serviceEndpoint": "http://credential_provider:8003",
      "name": "AP2 Demo Credential Provider",
      "description": "デモ用CP（Passkey対応）",
      "supported_methods": ["card", "passkey"],
      "logo_url": "https://example.com/cp_demo_logo.png"
    }
    """
    id: str = Field(..., description="サービスID（DIDフラグメント形式）")
    type: str = Field(..., description="サービスタイプ（例: AP2MerchantAgent, AP2CredentialProvider）")
    serviceEndpoint: str = Field(..., description="サービスエンドポイントURL")
    name: Optional[str] = Field(None, description="サービス名（人間可読）")
    description: Optional[str] = Field(None, description="サービスの説明")
    supported_methods: Optional[List[str]] = Field(None, description="サポートする支払い方法（CPの場合）")
    logo_url: Optional[str] = Field(None, description="ロゴURL（CPの場合）")


class DIDDocument(BaseModel):
    """
    DIDドキュメント

    W3C DID仕様準拠：DIDの解決結果として返されるドキュメント
    専門家の指摘対応：sender_didから公開鍵を解決するための基盤

    Example:
    {
      "id": "did:ap2:agent:shopping_agent",
      "verificationMethod": [
        {
          "id": "did:ap2:agent:shopping_agent#key-1",
          "type": "EcdsaSecp256k1VerificationKey2019",
          "controller": "did:ap2:agent:shopping_agent",
          "publicKeyPem": "-----BEGIN PUBLIC KEY-----..."
        }
      ],
      "authentication": ["#key-1"],
      "service": [
        {
          "id": "did:ap2:merchant:nike#merchant-agent",
          "type": "AP2MerchantAgent",
          "serviceEndpoint": "https://merchant-agent.nike.com"
        }
      ]
    }
    """
    id: str = Field(..., description="DID（例: did:ap2:agent:shopping_agent）")
    verificationMethod: List[VerificationMethod] = Field(
        default_factory=list,
        description="検証メソッドのリスト（公開鍵情報）"
    )
    authentication: List[str] = Field(
        default_factory=list,
        description="認証に使用できる検証メソッドのIDリスト"
    )
    assertionMethod: Optional[List[str]] = Field(
        None,
        description="アサーションに使用できる検証メソッドのIDリスト"
    )
    keyAgreement: Optional[List[str]] = Field(
        None,
        description="鍵共有に使用できる検証メソッドのIDリスト"
    )
    service: Optional[List[ServiceEndpoint]] = Field(
        None,
        description="サービスエンドポイントのリスト（AP2準拠）"
    )

    class Config:
        json_schema_extra = {
            "example": {
                "id": "did:ap2:agent:shopping_agent",
                "verificationMethod": [
                    {
                        "id": "did:ap2:agent:shopping_agent#key-1",
                        "type": "EcdsaSecp256k1VerificationKey2019",
                        "controller": "did:ap2:agent:shopping_agent",
                        "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
                    }
                ],
                "authentication": ["#key-1"]
            }
        }


class A2AMessageHeader(BaseModel):
    """
    A2A Message Header

    A2A仕様準拠（2025年版）：

    専門家の指摘対応：
    - nonce: リプレイ攻撃対策として必須（一度きりの使用を保証）
    - timestamp: タイムスタンプ検証によるリプレイ攻撃対策

    {
      "message_id": "uuid-v4",
      "sender": "did:ap2:agent:shopping_agent",
      "recipient": "did:ap2:agent:merchant_agent",
      "timestamp": "2025-10-15T12:34:56Z",
      "nonce": "random_hex_64_chars",
      "schema_version": "0.2",
      "proof": {
        "algorithm": "ecdsa",
        "signatureValue": "...",
        "publicKey": "...",
        "kid": "did:ap2:agent:shopping_agent#key-1",
        "created": "2025-10-15T12:34:56Z",
        "proofPurpose": "authentication"
      }
    }
    """
    message_id: str = Field(..., description="メッセージID (uuid-v4)")
    sender: str = Field(..., description="送信者エージェントDID (e.g., did:ap2:agent:shopping_agent)")
    recipient: str = Field(..., description="受信者エージェントDID (e.g., did:ap2:agent:merchant_agent)")
    timestamp: str = Field(..., description="ISO 8601タイムスタンプ (e.g., 2025-10-15T12:34:56Z)")
    nonce: str = Field(..., description="リプレイ攻撃対策用のワンタイムノンス（hex形式、32バイト以上推奨）")
    schema_version: str = Field(default="0.9", description="スキーマバージョン")

    # A2A仕様準拠：proof構造を使用（AP2完全準拠）
    proof: Optional[A2AProof] = Field(None, description="メッセージ全体の署名証明（A2A仕様準拠）")


class A2AArtifactPart(BaseModel):
    """
    A2A Artifact Part

    AP2/A2A仕様準拠（a2a-extension.md）:
    Artifactの個別パート（data, text, image等）
    """
    kind: Literal["data", "text", "image", "file"] = Field(..., description="パートの種類")
    data: Dict[str, Any] = Field(..., description="パートのデータ（kind=dataの場合）")
    text: Optional[str] = Field(None, description="テキストコンテンツ（kind=textの場合）")
    mimeType: Optional[str] = Field(None, description="MIMEタイプ")


class A2AArtifact(BaseModel):
    """
    A2A Artifact

    AP2/A2A仕様準拠（a2a-extension.md:144-229）:
    CartMandateはArtifactとして扱われる

    Example:
    {
      "name": "Cart Mandate for Order",
      "artifactId": "artifact_cart_123",
      "parts": [
        {
          "kind": "data",
          "data": {
            "ap2.mandates.CartMandate": { ... }
          }
        }
      ]
    }
    """
    name: str = Field(..., description="Artifactの名前")
    artifactId: str = Field(..., description="Artifact ID")
    parts: List[A2AArtifactPart] = Field(..., description="Artifactのパートリスト")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "Cart Mandate for Order",
                "artifactId": "artifact_cart_123",
                "parts": [
                    {
                        "kind": "data",
                        "data": {
                            "ap2.mandates.CartMandate": {
                                "id": "cart_abc123",
                                "merchant_id": "did:ap2:merchant:mugibo_merchant",
                                "items": [],
                                "total": {"value": "10000.00", "currency": "JPY"}
                            }
                        }
                    }
                ]
            }
        }


class A2ADataPart(BaseModel):
    """
    A2A DataPart

    AP2/A2A仕様準拠:
    - 通常のメッセージペイロード: type + id + payload
    - Artifact参照: kind="artifact" + artifact

    {
      "@type": "ap2/IntentMandate",
      "id": "intent-123",
      "payload": { ... }
    }

    または

    {
      "kind": "artifact",
      "artifact": { ...A2AArtifact... }
    }
    """
    # 通常のメッセージペイロード（kind指定なし）
    type: Optional[Literal[
        "ap2.mandates.IntentMandate",
        "ap2.mandates.CartMandate",
        "ap2.requests.CartRequest",
        "ap2.responses.CartMandatePending",
        "ap2.responses.CartCandidates",
        "ap2.mandates.PaymentMandate",
        "ap2.responses.PaymentResult",
        "ap2.requests.ProductSearch",
        "ap2.responses.ProductList",
        "ap2.requests.SignatureRequest",
        "ap2.responses.SignatureResponse",
        "ap2.consents.UserConsent",
        "ap2.errors.Error",
        "ap2.responses.Acknowledgement"
    ]] = Field(None, alias="@type", description="データタイプ（AP2仕様準拠）")
    id: Optional[str] = Field(None, description="データID")
    payload: Optional[Dict[str, Any]] = Field(None, description="各タイプ固有のペイロード")

    # Artifact参照（kind="artifact"の場合）
    kind: Optional[Literal["artifact"]] = Field(None, description="データの種類（artifact等）")
    artifact: Optional[A2AArtifact] = Field(None, description="Artifactオブジェクト（kind=artifactの場合）")

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
    { "type": "step_up_redirect", "step_up_url": "...", "session_id": "...", "content": "追加認証が必要です" }
    """
    type: Literal[
        "agent_text",
        "agent_thinking",  # LLMの思考過程（JSON出力など）
        "agent_thinking_complete",  # LLM思考完了通知
        "agent_text_chunk",  # エージェント応答のストリーミングチャンク
        "agent_text_complete",  # エージェント応答完了通知
        "signature_request",
        "cart_options",
        "shipping_form_request",
        "payment_method_selection",
        "credential_provider_selection",
        "webauthn_request",
        "stepup_authentication_request",  # AP2完全準拠: 3D Secure 2.0認証リクエスト
        "step_up_redirect",
        "payment_completed",  # AP2完全準拠: 決済完了通知
        "error",
        "done"
    ]
    content: Optional[str | Dict[str, Any]] = None  # AP2: stepup_authentication_requestはDict
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

    # Step-up認証用フィールド
    step_up_url: Optional[str] = None
    session_id: Optional[str] = None

    # AP2完全準拠: 決済完了イベント用フィールド
    transaction_id: Optional[str] = None
    product_name: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    merchant_name: Optional[str] = None
    receipt_url: Optional[str] = None
    status: Optional[str] = None

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
    """POST /sign/cart レスポンス（AP2完全準拠）"""
    signed_cart_mandate: Dict[str, Any] = Field(..., description="署名済みCartMandate")
    merchant_signature: Signature


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

    AP2仕様準拠：
    - payment_mandate: 支払い情報（最小限のペイロード）
    - cart_mandate: カート詳細情報（領収書生成に必要）
    - credential_token: 認証トークン（オプショナル）
    """
    payment_mandate: Dict[str, Any]
    cart_mandate: Dict[str, Any]  # 領収書生成に必要
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


# ========================================
# Passkey認証用モデル（AP2仕様準拠）
# ========================================

class UserCreate(BaseModel):
    """
    ユーザー登録リクエスト（メール/パスワード認証）

    AP2仕様準拠:
    - email: payer_emailとして使用（リファレンス実装: bugsbunny@gmail.com）
    - username: 表示名
    - password: bcryptでハッシュ化して保存

    AP2仕様: HTTPセッション認証方式は仕様外（実装の自由度あり）
    Mandate署名はCredential ProviderのPasskeyで実施（AP2準拠）
    """
    username: str = Field(..., min_length=3, max_length=50, description="ユーザー名（3-50文字）")
    email: str = Field(..., description="メールアドレス（AP2 payer_emailとして使用）")
    password: str = Field(..., min_length=8, description="パスワード（8文字以上）")

    class Config:
        json_schema_extra = {
            "example": {
                "username": "bugsbunny",
                "email": "bugsbunny@gmail.com",
                "password": "securepassword123"
            }
        }


class UserLogin(BaseModel):
    """
    ユーザーログインリクエスト（メール/パスワード認証）

    AP2仕様: HTTPセッション認証方式は仕様外（実装の自由度あり）
    """
    email: str = Field(..., description="メールアドレス")
    password: str = Field(..., description="パスワード")

    class Config:
        json_schema_extra = {
            "example": {
                "email": "bugsbunny@gmail.com",
                "password": "securepassword123"
            }
        }


class UserInDB(BaseModel):
    """
    データベース内のユーザー情報

    AP2仕様準拠:
    - email: PaymentMandate.payer_emailとして使用
    - id: 内部識別子（UUID）
    - hashed_password: bcryptハッシュ（メール/パスワード認証用）
    """
    id: str = Field(..., description="ユーザーID（UUID）")
    username: str = Field(..., description="ユーザー名")
    email: str = Field(..., description="メールアドレス（AP2 payer_email）")
    hashed_password: str = Field(..., description="bcryptハッシュ化パスワード")
    created_at: datetime = Field(..., description="作成日時")
    is_active: bool = Field(default=True, description="アカウント有効フラグ")


class UserResponse(BaseModel):
    """ユーザー情報レスポンス"""
    id: str
    username: str
    email: str
    created_at: datetime
    is_active: bool

    class Config:
        json_schema_extra = {
            "example": {
                "id": "usr_abc123",
                "username": "bugsbunny",
                "email": "bugsbunny@gmail.com",
                "created_at": "2025-10-24T10:00:00Z",
                "is_active": True
            }
        }


class PasskeyCredential(BaseModel):
    """
    Passkey認証情報（WebAuthn Credential）

    WebAuthn/FIDO2仕様準拠:
    - credential_id: 認証器が生成した一意のID
    - public_key: COSE形式の公開鍵
    - sign_count: リプレイ攻撃検出用カウンター
    """
    id: str = Field(..., description="Credential ID（プライマリキー）")
    user_id: str = Field(..., description="ユーザーID（外部キー）")
    credential_id: str = Field(..., description="WebAuthn credential ID（Base64URL）")
    public_key: str = Field(..., description="COSE形式公開鍵（Base64URL）")
    sign_count: int = Field(default=0, description="署名カウンター（リプレイ攻撃検出）")
    transports: List[str] = Field(default_factory=list, description="トランスポート（usb, nfc, ble, internal）")
    created_at: datetime = Field(..., description="作成日時")
    last_used_at: Optional[datetime] = Field(None, description="最終使用日時")


class PasskeyRegistrationChallenge(BaseModel):
    """Passkey登録用チャレンジリクエスト"""
    username: str
    email: str


class PasskeyRegistrationChallengeResponse(BaseModel):
    """Passkey登録用チャレンジレスポンス"""
    challenge: str = Field(..., description="Base64URL encoded challenge")
    user_id: str = Field(..., description="User ID")
    rp_id: str = Field(..., description="Relying Party ID（例: localhost）")
    rp_name: str = Field(default="AP2 Demo", description="Relying Party名")
    timeout: int = Field(default=60000, description="タイムアウト（ミリ秒）")

    class Config:
        json_schema_extra = {
            "example": {
                "challenge": "Y2hhbGxlbmdl...",
                "user_id": "usr_abc123",
                "rp_id": "localhost",
                "rp_name": "AP2 Demo",
                "timeout": 60000
            }
        }


class PasskeyRegistrationRequest(BaseModel):
    """Passkey登録リクエスト（WebAuthn Registration Response）"""
    username: str
    email: str
    credential_id: str = Field(..., description="Base64URL encoded credential ID")
    public_key: str = Field(..., description="Base64URL encoded COSE public key")
    attestation_object: str = Field(..., description="Base64URL encoded attestation object")
    client_data_json: str = Field(..., description="Base64URL encoded client data JSON")
    transports: Optional[List[str]] = Field(default=None, description="Authenticator transports")


class PasskeyLoginChallenge(BaseModel):
    """Passkeyログイン用チャレンジリクエスト"""
    email: str = Field(..., description="メールアドレス")


class PasskeyLoginChallengeResponse(BaseModel):
    """Passkeyログイン用チャレンジレスポンス"""
    challenge: str = Field(..., description="Base64URL encoded challenge")
    rp_id: str = Field(..., description="Relying Party ID")
    timeout: int = Field(default=60000, description="タイムアウト（ミリ秒）")
    allowed_credentials: List[Dict[str, Any]] = Field(..., description="許可されたcredential IDリスト")


class PasskeyLoginRequest(BaseModel):
    """Passkeyログインリクエスト（WebAuthn Authentication Response）"""
    email: str
    credential_id: str = Field(..., description="Base64URL encoded credential ID")
    authenticator_data: str = Field(..., description="Base64URL encoded authenticator data")
    client_data_json: str = Field(..., description="Base64URL encoded client data JSON")
    signature: str = Field(..., description="Base64URL encoded signature")
    user_handle: Optional[str] = Field(None, description="Base64URL encoded user handle")


class Token(BaseModel):
    """JWT認証トークン"""
    access_token: str = Field(..., description="JWTアクセストークン")
    token_type: str = Field(default="bearer", description="トークンタイプ（常にbearer）")
    user: UserResponse = Field(..., description="ユーザー情報")

    class Config:
        json_schema_extra = {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user": {
                    "id": "usr_abc123",
                    "username": "bugsbunny",
                    "email": "bugsbunny@gmail.com",
                    "created_at": "2025-10-24T10:00:00Z",
                    "is_active": True
                }
            }
        }


class TokenData(BaseModel):
    """JWTペイロードデータ"""
    user_id: Optional[str] = Field(None, description="ユーザーID")
    email: Optional[str] = Field(None, description="メールアドレス（AP2 payer_email）")


# ========================================
# エクスポート（AP2型定義を含む）
# ========================================

__all__ = [
    # A2A Message Models
    "A2AProof",

    # Cryptographic Models
    "Signature",
    "AttestationType",

    # W3C Payment Request API型（11型）
    "ContactAddress",
    "PaymentCurrencyAmount",
    "PaymentItem",
    "PaymentShippingOption",
    "PaymentOptions",
    "PaymentMethodData",
    "PaymentDetailsModifier",
    "PaymentDetailsInit",
    "PaymentRequest",
    "PaymentResponse",

    # AP2 Mandate型（5型）
    "IntentMandate",
    "CartContents",
    "CartMandate",
    "PaymentMandateContents",
    "PaymentMandate",

    # JWT生成・検証ユーティリティは循環インポート回避のため、
    # 直接 common.jwt_utils からインポートしてください
    # "compute_canonical_hash",
    # "MerchantAuthorizationJWT",
    # "UserAuthorizationSDJWT",
]
