"""
AP2 Protocol - Python型定義
Agent Payments Protocolの基本的なデータモデル
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Literal
from datetime import datetime
from enum import Enum


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
    """金額"""
    value: str  # 数値を文字列で表現（精度保証のため）
    currency: str  # ISO 4217通貨コード（例: "USD", "JPY"）

    def __str__(self) -> str:
        return f"{self.currency} {self.value}"


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
# Intent Mandate（意図マンデート）
# ========================================

@dataclass
class IntentConstraints:
    """Intent Mandateの制約条件"""
    valid_until: str  # ISO 8601形式
    max_amount: Optional[Amount] = None
    categories: Optional[List[str]] = None
    merchants: Optional[List[str]] = None
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


# ========================================
# Payment Mandate（支払いマンデート）
# ========================================

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
    risk_score: Optional[int] = None
    fraud_indicators: Optional[List[str]] = None
    user_signature: Optional[Signature] = None
    merchant_signature: Optional[Signature] = None


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
