# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""W3C Payment Request API型定義 (AP2プロトコル準拠)

このモジュールは、W3C Payment Request APIの型定義を提供します。
AP2プロトコルは、これらの標準型を利用してCart Mandateなどを構成します。

参照仕様:
- W3C Payment Request API: https://www.w3.org/TR/payment-request/
- W3C Contact Picker API: https://www.w3.org/TR/contact-picker/
- AP2公式実装: refs/AP2-main/src/ap2/types/payment_request.py
"""

from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

# Data keys for serialization
PAYMENT_METHOD_DATA_DATA_KEY = "payment_request.PaymentMethodData"
CONTACT_ADDRESS_DATA_KEY = "contact_picker.ContactAddress"


class ContactAddress(BaseModel):
    """物理的な住所を表すインターフェース (W3C Contact Picker API)

    仕様:
    https://www.w3.org/TR/contact-picker/#contact-address
    """

    city: Optional[str] = None
    country: Optional[str] = None
    dependent_locality: Optional[str] = None
    organization: Optional[str] = None
    phone_number: Optional[str] = None
    postal_code: Optional[str] = None
    recipient: Optional[str] = None
    region: Optional[str] = None
    sorting_code: Optional[str] = None
    address_line: Optional[list[str]] = None


class PaymentCurrencyAmount(BaseModel):
    """金額と通貨コードを表す型

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentcurrencyamount
    """

    currency: str = Field(
        ..., description="3文字のISO 4217通貨コード（例: USD, JPY）"
    )
    value: float = Field(..., description="金額")


class PaymentItem(BaseModel):
    """購入アイテムとその金額

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentitem
    """

    label: str = Field(
        ..., description="アイテムの人間が読める説明"
    )
    amount: PaymentCurrencyAmount = Field(
        ..., description="アイテムの金額"
    )
    pending: Optional[bool] = Field(
        None, description="Trueの場合、金額が確定していないことを示す"
    )
    refund_period: int = Field(
        30, description="このアイテムの返金可能期間（日数）"
    )


class PaymentShippingOption(BaseModel):
    """配送オプションの説明

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentshippingoption
    """

    id: str = Field(
        ..., description="配送オプションの一意な識別子"
    )
    label: str = Field(
        ..., description="配送オプションの人間が読める説明"
    )
    amount: PaymentCurrencyAmount = Field(
        ..., description="この配送オプションのコスト"
    )
    selected: Optional[bool] = Field(
        False, description="Trueの場合、デフォルトオプションとして示す"
    )


class PaymentOptions(BaseModel):
    """支払いリクエストの適格な支払いオプション情報

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentoptions
    """

    request_payer_name: Optional[bool] = Field(
        False, description="支払者の名前を収集するかどうか"
    )
    request_payer_email: Optional[bool] = Field(
        False, description="支払者のメールアドレスを収集するかどうか"
    )
    request_payer_phone: Optional[bool] = Field(
        False, description="支払者の電話番号を収集するかどうか"
    )
    request_shipping: Optional[bool] = Field(
        True, description="支払者の配送先住所を収集するかどうか"
    )
    shipping_type: Optional[str] = Field(
        None, description="配送タイプ: 'shipping', 'delivery', 'pickup' のいずれか"
    )


class PaymentMethodData(BaseModel):
    """支払い方法とその方法固有のデータを示す

    例:
    - カードは使用時に処理手数料がかかる場合がある
    - ロイヤルティカードは購入時に割引を提供する場合がある

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentmethoddata
    """

    supported_methods: str = Field(
        ..., description="支払い方法を識別する文字列"
    )
    data: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="支払い方法固有の詳細"
    )


class PaymentDetailsModifier(BaseModel):
    """支払い方法に基づいて支払い詳細を変更する修飾子

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentdetailsmodifier
    """

    supported_methods: str = Field(
        ..., description="この修飾子が適用される支払い方法ID"
    )
    total: Optional[PaymentItem] = Field(
        None, description="元の合計金額を上書きするPaymentItem"
    )
    additional_display_items: Optional[list[PaymentItem]] = Field(
        None, description="この支払い方法に適用される追加のPaymentItem"
    )
    data: Optional[dict[str, Any]] = Field(
        None, description="修飾子用の支払い方法固有のデータ"
    )


class PaymentDetailsInit(BaseModel):
    """支払いリクエストの詳細を含む

    仕様:
    https://www.w3.org/TR/payment-request/#dom-paymentdetailsinit
    """

    id: str = Field(
        ..., description="支払いリクエストの一意な識別子"
    )
    display_items: list[PaymentItem] = Field(
        ..., description="ユーザーに表示する支払いアイテムのリスト"
    )
    shipping_options: Optional[list[PaymentShippingOption]] = Field(
        None, description="利用可能な配送オプションのリスト"
    )
    modifiers: Optional[list[PaymentDetailsModifier]] = Field(
        None, description="特定の支払い方法に対する価格修飾子のリスト"
    )
    total: PaymentItem = Field(..., description="合計支払い金額")


class PaymentRequest(BaseModel):
    """支払いリクエスト

    仕様:
    https://www.w3.org/TR/payment-request/#paymentrequest-interface
    """

    method_data: list[PaymentMethodData] = Field(
        ..., description="サポートされる支払い方法のリスト"
    )
    details: PaymentDetailsInit = Field(
        ..., description="取引の財務詳細"
    )
    options: Optional[PaymentOptions] = None

    shipping_address: Optional[ContactAddress] = Field(
        None, description="ユーザーが提供した配送先住所"
    )


class PaymentResponse(BaseModel):
    """ユーザーが支払い方法を選択し、支払いリクエストを承認したことを示す

    仕様:
    https://www.w3.org/TR/payment-request/#paymentresponse-interface
    """

    request_id: str = Field(
        ..., description="元のPaymentRequestからの一意なID"
    )
    method_name: str = Field(
        ..., description="ユーザーが選択した支払い方法"
    )
    details: Optional[Dict[str, Any]] = Field(
        None,
        description=(
            "マーチャントが取引処理に使用できる、支払い方法によって生成された辞書。"
            "内容は支払い方法に依存します。"
        ),
    )
    shipping_address: Optional[ContactAddress] = None
    shipping_option: Optional[PaymentShippingOption] = None
    payer_name: Optional[str] = None
    payer_email: Optional[str] = None
    payer_phone: Optional[str] = None
