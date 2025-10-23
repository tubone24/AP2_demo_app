"""Agent Payments Protocol (AP2) Mandate型定義

このモジュールは、AP2プロトコルの3つの主要なMandate型を定義します:
1. IntentMandate - ユーザーの購買意図
2. CartMandate - Merchantが署名したカート内容
3. PaymentMandate - ユーザー承認を含む支払い指示

参照仕様:
- AP2公式実装: refs/AP2-main/src/ap2/types/mandate.py
- AP2仕様書: refs/AP2-main/docs/specification.md
"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

from common.payment_types import PaymentItem, PaymentRequest, PaymentResponse

# Data keys for serialization
CART_MANDATE_DATA_KEY = "ap2.mandates.CartMandate"
INTENT_MANDATE_DATA_KEY = "ap2.mandates.IntentMandate"
PAYMENT_MANDATE_DATA_KEY = "ap2.mandates.PaymentMandate"


class IntentMandate(BaseModel):
    """ユーザーの購買意図を表すMandate

    Human-Presentフローでは基本フィールドのみ使用します。
    Human-Not-Presentフローでは、追加フィールドが必要になります。

    参照: refs/AP2-main/src/ap2/types/mandate.py:32-77
    """

    user_cart_confirmation_required: bool = Field(
        True,
        description=(
            "Falseの場合、エージェントは全ての購買条件が満たされた後、"
            "ユーザーに代わって購入を実行できます。"
            "Intent Mandateがユーザーによって署名されていない場合、Trueである必要があります。"
        ),
    )
    natural_language_description: str = Field(
        ...,
        description=(
            "ユーザーの意図の自然言語での説明。"
            "Shopping Agentによって生成され、ユーザーによって確認されます。"
            "ユーザーによる情報に基づいた同意を得ることが目標です。"
        ),
        examples=["ハイトップの昔ながらの赤いバスケットボールシューズ"],
    )
    merchants: Optional[list[str]] = Field(
        None,
        description=(
            "意図を満たすことが許可されているMerchantのリスト。"
            "設定されていない場合、Shopping Agentは適切な任意のMerchantと取引できます。"
        ),
    )
    skus: Optional[list[str]] = Field(
        None,
        description=(
            "特定の商品SKUのリスト。設定されていない場合、任意のSKUが許可されます。"
        ),
    )
    requires_refundability: Optional[bool] = Field(
        False,
        description="Trueの場合、アイテムは返金可能である必要があります。",
    )
    intent_expiry: str = Field(
        ...,
        description="Intent Mandateの有効期限（ISO 8601形式）",
    )


class CartContents(BaseModel):
    """カートの詳細な内容

    このオブジェクトはMerchantによって署名され、CartMandateが作成されます。

    参照: refs/AP2-main/src/ap2/types/mandate.py:79-105
    """

    id: str = Field(..., description="このカートの一意な識別子")
    user_cart_confirmation_required: bool = Field(
        ...,
        description=(
            "Trueの場合、Merchantは購入を完了する前にユーザーによるカートの確認を要求します。"
        ),
    )
    payment_request: PaymentRequest = Field(
        ...,
        description=(
            "支払いを開始するためのW3C PaymentRequestオブジェクト。"
            "購入されるアイテム、価格、およびMerchantがこのカートに対して"
            "受け入れる支払い方法のセットを含みます。"
        ),
    )
    cart_expiry: str = Field(
        ..., description="このカートの有効期限（ISO 8601形式）"
    )
    merchant_name: str = Field(..., description="Merchantの名前")


class CartMandate(BaseModel):
    """Merchantによってデジタル署名されたカート

    限られた時間、アイテムと価格の保証として機能します。

    参照: refs/AP2-main/src/ap2/types/mandate.py:107-135
    """

    contents: CartContents = Field(..., description="カートの内容")
    merchant_authorization: Optional[str] = Field(
        None,
        description=(
            """base64url-encoded JSON Web Token (JWT)で、カート内容にデジタル署名し、
            その真正性と整合性を保証します:

            1. Header: 署名アルゴリズムとKey IDを含みます
            2. Payload:
               - iss, sub, aud: Merchant（発行者）と受信者（Payment Processorなど）の識別子
               - iat, exp: トークンの作成時刻と短期間の有効期限（例: 5-15分）のタイムスタンプ
               - jti: リプレイ攻撃を防ぐためのJWTの一意な識別子
               - cart_hash: CartMandateの安全なハッシュ。CartContentsオブジェクトの
                 Canonical JSON表現から計算されます
            3. Signature: Merchantの秘密鍵で作成されたデジタル署名。
               公開鍵を持つ誰もがトークンの真正性を検証し、ペイロードが改ざん
               されていないことを確認できます。

            JWT全体がbase64urlエンコードされ、安全な送信が保証されます。
            """
        ),
        examples=["eyJhbGciOiJSUzI1NiIsImtpZCI6IjIwMjQwOTA..."],
    )


class PaymentMandateContents(BaseModel):
    """PaymentMandateのデータ内容

    参照: refs/AP2-main/src/ap2/types/mandate.py:137-163
    """

    payment_mandate_id: str = Field(
        ..., description="このPayment Mandateの一意な識別子"
    )
    payment_details_id: str = Field(
        ..., description="Payment Requestの一意な識別子"
    )
    payment_details_total: PaymentItem = Field(
        ..., description="合計支払い金額"
    )
    payment_response: PaymentResponse = Field(
        ...,
        description=(
            "ユーザーが選択した支払い方法の詳細を含むPayment Response"
        ),
    )
    merchant_agent: str = Field(..., description="Merchantの識別子")
    timestamp: str = Field(
        description="Mandateが作成された日時（ISO 8601形式）",
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
    )


class PaymentMandate(BaseModel):
    """ユーザーの支払い指示と承認を含む

    CartとIntent MandateはMerchantが注文を処理するために必要ですが、
    別途、プロトコルはAgenticトランザクションへの可視性をPaymentエコシステムに
    提供します。この目的のため、PaymentMandate（CartとIntent Mandateに紐付けられているが、
    別の情報を含む）は、標準的なトランザクション承認メッセージとともに
    Network/Issuerと共有される場合があります。
    PaymentMandateの目標は、Network/IssuerがAgenticトランザクションへの信頼を
    構築するのを支援することです。

    参照: refs/AP2-main/src/ap2/types/mandate.py:165-201
    """

    payment_mandate_contents: PaymentMandateContents = Field(
        ...,
        description="Payment Mandateのデータ内容",
    )
    user_authorization: Optional[str] = Field(
        None,
        description=(
            """
            CartMandateとPaymentMandateContentsのハッシュに署名する
            Verifiable Credential（VC）のVerifiable Presentation（VP）の
            base64url-encoded表現です。

            例: SD-JWT-VCは以下を含みます:

            - Issuer-signed JWT: 'cnf'クレームを承認
            - Key-binding JWT: 以下のクレームを含む
              * "aud": オーディエンス
              * "nonce": リプレイ攻撃対策
              * "sd_hash": Issuer-signed JWTのハッシュ
              * "transaction_data": CartMandateとPaymentMandateContentsの
                安全なハッシュを含む配列
            """
        ),
        examples=["eyJhbGciOiJFUzI1NksiLCJraWQiOiJkaWQ6ZXhhbXBsZ..."],
    )
