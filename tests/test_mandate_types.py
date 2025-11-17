"""
Tests for Mandate Types

Tests cover:
- IntentMandate model validation
- CartMandate model validation
- PaymentMandate model validation
- CartContents model validation
- PaymentMandateContents model validation
"""

import pytest
from pydantic import ValidationError
from datetime import datetime, timezone, timedelta


class TestIntentMandateModel:
    """Test IntentMandate model validation"""

    def test_intent_mandate_valid(self):
        """Test valid IntentMandate creation"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="ハイトップの昔ながらの赤いバスケットボールシューズ",
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Validate fields
        assert intent.user_cart_confirmation_required is True
        assert len(intent.natural_language_description) > 0

    def test_intent_mandate_with_merchants(self):
        """Test IntentMandate with merchant restrictions"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Running shoes",
            merchants=["did:ap2:merchant:nike", "did:ap2:merchant:adidas"],
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Validate merchants list
        assert intent.merchants is not None
        assert len(intent.merchants) == 2
        assert all(m.startswith("did:ap2:merchant:") for m in intent.merchants)

    def test_intent_mandate_with_skus(self):
        """Test IntentMandate with SKU restrictions"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Specific product",
            skus=["SHOE-RUN-001", "SHOE-RUN-002"],
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Validate SKUs
        assert intent.skus is not None
        assert len(intent.skus) == 2

    def test_intent_mandate_refundability(self):
        """Test IntentMandate refundability requirement"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Product with refund policy",
            requires_refundability=True,
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Validate refundability
        assert intent.requires_refundability is True

    def test_intent_mandate_expiry(self):
        """Test IntentMandate expiry validation"""
        from common.mandate_types import IntentMandate

        expiry = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Test intent",
            intent_expiry=expiry
        )

        # Validate expiry is set
        assert intent.intent_expiry == expiry


class TestCartContentsModel:
    """Test CartContents model validation"""

    def test_cart_contents_valid(self):
        """Test valid CartContents creation"""
        from common.mandate_types import CartContents
        from common.payment_types import (
            PaymentRequest, PaymentDetailsInit, PaymentItem,
            PaymentMethodData, PaymentCurrencyAmount
        )

        payment_request = PaymentRequest(
            method_data=[PaymentMethodData(supported_methods="card")],
            details=PaymentDetailsInit(
                id="details_001",
                total=PaymentItem(
                    label="Total",
                    amount=PaymentCurrencyAmount(currency="JPY", value=8000)
                ),
                display_items=[]
            )
        )

        cart_contents = CartContents(
            id="cart_001",
            user_cart_confirmation_required=True,
            payment_request=payment_request,
            cart_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            merchant_name="Test Merchant"
        )

        # Validate fields
        assert cart_contents.id == "cart_001"
        assert cart_contents.merchant_name == "Test Merchant"
        assert cart_contents.user_cart_confirmation_required is True

    def test_cart_contents_expiry(self):
        """Test CartContents expiry"""
        from common.mandate_types import CartContents
        from common.payment_types import (
            PaymentRequest, PaymentDetailsInit, PaymentItem,
            PaymentMethodData, PaymentCurrencyAmount
        )

        payment_request = PaymentRequest(
            method_data=[PaymentMethodData(supported_methods="card")],
            details=PaymentDetailsInit(
                id="details_001",
                total=PaymentItem(
                    label="Total",
                    amount=PaymentCurrencyAmount(currency="JPY", value=8000)
                ),
                display_items=[]
            )
        )

        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        cart_contents = CartContents(
            id="cart_001",
            user_cart_confirmation_required=True,
            payment_request=payment_request,
            cart_expiry=expiry,
            merchant_name="Test Merchant"
        )

        # Validate expiry
        assert cart_contents.cart_expiry == expiry


class TestCartMandateModel:
    """Test CartMandate model validation"""

    def test_cart_mandate_valid(self):
        """Test valid CartMandate creation"""
        from common.mandate_types import CartMandate, CartContents
        from common.payment_types import (
            PaymentRequest, PaymentDetailsInit, PaymentItem,
            PaymentMethodData, PaymentCurrencyAmount
        )

        payment_request = PaymentRequest(
            method_data=[PaymentMethodData(supported_methods="card")],
            details=PaymentDetailsInit(
                id="details_001",
                total=PaymentItem(
                    label="Total",
                    amount=PaymentCurrencyAmount(currency="JPY", value=8000)
                ),
                display_items=[]
            )
        )

        cart_contents = CartContents(
            id="cart_001",
            user_cart_confirmation_required=True,
            payment_request=payment_request,
            cart_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            merchant_name="Test Merchant"
        )

        cart_mandate = CartMandate(
            contents=cart_contents,
            merchant_authorization="eyJhbGciOiJSUzI1NiIsImtpZCI6IjIwMjQwOTA..."
        )

        # Validate fields
        assert cart_mandate.contents.id == "cart_001"
        assert cart_mandate.merchant_authorization is not None

    def test_cart_mandate_without_authorization(self):
        """Test CartMandate without merchant authorization (unsigned)"""
        from common.mandate_types import CartMandate, CartContents
        from common.payment_types import (
            PaymentRequest, PaymentDetailsInit, PaymentItem,
            PaymentMethodData, PaymentCurrencyAmount
        )

        payment_request = PaymentRequest(
            method_data=[PaymentMethodData(supported_methods="card")],
            details=PaymentDetailsInit(
                id="details_001",
                total=PaymentItem(
                    label="Total",
                    amount=PaymentCurrencyAmount(currency="JPY", value=8000)
                ),
                display_items=[]
            )
        )

        cart_contents = CartContents(
            id="cart_001",
            user_cart_confirmation_required=True,
            payment_request=payment_request,
            cart_expiry=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            merchant_name="Test Merchant"
        )

        # Unsigned cart mandate
        cart_mandate = CartMandate(contents=cart_contents)

        # merchant_authorization should be None
        assert cart_mandate.merchant_authorization is None


class TestPaymentMandateContentsModel:
    """Test PaymentMandateContents model validation"""

    def test_payment_mandate_contents_valid(self):
        """Test valid PaymentMandateContents creation"""
        from common.mandate_types import PaymentMandateContents
        from common.payment_types import PaymentItem, PaymentResponse, PaymentCurrencyAmount

        payment_response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234"}
        )

        payment_contents = PaymentMandateContents(
            payment_mandate_id="payment_001",
            payment_details_id="details_001",
            payment_details_total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            payment_response=payment_response,
            merchant_agent="did:ap2:merchant:test_merchant"
        )

        # Validate fields
        assert payment_contents.payment_mandate_id == "payment_001"
        assert payment_contents.payment_details_total.label == "Total"
        assert payment_contents.merchant_agent == "did:ap2:merchant:test_merchant"

    def test_payment_mandate_contents_with_timestamp(self):
        """Test PaymentMandateContents with automatic timestamp"""
        from common.mandate_types import PaymentMandateContents
        from common.payment_types import PaymentItem, PaymentResponse, PaymentCurrencyAmount

        payment_response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234"}
        )

        payment_contents = PaymentMandateContents(
            payment_mandate_id="payment_001",
            payment_details_id="details_001",
            payment_details_total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            payment_response=payment_response,
            merchant_agent="did:ap2:merchant:test_merchant"
        )

        # Validate timestamp is automatically generated
        assert payment_contents.timestamp is not None
        assert isinstance(payment_contents.timestamp, str)


class TestPaymentMandateModel:
    """Test PaymentMandate model validation"""

    def test_payment_mandate_valid(self):
        """Test valid PaymentMandate creation"""
        from common.mandate_types import PaymentMandate, PaymentMandateContents
        from common.payment_types import PaymentItem, PaymentResponse, PaymentCurrencyAmount

        payment_response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234"}
        )

        payment_contents = PaymentMandateContents(
            payment_mandate_id="payment_001",
            payment_details_id="details_001",
            payment_details_total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            payment_response=payment_response,
            merchant_agent="did:ap2:merchant:test_merchant"
        )

        payment_mandate = PaymentMandate(
            payment_mandate_contents=payment_contents,
            user_authorization="sd-jwt-vc-string"
        )

        # Validate fields
        assert payment_mandate.payment_mandate_contents.payment_mandate_id == "payment_001"
        assert payment_mandate.user_authorization is not None

    def test_payment_mandate_without_authorization(self):
        """Test PaymentMandate without user authorization"""
        from common.mandate_types import PaymentMandate, PaymentMandateContents
        from common.payment_types import PaymentItem, PaymentResponse, PaymentCurrencyAmount

        payment_response = PaymentResponse(
            request_id="req_001",
            method_name="card",
            details={"cardNumber": "****1234"}
        )

        payment_contents = PaymentMandateContents(
            payment_mandate_id="payment_001",
            payment_details_id="details_001",
            payment_details_total=PaymentItem(
                label="Total",
                amount=PaymentCurrencyAmount(currency="JPY", value=8000)
            ),
            payment_response=payment_response,
            merchant_agent="did:ap2:merchant:test_merchant"
        )

        # Without user authorization
        payment_mandate = PaymentMandate(payment_mandate_contents=payment_contents)

        # user_authorization should be None
        assert payment_mandate.user_authorization is None


class TestMandateDataKeys:
    """Test mandate data keys constants"""

    def test_data_keys_defined(self):
        """Test that data keys are properly defined"""
        from common.mandate_types import (
            CART_MANDATE_DATA_KEY,
            INTENT_MANDATE_DATA_KEY,
            PAYMENT_MANDATE_DATA_KEY
        )

        # Validate data keys
        assert CART_MANDATE_DATA_KEY == "ap2.mandates.CartMandate"
        assert INTENT_MANDATE_DATA_KEY == "ap2.mandates.IntentMandate"
        assert PAYMENT_MANDATE_DATA_KEY == "ap2.mandates.PaymentMandate"


class TestMandateFieldValidation:
    """Test mandate field validation"""

    def test_required_field_missing_raises_error(self):
        """Test that missing required fields raise ValidationError"""
        from common.mandate_types import IntentMandate

        # Missing required field 'natural_language_description'
        with pytest.raises(ValidationError):
            IntentMandate(
                user_cart_confirmation_required=True,
                intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                # 'natural_language_description' is missing
            )

    def test_all_required_fields_present(self):
        """Test that all required fields must be present"""
        from common.mandate_types import IntentMandate

        # All required fields present - should not raise
        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Test description",
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )
        assert intent.natural_language_description == "Test description"


class TestUserCartConfirmation:
    """Test user_cart_confirmation_required field"""

    def test_confirmation_required_true(self):
        """Test when cart confirmation is required"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=True,
            natural_language_description="Test",
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Should require confirmation
        assert intent.user_cart_confirmation_required is True

    def test_confirmation_required_false(self):
        """Test when cart confirmation is not required (auto-purchase)"""
        from common.mandate_types import IntentMandate

        intent = IntentMandate(
            user_cart_confirmation_required=False,
            natural_language_description="Test",
            intent_expiry=(datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
        )

        # Should allow auto-purchase
        assert intent.user_cart_confirmation_required is False
