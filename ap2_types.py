"""
AP2 Protocol - Python型定義
Agent Payments Protocolの基本的なデータモデル
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum
from decimal import Decimal


# ========================================
# 基本型定義
# ========================================

@dataclass
class Signature:
    """暗号署名"""
    algorithm: Literal['ECDSA', 'RSA', 'Ed25519']
    value: str  # Base64エンコードされた署名
    public_key: str  # 公開鍵
    signed_at: str  # ISO 8601形式のタイムスタンプ


@dataclass
class Amount:
    """金額（精度保証のためDecimalを使用）"""
    value: str  # 数値を文字列で表現（精度保証のため）
    currency: str  # ISO 4217通貨コード（例: "USD", "JPY"）

    def __str__(self) -> str:
        return f"{self.currency} {self.value}"

    def to_decimal(self) -> Decimal:
        """
        文字列からDecimalに変換

        Returns:
            Decimal: 正確な金額表現
        """
        return Decimal(self.value)

    @staticmethod
    def from_decimal(amount: Decimal, currency: str) -> 'Amount':
        """
        DecimalからAmountを作成

        Args:
            amount: Decimal形式の金額
            currency: 通貨コード

        Returns:
            Amount: Amount オブジェクト
        """
        # Decimalを文字列に変換（精度を保つ）
        return Amount(value=str(amount), currency=currency)

    def __add__(self, other: 'Amount') -> 'Amount':
        """金額の加算"""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        result = self.to_decimal() + other.to_decimal()
        return Amount.from_decimal(result, self.currency)

    def __sub__(self, other: 'Amount') -> 'Amount':
        """金額の減算"""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        result = self.to_decimal() - other.to_decimal()
        return Amount.from_decimal(result, self.currency)

    def __mul__(self, multiplier: int | Decimal) -> 'Amount':
        """金額の乗算"""
        if isinstance(multiplier, int):
            multiplier = Decimal(multiplier)
        result = self.to_decimal() * multiplier
        return Amount.from_decimal(result, self.currency)

    def __lt__(self, other: 'Amount') -> bool:
        """金額の比較 <"""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        return self.to_decimal() < other.to_decimal()

    def __le__(self, other: 'Amount') -> bool:
        """金額の比較 <="""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        return self.to_decimal() <= other.to_decimal()

    def __gt__(self, other: 'Amount') -> bool:
        """金額の比較 >"""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        return self.to_decimal() > other.to_decimal()

    def __ge__(self, other: 'Amount') -> bool:
        """金額の比較 >="""
        if self.currency != other.currency:
            raise ValueError(f"通貨が一致しません: {self.currency} != {other.currency}")
        return self.to_decimal() >= other.to_decimal()


class AgentType(Enum):
    """エージェントタイプ"""
    SHOPPING = "shopping"
    MERCHANT = "merchant"
    CREDENTIALS_PROVIDER = "credentials_provider"
    PAYMENT_PROCESSOR = "payment_processor"


@dataclass
class AgentIdentity:
    """エージェントの識別情報"""
    id: str
    name: str
    type: AgentType
    public_key: str


# ========================================
# Risk Payload（リスクペイロード）
# ========================================

@dataclass
class RiskPayload:
    """
    Risk Payload - リスク評価に関する情報

    AP2プロトコルでは、Intent→Cart→Paymentと連鎖して渡される。
    各エンティティ（Merchant, Payment Processor, Issuer）が
    独自のリスク評価モデルに使用できる柔軟な構造。
    """
    # デバイス情報
    device_fingerprint: Optional[str] = None  # デバイスのフィンガープリント
    device_id: Optional[str] = None  # デバイス識別子
    ip_address: Optional[str] = None  # IPアドレス
    user_agent: Optional[str] = None  # ユーザーエージェント文字列
    platform: Optional[str] = None  # プラットフォーム（iOS, Android, Web等）

    # 位置情報
    geolocation: Optional[Dict[str, Any]] = None  # 位置情報（緯度経度等）

    # 行動パターン
    session_id: Optional[str] = None  # セッションID
    time_on_site: Optional[int] = None  # サイト滞在時間（秒）
    pages_viewed: Optional[int] = None  # 閲覧ページ数

    # 取引履歴
    previous_transactions: Optional[int] = None  # 過去の取引回数
    account_age_days: Optional[int] = None  # アカウント作成からの日数

    # 詐欺シグナル
    velocity_checks: Optional[Dict[str, Any]] = None  # 速度チェック結果
    anomaly_score: Optional[float] = None  # 異常スコア（0.0-1.0）

    # カスタムフィールド（各エンティティが自由に追加）
    custom_fields: Optional[Dict[str, Any]] = None


@dataclass
class AgentSignal:
    """
    Agent Signal - エージェント関与のシグナル

    A2A Extensionで定義される、AI Agent関与の詳細情報。
    """
    agent_id: str  # エージェントの一意識別子
    agent_name: str  # エージェント名
    agent_version: Optional[str] = None  # エージェントバージョン
    agent_provider: Optional[str] = None  # エージェント提供者
    model_name: Optional[str] = None  # 使用AIモデル名（例: "Gemini 2.5 Flash"）
    confidence_score: Optional[float] = None  # エージェントの信頼度スコア（0.0-1.0）
    human_oversight: bool = False  # 人間による監視の有無
    autonomous_level: Optional[Literal['fully_autonomous', 'semi_autonomous', 'human_in_loop']] = None


@dataclass
class MandateMetadata:
    """
    Mandate Metadata - Mandateのメタデータ

    Mandateの再利用・検証・監査に使用される情報。
    """
    mandate_hash: str  # Mandateのcanonical JSONのSHA-256ハッシュ
    schema_version: str  # スキーマバージョン
    issuer: str  # 発行者
    issued_at: str  # 発行日時（ISO 8601）
    previous_mandate_hash: Optional[str] = None  # 前のMandateのハッシュ（連鎖用）
    nonce: Optional[str] = None  # リプレイ攻撃防止用ノンス
    audit_trail: Optional[List[Dict[str, Any]]] = None  # 監査証跡


# ========================================
# Intent Mandate（意図マンデート）
# ========================================

@dataclass
class IntentConstraints:
    """Intent Mandateの制約条件"""
    valid_until: str  # ISO 8601形式
    max_amount: Optional[Amount] = None
    categories: Optional[List[str]] = None
    merchants: Optional[List[str]] = field(default_factory=list)  # nullではなく空配列をデフォルトに
    brands: Optional[List[str]] = None
    valid_from: Optional[str] = None
    max_transactions: Optional[int] = None


@dataclass
class IntentMandate:
    """Intent Mandate - ユーザーがエージェントに与える購入権限"""
    id: str
    type: Literal['IntentMandate']
    version: str
    user_id: str
    user_public_key: str
    intent: str  # 自然言語での意図
    constraints: IntentConstraints
    created_at: str  # ISO 8601
    expires_at: str  # ISO 8601
    user_signature: Optional[Signature] = None
    # A2A Extension拡張フィールド
    agent_signal: Optional[AgentSignal] = None  # エージェント関与シグナル
    mandate_metadata: Optional[MandateMetadata] = None  # メタデータ
    risk_payload: Optional[RiskPayload] = None  # リスク情報


# ========================================
# Cart Mandate（カートマンデート）
# ========================================

@dataclass
class CartItem:
    """カート内の商品アイテム"""
    id: str
    name: str
    description: str
    quantity: int
    unit_price: Amount
    total_price: Amount
    image_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    # AP2仕様推奨フィールド
    sku: Optional[str] = None  # Stock Keeping Unit
    category: Optional[str] = None  # 商品カテゴリー
    tax_rate: Optional[str] = None  # 税率（例: "0.10" = 10%）
    risk_payload: Optional[RiskPayload] = None  # 商品レベルのリスク情報


@dataclass
class Address:
    """住所情報"""
    street: str
    city: str
    state: str
    postal_code: str
    country: str


@dataclass
class ShippingInfo:
    """配送情報"""
    address: Address
    method: str
    cost: Amount
    estimated_delivery: Optional[str] = None  # ISO 8601


@dataclass
class CartMandate:
    """Cart Mandate - カート内容に対するユーザーの承認"""
    id: str
    type: Literal['CartMandate']
    version: str
    intent_mandate_id: str
    items: List[CartItem]
    subtotal: Amount
    tax: Amount
    shipping: ShippingInfo
    total: Amount
    merchant_id: str
    merchant_name: str
    created_at: str  # ISO 8601
    expires_at: str  # ISO 8601
    merchant_signature: Optional[Signature] = None
    user_signature: Optional[Signature] = None
    # A2A Extension拡張フィールド
    intent_mandate_hash: Optional[str] = None  # IntentMandateのSHA-256ハッシュ
    mandate_metadata: Optional[MandateMetadata] = None  # メタデータ
    risk_payload: Optional[RiskPayload] = None  # リスク情報（IntentMandateから引き継ぎ＋追加）


# ========================================
# Payment Mandate（支払いマンデート）
# ========================================

class AttestationType(Enum):
    """デバイス証明の種類"""
    BIOMETRIC = "biometric"  # 生体認証（指紋、顔認証など）
    PIN = "pin"  # PIN認証
    PASSKEY = "passkey"  # パスキー/WebAuthn
    DEVICE_BINDING = "device_binding"  # デバイスバインディング
    TRUSTED_EXECUTION = "trusted_execution"  # TEE/Secure Enclave


@dataclass
class DeviceAttestation:
    """
    Device Attestation - デバイス証明

    AP2プロトコルのステップ20-23で使用される、
    ユーザーのデバイスによる暗号学的証明。

    これにより、以下が保証される：
    - ユーザーが信頼されたデバイスで取引を承認したこと
    - デバイスが改ざんされていないこと
    - 取引がリアルタイムで行われていること（リプレイ攻撃対策）
    """
    device_id: str  # デバイスの一意識別子
    attestation_type: AttestationType  # 認証タイプ
    attestation_value: str  # 証明値（署名、トークンなど）
    timestamp: str  # ISO 8601形式のタイムスタンプ
    device_public_key: str  # デバイスの公開鍵（検証用）
    challenge: str  # チャレンジ値（リプレイ攻撃対策）
    platform: str  # プラットフォーム情報（"iOS", "Android", "Web"など）
    os_version: Optional[str] = None  # OSバージョン
    app_version: Optional[str] = None  # アプリバージョン


class PaymentMethodType(Enum):
    """支払い方法の種類"""
    CARD = "card"
    BANK_TRANSFER = "bank_transfer"
    CRYPTO = "crypto"
    DIGITAL_WALLET = "digital_wallet"


@dataclass
class CardPaymentMethod:
    """カード情報（トークン化済み）"""
    type: Literal['card']
    token: str
    last4: str
    brand: Literal['visa', 'mastercard', 'amex', 'discover']
    expiry_month: int
    expiry_year: int
    holder_name: str


@dataclass
class CryptoPaymentMethod:
    """暗号通貨支払い情報"""
    type: Literal['crypto']
    wallet_address: str
    network: Literal['ethereum', 'bitcoin', 'solana']
    currency: str  # 例: "ETH", "BTC", "USDC"


PaymentMethod = CardPaymentMethod | CryptoPaymentMethod


@dataclass
class PaymentMandate:
    """Payment Mandate - 支払いネットワークに送信される情報"""
    id: str
    type: Literal['PaymentMandate']
    version: str
    cart_mandate_id: str
    intent_mandate_id: str
    payment_method: PaymentMethod
    amount: Amount
    transaction_type: Literal['human_present', 'human_not_present']
    agent_involved: bool
    payer_id: str
    payee_id: str
    created_at: str  # ISO 8601
    expires_at: str  # ISO 8601 - Payment Mandateの有効期限
    risk_score: Optional[int] = None
    fraud_indicators: Optional[List[str]] = None
    user_signature: Optional[Signature] = None
    merchant_signature: Optional[Signature] = None
    device_attestation: Optional[DeviceAttestation] = None  # AP2ステップ20-23で追加
    # A2A Extension拡張フィールド
    cart_mandate_hash: Optional[str] = None  # CartMandateのSHA-256ハッシュ
    intent_mandate_hash: Optional[str] = None  # IntentMandateのSHA-256ハッシュ
    mandate_metadata: Optional[MandateMetadata] = None  # メタデータ
    risk_payload: Optional[RiskPayload] = None  # リスク情報（Intent→Cartから連鎖＋追加）


# ========================================
# トランザクション結果
# ========================================

class TransactionStatus(Enum):
    """トランザクションのステータス"""
    PENDING = "pending"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


@dataclass
class ReceiptData:
    """領収書データ"""
    order_id: str
    items: List[CartItem]
    total: Amount
    paid_at: str  # ISO 8601


@dataclass
class TransactionResult:
    """トランザクション結果"""
    id: str
    status: TransactionStatus
    payment_mandate_id: str
    authorized_at: Optional[str] = None  # ISO 8601
    captured_at: Optional[str] = None  # ISO 8601
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    receipt_url: Optional[str] = None
    receipt_data: Optional[ReceiptData] = None


# ========================================
# AP2プロトコル定数
# ========================================

# サポートされているプロトコルバージョン
SUPPORTED_AP2_VERSIONS = ["0.1", "0.2", "1.0"]
DEFAULT_AP2_VERSION = "0.1"


# ========================================
# バージョンネゴシエーション機能
# ========================================

def is_version_supported(version: str) -> bool:
    """
    指定されたバージョンがサポートされているか確認

    Args:
        version: チェックするバージョン文字列

    Returns:
        bool: サポートされている場合はTrue
    """
    return version in SUPPORTED_AP2_VERSIONS


def get_compatible_version(requested_version: str, available_versions: Optional[List[str]] = None) -> Optional[str]:
    """
    互換性のあるバージョンを取得

    Args:
        requested_version: リクエストされたバージョン
        available_versions: 利用可能なバージョンのリスト（Noneの場合はSUPPORTED_AP2_VERSIONSを使用）

    Returns:
        Optional[str]: 互換性のあるバージョン（見つからない場合はNone）
    """
    if available_versions is None:
        available_versions = SUPPORTED_AP2_VERSIONS

    # 完全一致を優先
    if requested_version in available_versions:
        return requested_version

    # メジャーバージョンが一致する最新バージョンを探す
    try:
        requested_major = requested_version.split('.')[0]
        compatible_versions = [
            v for v in available_versions
            if v.split('.')[0] == requested_major
        ]

        if compatible_versions:
            # バージョン番号でソート（降順）して最新を返す
            return sorted(compatible_versions, reverse=True)[0]

    except (IndexError, ValueError):
        pass

    return None


def validate_mandate_version(mandate_version: str, entity_name: str = "Entity") -> None:
    """
    Mandateのバージョンを検証

    Args:
        mandate_version: Mandateのバージョン文字列
        entity_name: エンティティ名（エラーメッセージ用）

    Raises:
        VersionError: バージョンがサポートされていない場合
    """
    if not is_version_supported(mandate_version):
        raise VersionError(
            error_code=AP2ErrorCode.UNSUPPORTED_VERSION,
            message=f"{entity_name}がサポートしていないバージョンです: {mandate_version}",
            details={
                "requested_version": mandate_version,
                "supported_versions": SUPPORTED_AP2_VERSIONS,
                "entity": entity_name
            }
        )


# ========================================
# AP2標準エラーコード
# ========================================

class AP2ErrorCode(Enum):
    """AP2プロトコル標準エラーコード"""

    # 署名関連エラー
    INVALID_SIGNATURE = "invalid_signature"
    MISSING_SIGNATURE = "missing_signature"
    SIGNATURE_VERIFICATION_FAILED = "signature_verification_failed"

    # Mandate関連エラー
    EXPIRED_INTENT = "expired_intent"
    EXPIRED_CART = "expired_cart"
    EXPIRED_PAYMENT = "expired_payment"
    INVALID_MANDATE_CHAIN = "invalid_mandate_chain"
    MANDATE_NOT_FOUND = "mandate_not_found"

    # 金額・制約関連エラー
    AMOUNT_EXCEEDED = "amount_exceeded"
    CONSTRAINT_VIOLATION = "constraint_violation"
    INVALID_AMOUNT = "invalid_amount"

    # 認証・認可エラー
    UNAUTHORIZED = "unauthorized"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"
    DEVICE_ATTESTATION_FAILED = "device_attestation_failed"

    # バージョン関連エラー
    UNSUPPORTED_VERSION = "unsupported_version"
    VERSION_MISMATCH = "version_mismatch"

    # トランザクション関連エラー
    TRANSACTION_FAILED = "transaction_failed"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    PAYMENT_METHOD_DECLINED = "payment_method_declined"

    # 一般エラー
    INVALID_REQUEST = "invalid_request"
    INTERNAL_ERROR = "internal_error"
    NETWORK_ERROR = "network_error"


class AP2Exception(Exception):
    """AP2プロトコル例外のベースクラス"""

    def __init__(
        self,
        error_code: AP2ErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ):
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{error_code.value}] {message}")

    def to_dict(self) -> Dict[str, Any]:
        """エラーを辞書形式で返す"""
        return {
            "error_code": self.error_code.value,
            "error_message": self.message,
            "details": self.details
        }


class SignatureError(AP2Exception):
    """署名関連エラー"""
    pass


class MandateError(AP2Exception):
    """Mandate関連エラー"""
    pass


class AmountError(AP2Exception):
    """金額関連エラー"""
    pass


class AuthorizationError(AP2Exception):
    """認証・認可エラー"""
    pass


class VersionError(AP2Exception):
    """バージョン関連エラー"""
    pass


class TransactionError(AP2Exception):
    """トランザクション関連エラー"""
    pass


# ========================================
# エージェント間メッセージ
# ========================================

@dataclass
class A2AMessage:
    """A2A（Agent-to-Agent）メッセージ"""
    id: str
    type: str
    from_agent: AgentIdentity
    to_agent: AgentIdentity
    timestamp: str  # ISO 8601
    payload: Any
    signature: Optional[Signature] = None


# ========================================
# A2A Extension メッセージ
# ========================================

@dataclass
class A2AExtensionHeader:
    """
    A2A Extension Message Header

    AP2プロトコルのA2A Extensionで使用されるヘッダー情報。
    メッセージの署名とメタデータを含む。
    """
    message_id: str  # メッセージID
    schema: str  # スキーマURI（例: "a2a://intentmandate", "a2a://cartmandate"）
    version: str  # プロトコルバージョン
    timestamp: str  # ISO 8601タイムスタンプ
    sender: str  # 送信者エージェントID（AgentCard URI: did:ap2:agent:id）
    recipient: str  # 受信者エージェントID（AgentCard URI: did:ap2:agent:id）
    signature: Optional[Signature] = None  # メッセージ全体の署名


@dataclass
class A2ADataPart:
    """
    A2A DataPart Structure

    A2A仕様準拠のDataPart構造。構造化データ（JSON）を含む。
    kind="data"を識別子として使用し、dataフィールドにキーと値のペアを含む。

    Example:
        {
            "kind": "data",
            "data": {
                "ap2.mandates.IntentMandate": {...},
                "risk_data": {...}
            }
        }
    """
    kind: Literal["data"] = "data"
    data: Dict[str, Any] = field(default_factory=dict)  # キーはap2.mandates.X形式


@dataclass
class A2AMessageStandard:
    """
    統一されたA2A Message構造（DataPart形式）- A2A仕様準拠

    A2A Extension仕様に準拠した標準メッセージ構造。
    すべてのMandate型（Intent/Cart/Payment）に対応。

    DataPartの"data"フィールドには以下のキーを含む：
    - "ap2.mandates.IntentMandate": IntentMandateオブジェクト
    - "ap2.mandates.CartMandate": CartMandateオブジェクト
    - "ap2.mandates.PaymentMandate": PaymentMandateオブジェクト
    - "risk_data": RiskPayloadオブジェクト（オプション）
    """
    header: A2AExtensionHeader
    dataPart: A2ADataPart


# ========================================
# 後方互換性のための旧メッセージ型（非推奨）
# これらの型は将来的に削除される予定です。
# 新しいコードではA2AMessageStandardを使用してください。
# ========================================

@dataclass
class A2AIntentMandateMessage:
    """
    A2A IntentMandate Message (a2a://intentmandate)

    AP2のA2A Extensionで定義される、IntentMandateを包装したメッセージ。
    """
    header: A2AExtensionHeader
    intent_mandate: IntentMandate
    risk_data: Optional[RiskPayload] = None  # 追加のリスクデータ


@dataclass
class A2ACartMandateMessage:
    """
    A2A CartMandate Message (a2a://cartmandate)

    AP2のA2A Extensionで定義される、CartMandateを包装したメッセージ。
    IntentMandateへの参照を含む。
    """
    header: A2AExtensionHeader
    cart_mandate: CartMandate
    intent_mandate_reference: str  # IntentMandateのID or ハッシュ
    risk_data: Optional[RiskPayload] = None  # 追加のリスクデータ


@dataclass
class A2APaymentMandateMessage:
    """
    A2A PaymentMandate Message (a2a://paymentmandate)

    AP2のA2A Extensionで定義される、PaymentMandateを包装したメッセージ。
    Cart/IntentMandateへの参照を含む。
    """
    header: A2AExtensionHeader
    payment_mandate: PaymentMandate
    cart_mandate_reference: str  # CartMandateのID or ハッシュ
    intent_mandate_reference: str  # IntentMandateのID or ハッシュ
    risk_data: Optional[RiskPayload] = None  # 追加のリスクデータ


@dataclass
class TaskRequest:
    """エージェントへのタスクリクエスト"""
    task_id: str
    intent: str
    intent_mandate: Optional[IntentMandate] = None
    context: Optional[Dict[str, Any]] = None


@dataclass
class TaskResponse:
    """エージェントからのタスクレスポンス"""
    task_id: str
    status: Literal['in_progress', 'completed', 'failed']
    result: Optional[Any] = None
    cart_mandates: Optional[List[CartMandate]] = None
    error: Optional[str] = None
