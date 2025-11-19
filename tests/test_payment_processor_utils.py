"""
Tests for Payment Processor Utils

Tests cover:
- jwt_helpers.py (payment_processor)
- mandate_helpers.py (payment_processor)
"""

import pytest
import base64
import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch


# ============================================================================
# Payment Processor JWT Helpers Tests
# ============================================================================


class TestJWTHelpers:
    """Test payment_processor JWT helpers"""

    def test_base64url_decode(self):
        """Test base64url decoding with padding"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        # Test data
        test_str = "Hello World"
        # Encode without padding
        encoded = base64.urlsafe_b64encode(test_str.encode()).decode().rstrip('=')

        # Decode
        decoded = JWTHelpers.base64url_decode(encoded)
        assert decoded.decode() == test_str

    def test_base64url_decode_with_padding(self):
        """Test base64url decoding when padding needed"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        # Test with different lengths requiring different padding
        test_cases = ["a", "ab", "abc", "abcd"]
        for test_str in test_cases:
            encoded = base64.urlsafe_b64encode(test_str.encode()).decode().rstrip('=')
            decoded = JWTHelpers.base64url_decode(encoded)
            assert decoded.decode() == test_str

    def test_parse_jwt_parts_success(self):
        """Test successful JWT parsing"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        key_manager = Mock()
        helpers = JWTHelpers(key_manager)

        # Create test JWT
        header = {"alg": "ES256", "typ": "JWT", "kid": "test_kid"}
        payload = {"iss": "test", "aud": "test_aud", "iat": 123, "exp": 999}

        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        signature_b64 = "fake_signature"

        jwt_string = f"{header_b64}.{payload_b64}.{signature_b64}"

        # Parse
        h, p, h_b64, p_b64, s_b64 = helpers.parse_jwt_parts(jwt_string)

        assert h["alg"] == "ES256"
        assert p["iss"] == "test"
        assert s_b64 == "fake_signature"

    def test_parse_jwt_parts_invalid_format(self):
        """Test JWT parsing with invalid format"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        key_manager = Mock()
        helpers = JWTHelpers(key_manager)

        # Invalid JWT (only 2 parts)
        with pytest.raises(ValueError, match="expected 3 parts"):
            helpers.parse_jwt_parts("part1.part2")

        # Invalid JWT (4 parts)
        with pytest.raises(ValueError, match="expected 3 parts"):
            helpers.parse_jwt_parts("part1.part2.part3.part4")

    def test_validate_jwt_header_success(self):
        """Test successful JWT header validation"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        header = {
            "alg": "ES256",
            "typ": "JWT",
            "kid": "test_kid_123"
        }

        # Should not raise
        JWTHelpers.validate_jwt_header(header)

    def test_validate_jwt_header_missing_kid(self):
        """Test JWT header validation with missing kid"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        header = {
            "alg": "ES256",
            "typ": "JWT"
            # Missing kid
        }

        with pytest.raises(ValueError, match="Missing 'kid'"):
            JWTHelpers.validate_jwt_header(header)

    def test_validate_jwt_header_wrong_algorithm(self):
        """Test JWT header validation with wrong algorithm (logs warning)"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        header = {
            "alg": "HS256",  # Wrong algorithm
            "typ": "JWT",
            "kid": "test_kid"
        }

        # Should still not raise (just warns)
        JWTHelpers.validate_jwt_header(header)

    def test_validate_jwt_payload_success(self):
        """Test successful JWT payload validation"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600  # 1 hour from now

        payload = {
            "iss": "did:ap2:user:test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "nonce": "test_nonce_123",
            "transaction_data": {
                "cart_mandate_hash": "hash1",
                "payment_mandate_hash": "hash2"
            }
        }

        # Should not raise
        JWTHelpers.validate_jwt_payload(payload)

    def test_validate_jwt_payload_missing_claim(self):
        """Test JWT payload validation with missing required claim"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        payload = {
            "iss": "test",
            "aud": "test_aud",
            # Missing iat, exp, nonce, transaction_data
        }

        with pytest.raises(ValueError, match="Missing required claim"):
            JWTHelpers.validate_jwt_payload(payload)

    def test_validate_jwt_payload_expired(self):
        """Test JWT payload validation with expired token"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        past_timestamp = int(time.time()) - 3600  # 1 hour ago

        payload = {
            "iss": "test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()) - 7200,
            "exp": past_timestamp,  # Expired
            "nonce": "test_nonce",
            "transaction_data": {
                "cart_mandate_hash": "hash1",
                "payment_mandate_hash": "hash2"
            }
        }

        with pytest.raises(ValueError, match="JWT has expired"):
            JWTHelpers.validate_jwt_payload(payload)

    def test_validate_jwt_payload_invalid_transaction_data(self):
        """Test JWT payload validation with invalid transaction_data"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600

        payload = {
            "iss": "test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "nonce": "test_nonce",
            "transaction_data": "invalid"  # Should be dict
        }

        with pytest.raises(ValueError, match="transaction_data must be a dictionary"):
            JWTHelpers.validate_jwt_payload(payload)

    def test_validate_jwt_payload_missing_transaction_field(self):
        """Test JWT payload validation with missing transaction_data field"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600

        payload = {
            "iss": "test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "nonce": "test_nonce",
            "transaction_data": {
                "cart_mandate_hash": "hash1"
                # Missing payment_mandate_hash
            }
        }

        with pytest.raises(ValueError, match="Missing required field in transaction_data"):
            JWTHelpers.validate_jwt_payload(payload)

    def test_validate_merchant_jwt_payload_success(self):
        """Test successful merchant JWT payload validation"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600

        payload = {
            "iss": "did:ap2:merchant:test",
            "sub": "did:ap2:merchant:test",  # Should match iss
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "jti": "unique_jwt_id_123",
            "cart_hash": "a" * 32  # 32 char hash
        }

        # Should not raise
        JWTHelpers.validate_merchant_jwt_payload(payload)

    def test_validate_merchant_jwt_payload_missing_claim(self):
        """Test merchant JWT payload validation with missing claim"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        payload = {
            "iss": "did:ap2:merchant:test",
            "sub": "did:ap2:merchant:test",
            # Missing other required claims
        }

        with pytest.raises(ValueError, match="Missing required claim"):
            JWTHelpers.validate_merchant_jwt_payload(payload)

    def test_validate_merchant_jwt_payload_iss_sub_differ(self):
        """Test merchant JWT payload when iss and sub differ (logs warning)"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600

        payload = {
            "iss": "did:ap2:merchant:test1",
            "sub": "did:ap2:merchant:test2",  # Different from iss
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "jti": "jti_123",
            "cart_hash": "a" * 32
        }

        # Should not raise (just warns)
        JWTHelpers.validate_merchant_jwt_payload(payload)

    def test_validate_merchant_jwt_payload_invalid_cart_hash(self):
        """Test merchant JWT payload validation with invalid cart_hash"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        future_timestamp = int(time.time()) + 3600

        payload = {
            "iss": "did:ap2:merchant:test",
            "sub": "did:ap2:merchant:test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()),
            "exp": future_timestamp,
            "jti": "jti_123",
            "cart_hash": "short"  # Too short
        }

        with pytest.raises(ValueError, match="Invalid cart_hash"):
            JWTHelpers.validate_merchant_jwt_payload(payload)

    def test_validate_merchant_jwt_payload_expired(self):
        """Test merchant JWT payload validation with expired token"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        past_timestamp = int(time.time()) - 3600

        payload = {
            "iss": "did:ap2:merchant:test",
            "sub": "did:ap2:merchant:test",
            "aud": "did:ap2:agent:payment_processor",
            "iat": int(time.time()) - 7200,
            "exp": past_timestamp,  # Expired
            "jti": "jti_123",
            "cart_hash": "a" * 32
        }

        with pytest.raises(ValueError, match="JWT has expired"):
            JWTHelpers.validate_merchant_jwt_payload(payload)

    def test_verify_jwt_signature_missing_public_key(self):
        """Test JWT signature verification when public key not found"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        key_manager = Mock()
        helpers = JWTHelpers(key_manager)

        header = {"alg": "ES256", "typ": "JWT", "kid": "nonexistent_kid"}

        with patch('common.did_resolver.DIDResolver') as MockResolver:
            mock_resolver = Mock()
            mock_resolver.resolve_public_key.return_value = None
            MockResolver.return_value = mock_resolver

            with pytest.raises(ValueError, match="Public key not found"):
                helpers.verify_jwt_signature(header, "h", "p", "s")

    def test_verify_jwt_signature_invalid_length(self):
        """Test JWT signature verification with invalid signature length"""
        from services.payment_processor.utils.jwt_helpers import JWTHelpers

        key_manager = Mock()
        helpers = JWTHelpers(key_manager)

        header = {"alg": "ES256", "typ": "JWT", "kid": "test_kid"}

        # Create fake signature with wrong length (not 64 bytes)
        fake_signature = base64.urlsafe_b64encode(b"short").decode().rstrip('=')

        # Create a valid EC public key for testing
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization

        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ).decode()

        with patch('common.did_resolver.DIDResolver') as MockResolver:
            mock_resolver = Mock()
            mock_resolver.resolve_public_key.return_value = public_key_pem
            MockResolver.return_value = mock_resolver

            with pytest.raises(ValueError, match="Invalid ES256 signature length"):
                helpers.verify_jwt_signature(header, "h", "p", fake_signature)


# ============================================================================
# Payment Processor Mandate Helpers Tests
# ============================================================================


class TestMandateHelpers:
    """Test payment_processor mandate helpers"""

    def test_validate_payment_mandate_success(self):
        """Test successful payment mandate validation"""
        from services.payment_processor.utils.mandate_helpers import MandateHelpers

        payment_mandate = {
            "id": "pm_123",
            "amount": {"value": "10000", "currency": "JPY"},
            "payment_method": "credit_card",
            "payer_id": "user_001",
            "payee_id": "merchant_001",
            "user_authorization": "auth_token_xyz"
        }

        # Should not raise
        MandateHelpers.validate_payment_mandate(payment_mandate)

    def test_validate_payment_mandate_missing_field(self):
        """Test payment mandate validation with missing required field"""
        from services.payment_processor.utils.mandate_helpers import MandateHelpers

        payment_mandate = {
            "id": "pm_123",
            "amount": {"value": "10000", "currency": "JPY"},
            # Missing payment_method, payer_id, payee_id, user_authorization
        }

        with pytest.raises(ValueError, match="Missing required field"):
            MandateHelpers.validate_payment_mandate(payment_mandate)

    def test_validate_payment_mandate_missing_user_authorization(self):
        """Test payment mandate validation with missing user_authorization"""
        from services.payment_processor.utils.mandate_helpers import MandateHelpers

        payment_mandate = {
            "id": "pm_123",
            "amount": {"value": "10000", "currency": "JPY"},
            "payment_method": "credit_card",
            "payer_id": "user_001",
            "payee_id": "merchant_001"
            # Missing user_authorization
        }

        with pytest.raises(ValueError, match="AP2 specification violation.*user_authorization"):
            MandateHelpers.validate_payment_mandate(payment_mandate)

    def test_validate_payment_mandate_none_user_authorization(self):
        """Test payment mandate validation when user_authorization is None"""
        from services.payment_processor.utils.mandate_helpers import MandateHelpers

        payment_mandate = {
            "id": "pm_123",
            "amount": {"value": "10000", "currency": "JPY"},
            "payment_method": "credit_card",
            "payer_id": "user_001",
            "payee_id": "merchant_001",
            "user_authorization": None  # Explicitly None
        }

        with pytest.raises(ValueError, match="AP2 specification violation.*user_authorization"):
            MandateHelpers.validate_payment_mandate(payment_mandate)

    def test_validate_payment_mandate_empty_user_authorization(self):
        """Test payment mandate validation with empty user_authorization (should pass)"""
        from services.payment_processor.utils.mandate_helpers import MandateHelpers

        payment_mandate = {
            "id": "pm_123",
            "amount": {"value": "10000", "currency": "JPY"},
            "payment_method": "credit_card",
            "payer_id": "user_001",
            "payee_id": "merchant_001",
            "user_authorization": ""  # Empty string is valid (not None)
        }

        # Should not raise (empty string is not None)
        MandateHelpers.validate_payment_mandate(payment_mandate)
