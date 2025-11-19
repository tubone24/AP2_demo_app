"""
Tests for Services Utils Helpers

Tests cover:
- signature_helpers.py (merchant)
- validation_helpers.py (merchant)
- hash_helpers.py (shopping_agent)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock


class TestSignatureHelpers:
    """Test merchant signature helpers"""

    def test_compute_cart_hash(self):
        """Test cart hash computation"""
        from services.merchant.utils.signature_helpers import SignatureHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "merchant_id": "merchant_001",
                "items": [
                    {"sku": "ITEM-001", "price": 10000}
                ]
            }
        }

        cart_hash = SignatureHelpers.compute_cart_hash(cart_mandate)

        assert isinstance(cart_hash, str)
        assert len(cart_hash) == 64  # SHA256 hex length
        # Hash should be deterministic
        assert cart_hash == SignatureHelpers.compute_cart_hash(cart_mandate)

    def test_compute_cart_hash_with_different_data(self):
        """Test that hash changes with different data"""
        from services.merchant.utils.signature_helpers import SignatureHelpers

        cart_1 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-001"}]
            }
        }

        cart_2 = {
            "contents": {
                "id": "cart_456",
                "items": [{"sku": "ITEM-002"}]
            }
        }

        hash_1 = SignatureHelpers.compute_cart_hash(cart_1)
        hash_2 = SignatureHelpers.compute_cart_hash(cart_2)

        # Hashes should be different for different data
        assert hash_1 != hash_2


class TestValidationHelpers:
    """Test merchant validation helpers"""

    def test_init(self):
        """Test ValidationHelpers initialization"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")
        assert validator.merchant_id == "merchant_001"

    def test_validate_cart_mandate_success(self):
        """Test successful cart mandate validation"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "cart_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            },
            "_metadata": {
                "merchant_id": "merchant_001"
            }
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_missing_contents(self):
        """Test validation fails with missing contents"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {}

        with pytest.raises(ValueError, match="CartMandate.contents is missing"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_merchant_id_mismatch(self):
        """Test validation fails with merchant ID mismatch"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
            },
            "_metadata": {
                "merchant_id": "merchant_002"  # Different merchant
            }
        }

        with pytest.raises(ValueError, match="Merchant ID mismatch"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_expired(self):
        """Test validation fails with expired cart"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        # Cart expired 1 hour ago
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "cart_expiry": expired_time
            },
            "_metadata": {
                "merchant_id": "merchant_001"
            }
        }

        with pytest.raises(ValueError, match="CartMandate has expired"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_no_merchant_id_metadata(self):
        """Test validation passes when no merchant_id in metadata"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
            },
            "_metadata": {}  # No merchant_id
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_no_expiry(self):
        """Test validation passes when no expiry"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
                # No cart_expiry
            }
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)


class TestHashHelpers:
    """Test shopping agent hash helpers"""

    def test_generate_cart_mandate_hash(self):
        """Test cart mandate hash generation"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "items": [
                    {"sku": "ITEM-001", "quantity": 2, "price": 10000}
                ]
            }
        }

        cart_hash = HashHelpers.generate_cart_mandate_hash(cart_mandate)

        assert isinstance(cart_hash, str)
        assert len(cart_hash) == 64  # SHA256 hex
        # Should be deterministic
        assert cart_hash == HashHelpers.generate_cart_mandate_hash(cart_mandate)

    def test_generate_cart_mandate_hash_consistency(self):
        """Test that cart hash is consistent across multiple calls"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "items": [
                    {"sku": "ITEM-001", "quantity": 2, "price": 10000}
                ]
            }
        }

        hash_1 = HashHelpers.generate_cart_mandate_hash(cart_mandate)
        hash_2 = HashHelpers.generate_cart_mandate_hash(cart_mandate)
        hash_3 = HashHelpers.generate_cart_mandate_hash(cart_mandate)

        # All hashes should be identical (deterministic)
        assert hash_1 == hash_2 == hash_3

    def test_generate_payment_mandate_hash(self):
        """Test payment mandate hash generation"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "10000", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        payment_hash = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        assert isinstance(payment_hash, str)
        assert len(payment_hash) == 64  # SHA256 hex
        # Should be deterministic
        assert payment_hash == HashHelpers.generate_payment_mandate_hash(payment_mandate)

    def test_generate_payment_mandate_hash_excludes_user_authorization(self):
        """Test that user_authorization field is excluded from payment hash"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000", "currency": "JPY"}
                }
            }
        }

        hash_before = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        # Add user_authorization (should be excluded)
        payment_mandate["user_authorization"] = {
            "transaction_data": ["cart_hash", "payment_hash"]
        }

        hash_after = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        # Hash should be the same (user_authorization excluded)
        assert hash_before == hash_after

    def test_cart_hash_changes_with_content(self):
        """Test that cart hash changes when content changes"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate_1 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-001", "price": 10000}]
            }
        }

        cart_mandate_2 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-002", "price": 20000}]  # Different item
            }
        }

        hash_1 = HashHelpers.generate_cart_mandate_hash(cart_mandate_1)
        hash_2 = HashHelpers.generate_cart_mandate_hash(cart_mandate_2)

        # Hashes should be different
        assert hash_1 != hash_2

    def test_payment_hash_changes_with_amount(self):
        """Test that payment hash changes when amount changes"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_1 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "10000", "currency": "JPY"}
                }
            }
        }

        payment_2 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "20000", "currency": "JPY"}  # Different amount
                }
            }
        }

        hash_1 = HashHelpers.generate_payment_mandate_hash(payment_1)
        hash_2 = HashHelpers.generate_payment_mandate_hash(payment_2)

        # Hashes should be different
        assert hash_1 != hash_2
