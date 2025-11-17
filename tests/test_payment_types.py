"""
Tests for Payment Types (W3C Payment Request API)

Tests cover:
- PaymentItem model validation
- PaymentCurrencyAmount model validation
- PaymentRequest model validation
- PaymentResponse model validation
- ContactAddress model validation
"""

import pytest
from pydantic import ValidationError


class TestPaymentCurrencyAmountModel:
    """Test PaymentCurrencyAmount model validation"""

    def test_currency_amount_valid(self):
        """Test valid PaymentCurrencyAmount creation"""
        from common.payment_types import PaymentCurrencyAmount

        amount = PaymentCurrencyAmount(
            currency="JPY",
            value=8000
        )

        # Validate fields
        assert amount.currency == "JPY"
        assert amount.value == 8000

    def test_currency_code_validation(self):
        """Test currency code format"""
        from common.payment_types import PaymentCurrencyAmount

        # Valid currency codes
        valid_currencies = ["JPY", "USD", "EUR", "GBP"]
        for currency in valid_currencies:
            amount = PaymentCurrencyAmount(currency=currency, value=100)
            assert amount.currency == currency
            assert len(amount.currency) == 3  # ISO 4217 format


class TestPaymentItemModel:
    """Test PaymentItem model validation"""

    def test_payment_item_valid(self):
        """Test valid PaymentItem creation"""
        from common.payment_types import PaymentItem, PaymentCurrencyAmount

        item = PaymentItem(
            label="Running Shoes",
            amount=PaymentCurrencyAmount(currency="JPY", value=8000)
        )

        # Validate fields
        assert item.label == "Running Shoes"
        assert item.amount.currency == "JPY"
        assert item.amount.value == 8000

    def test_payment_item_with_pending(self):
        """Test PaymentItem with pending flag"""
        from common.payment_types import PaymentItem, PaymentCurrencyAmount

        item = PaymentItem(
            label="Shipping",
            amount=PaymentCurrencyAmount(currency="JPY", value=500),
            pending=True
        )

        # pending should be True
        assert item.pending is True

    def test_payment_item_default_refund_period(self):
        """Test PaymentItem default refund period"""
        from common.payment_types import PaymentItem, PaymentCurrencyAmount

        item = PaymentItem(
            label="Running Shoes",
            amount=PaymentCurrencyAmount(currency="JPY", value=8000)
        )

        # Default refund period should be 30 days
        assert item.refund_period == 30


class TestContactAddressModel:
    """Test ContactAddress model validation"""

    def test_contact_address_valid(self):
        """Test valid ContactAddress creation"""
        from common.payment_types import ContactAddress

        address = ContactAddress(
            country="JP",
            address_line=["東京都千代田区1-1-1"],
            region="東京都",
            city="千代田区",
            postal_code="100-0001",
            recipient="山田太郎",
            phone_number="+81-3-1234-5678"
        )

        # Validate fields
        assert address.country == "JP"
        assert address.city == "千代田区"
        assert address.recipient == "山田太郎"

    def test_contact_address_minimal(self):
        """Test ContactAddress with minimal fields"""
        from common.payment_types import ContactAddress

        # Only optional fields
        address = ContactAddress()

        # Should allow empty
        assert address.country is None


class TestPaymentDetailsInitModel:
    """Test PaymentDetailsInit model validation"""

    def test_payment_details_init_valid(self):
        """Test valid PaymentDetailsInit creation"""
        from common.payment_types import PaymentDetailsInit, PaymentItem, PaymentCurrencyAmount

        details = PaymentDetailsInit(
            id="details_001",
            total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            display_items=[
                PaymentItem(
                    label="Item 1",
                    amount=PaymentCurrencyAmount(currency="JPY", value=8000)
                )
            ]
        )

        # Validate fields
        assert details.id == "details_001"
        assert details.total.label == "Total"
        assert len(details.display_items) == 1

    def test_payment_details_with_shipping(self):
        """Test PaymentDetailsInit with shipping options"""
        from common.payment_types import (
            PaymentDetailsInit,
            PaymentItem,
            PaymentShippingOption,
            PaymentCurrencyAmount
        )

        shipping_option = PaymentShippingOption(
            id="shipping_001",
            label="Standard Shipping",
            amount=PaymentCurrencyAmount(currency="JPY", value=500),
            selected=True
        )

        details = PaymentDetailsInit(
            id="details_001",
            total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8500)
            ),
            display_items=[],
            shipping_options=[shipping_option]
        )

        # Validate shipping options
        assert len(details.shipping_options) == 1
        assert details.shipping_options[0].selected is True


class TestPaymentRequestModel:
    """Test PaymentRequest model validation"""

    def test_payment_request_valid(self):
        """Test valid PaymentRequest creation"""
        from common.payment_types import (
            PaymentRequest,
            PaymentDetailsInit,
            PaymentItem,
            PaymentMethodData,
            PaymentCurrencyAmount
        )

        payment_details = PaymentDetailsInit(
            id="details_001",
            total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            display_items=[]
        )

        payment_method = PaymentMethodData(
            supported_methods="card",
            data={}
        )

        payment_request = PaymentRequest(
            method_data=[payment_method],
            details=payment_details
        )

        # Validate fields
        assert len(payment_request.method_data) > 0
        assert payment_request.details.id == "details_001"

    def test_payment_request_with_options(self):
        """Test PaymentRequest with payment options"""
        from common.payment_types import (
            PaymentRequest,
            PaymentDetailsInit,
            PaymentItem,
            PaymentMethodData,
            PaymentOptions,
            PaymentCurrencyAmount
        )

        payment_details = PaymentDetailsInit(
            id="details_001",
            total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            display_items=[]
        )

        payment_options = PaymentOptions(
            request_payer_name=True,
            request_payer_email=True,
            request_payer_phone=False,
            request_shipping=False
        )

        payment_request = PaymentRequest(
            method_data=[PaymentMethodData(supported_methods="card")],
            details=payment_details,
            options=payment_options
        )

        # Validate options
        assert payment_request.options.request_payer_name is True


class TestPaymentResponseModel:
    """Test PaymentResponse model validation"""

    def test_payment_response_valid(self):
        """Test valid PaymentResponse creation"""
        from common.payment_types import PaymentResponse

        response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234", "cardholderName": "TARO YAMADA"}
        )

        # Validate fields
        assert response.request_id == "req_001"
        assert response.method_name == "card"
        assert "cardNumber" in response.details

    def test_payment_response_with_payer_info(self):
        """Test PaymentResponse with payer information"""
        from common.payment_types import PaymentResponse

        response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234"},
            payer_name="山田太郎",
            payer_email="yamada@example.com",
            payer_phone="+81-3-1234-5678"
        )

        # Validate payer info
        assert response.payer_name == "山田太郎"
        assert response.payer_email == "yamada@example.com"
        assert response.payer_phone == "+81-3-1234-5678"


class TestPaymentMethodDataModel:
    """Test PaymentMethodData model validation"""

    def test_payment_method_data_card(self):
        """Test PaymentMethodData for card payment"""
        from common.payment_types import PaymentMethodData

        method = PaymentMethodData(
            supported_methods="card",
            data={
                "supportedNetworks": ["visa", "mastercard"],
                "supportedTypes": ["credit", "debit"]
            }
        )

        # Validate fields
        assert method.supported_methods == "card"
        assert "supportedNetworks" in method.data

    def test_payment_method_data_basic_card(self):
        """Test PaymentMethodData for basic-card"""
        from common.payment_types import PaymentMethodData

        method = PaymentMethodData(
            supported_methods="basic-card",
            data={}
        )

        # Validate method
        assert method.supported_methods == "basic-card"


class TestPaymentShippingOptionModel:
    """Test PaymentShippingOption model validation"""

    def test_shipping_option_valid(self):
        """Test valid PaymentShippingOption creation"""
        from common.payment_types import PaymentShippingOption, PaymentCurrencyAmount

        option = PaymentShippingOption(
            id="shipping_001",
            label="Standard Shipping",
            amount=PaymentCurrencyAmount(currency="JPY", value=500),
            selected=True
        )

        # Validate fields
        assert option.id == "shipping_001"
        assert option.label == "Standard Shipping"
        assert option.selected is True

    def test_shipping_option_not_selected(self):
        """Test shipping option not selected by default"""
        from common.payment_types import PaymentShippingOption, PaymentCurrencyAmount

        option = PaymentShippingOption(
            id="shipping_002",
            label="Express Shipping",
            amount=PaymentCurrencyAmount(currency="JPY", value=1000)
        )

        # Default selected should be False
        assert option.selected is False


class TestPaymentOptionsModel:
    """Test PaymentOptions model validation"""

    def test_payment_options_all_true(self):
        """Test PaymentOptions with all options enabled"""
        from common.payment_types import PaymentOptions

        options = PaymentOptions(
            request_payer_name=True,
            request_payer_email=True,
            request_payer_phone=True,
            request_shipping=True,
            shipping_type="shipping"
        )

        # Validate all options
        assert options.request_payer_name is True
        assert options.request_payer_email is True
        assert options.request_payer_phone is True
        assert options.request_shipping is True

    def test_payment_options_defaults(self):
        """Test PaymentOptions default values"""
        from common.payment_types import PaymentOptions

        options = PaymentOptions()

        # Defaults
        assert options.request_payer_name is False
        assert options.request_payer_email is False
        assert options.request_payer_phone is False
        assert options.request_shipping is True  # Default is True


class TestPaymentDetailsModifierModel:
    """Test PaymentDetailsModifier model validation"""

    def test_payment_modifier_valid(self):
        """Test valid PaymentDetailsModifier creation"""
        from common.payment_types import PaymentDetailsModifier, PaymentItem, PaymentCurrencyAmount

        modifier = PaymentDetailsModifier(
            supported_methods="card",
            total=PaymentItem(
                label="Discounted Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=7200)
            ),
            additional_display_items=[
                PaymentItem(
                    label="Discount",
                    amount=PaymentCurrencyAmount(currency="JPY", value=-800)
                )
            ]
        )

        # Validate fields
        assert modifier.supported_methods == "card"
        assert modifier.total.label == "Discounted Total"
        assert len(modifier.additional_display_items) == 1


class TestRequiredFieldValidation:
    """Test required field validation"""

    def test_payment_item_requires_label_and_amount(self):
        """Test PaymentItem requires label and amount"""
        from common.payment_types import PaymentItem

        # Missing amount - should raise
        with pytest.raises(ValidationError):
            PaymentItem(label="Test Item")

    def test_payment_response_requires_fields(self):
        """Test PaymentResponse requires request_id and method_name"""
        from common.payment_types import PaymentResponse

        # Missing required fields - should raise
        with pytest.raises(ValidationError):
            PaymentResponse(request_id="req_001")
