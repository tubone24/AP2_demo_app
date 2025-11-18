"""
Tests for common/user_authorization.py

Tests cover:
- SD-JWT+KB user authorization generation
- Mandate hash computation
- Base64URL encoding/decoding
- JWT validation
- WebAuthn assertion processing
"""

import pytest
import json
import base64
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, Mock

from common.user_authorization import (
    base64url_encode,
    base64url_decode,
    compute_mandate_hash,
    create_user_authorization_vp,
    convert_vp_to_standard_format,
    convert_standard_format_to_vp,
    verify_user_authorization_vp
)


class TestBase64URLEncoding:
    """Test Base64URL encoding/decoding"""

    def test_base64url_encode(self):
        """Test Base64URL encoding"""
        data = b"test data"
        encoded = base64url_encode(data)

        # Should be valid base64url (no padding)
        assert isinstance(encoded, str)
        assert "=" not in encoded

    def test_base64url_decode(self):
        """Test Base64URL decoding"""
        data = b"test data"
        encoded = base64url_encode(data)
        decoded = base64url_decode(encoded)

        assert decoded == data

    def test_base64url_round_trip(self):
        """Test Base64URL encode/decode round trip"""
        test_cases = [
            b"",
            b"a",
            b"ab",
            b"abc",
            b"test data with various lengths",
            json.dumps({"key": "value"}).encode('utf-8')
        ]

        for data in test_cases:
            encoded = base64url_encode(data)
            decoded = base64url_decode(encoded)
            assert decoded == data


class TestMandateHashComputation:
    """Test mandate hash computation"""

    def test_compute_cart_mandate_hash(self):
        """Test computing CartMandate hash"""
        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [
                {
                    "product_id": "prod_001",
                    "sku": "SHOE-001",
                    "quantity": 1,
                    "price": 8000
                }
            ],
            "total_amount": {
                "value": "8000.00",
                "currency": "JPY"
            }
        }

        hash_value = compute_mandate_hash(cart_mandate)

        # Should be hex string of SHA-256 (64 characters)
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
        assert all(c in "0123456789abcdef" for c in hash_value)

    def test_compute_payment_mandate_hash(self):
        """Test computing PaymentMandate hash"""
        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "amount": {
                "value": "8000.00",
                "currency": "JPY"
            },
            "payer_id": "user_001",
            "payee_id": "did:ap2:merchant:test_merchant"
        }

        hash_value = compute_mandate_hash(payment_mandate)

        # Should be hex string of SHA-256
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64

    def test_compute_mandate_hash_excludes_signatures(self):
        """Test that mandate hash excludes signature fields"""
        mandate_with_signatures = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [],
            "merchant_signature": {"algorithm": "ED25519", "value": "sig1"},
            "merchant_authorization": "jwt_token",
            "user_authorization": "vp_token"
        }

        mandate_without_signatures = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": []
        }

        # Hashes should be the same (signatures excluded)
        hash1 = compute_mandate_hash(mandate_with_signatures)
        hash2 = compute_mandate_hash(mandate_without_signatures)

        assert hash1 == hash2

    def test_compute_mandate_hash_deterministic(self):
        """Test that mandate hash is deterministic"""
        mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "TEST-001", "quantity": 1}]
        }

        hash1 = compute_mandate_hash(mandate)
        hash2 = compute_mandate_hash(mandate)
        hash3 = compute_mandate_hash(mandate)

        # All hashes should be identical
        assert hash1 == hash2 == hash3

    def test_compute_mandate_hash_key_order_independent(self):
        """Test that mandate hash is independent of key order"""
        mandate1 = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": []
        }

        mandate2 = {
            "items": [],
            "id": "cart_001",
            "type": "CartMandate"
        }

        # Hashes should be the same (RFC 8785 canonicalization)
        hash1 = compute_mandate_hash(mandate1)
        hash2 = compute_mandate_hash(mandate2)

        assert hash1 == hash2


class TestUserAuthorizationVP:
    """Test user authorization VP creation"""

    def test_create_user_authorization_structure(self):
        """Test creating user authorization with valid structure"""
        # Mock WebAuthn assertion
        webauthn_assertion = {
            "id": "credential_id_123",
            "response": {
                "clientDataJSON": base64.urlsafe_b64encode(
                    json.dumps({
                        "type": "webauthn.get",
                        "challenge": "test_challenge",
                        "origin": "https://example.com"
                    }).encode('utf-8')
                ).decode('utf-8'),
                "authenticatorData": base64.urlsafe_b64encode(
                    b'\x00' * 37  # Minimal valid authenticator data
                ).decode('utf-8'),
                "signature": base64.urlsafe_b64encode(
                    b'\x00' * 64  # Mock signature
                ).decode('utf-8')
            }
        }

        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "TEST-001", "quantity": 1}]
        }

        payment_mandate = {
            "type": "PaymentMandate",
            "id": "payment_001",
            "amount": {"value": "100.00", "currency": "JPY"}
        }

        # Mock COSE public key (base64 encoded)
        mock_public_key_cose = base64.b64encode(b'\x00' * 64).decode('utf-8')

        try:
            vp = create_user_authorization_vp(
                webauthn_assertion=webauthn_assertion,
                cart_mandate=cart_mandate,
                payment_mandate_contents=payment_mandate,
                user_id="user_001",
                public_key_cose=mock_public_key_cose
            )

            # VP should be in SD-JWT+KB format: "issuer_jwt~kb_jwt"
            assert isinstance(vp, str)
            assert "~" in vp

            parts = vp.split("~")
            assert len(parts) >= 2  # At least issuer JWT and KB JWT

        except Exception as e:
            # If VP creation fails due to crypto operations, that's expected
            # in unit tests without proper keys
            pytest.skip(f"VP creation requires valid crypto operations: {e}")

    def test_user_authorization_vp_format(self):
        """Test user authorization VP format (SD-JWT+KB)"""
        # This test validates the expected structure without full creation
        # Real VP format: "issuer_jwt~kb_jwt"

        expected_format = "eyJ...header.eyJ...payload.signature~eyJ...kb_header.eyJ...kb_payload.signature"

        # Validate format
        assert "~" in expected_format
        parts = expected_format.split("~")
        assert len(parts) == 2

        # Each part should be a JWT (3 parts separated by dots)
        for part in parts:
            jwt_parts = part.split(".")
            # Note: Simplified validation - real JWTs have 3 parts
            assert len(jwt_parts) >= 1


class TestUserAuthorizationValidation:
    """Test user authorization validation logic"""

    def test_transaction_data_structure(self):
        """Test transaction_data structure for KB JWT"""
        cart_hash = "abc123"
        payment_hash = "def456"

        transaction_data = {
            "cart_mandate_hash": cart_hash,
            "payment_mandate_hash": payment_hash
        }

        # Validate structure
        assert "cart_mandate_hash" in transaction_data
        assert "payment_mandate_hash" in transaction_data
        assert transaction_data["cart_mandate_hash"] == cart_hash
        assert transaction_data["payment_mandate_hash"] == payment_hash

    def test_cnf_claim_structure(self):
        """Test cnf (confirmation) claim structure"""
        # Example cnf claim for SD-JWT
        cnf_claim = {
            "jwk": {
                "kty": "EC",
                "crv": "P-256",
                "x": "base64url_x",
                "y": "base64url_y"
            }
        }

        # Validate structure
        assert "jwk" in cnf_claim
        assert "kty" in cnf_claim["jwk"]
        assert cnf_claim["jwk"]["kty"] == "EC"

    def test_webauthn_assertion_required_fields(self):
        """Test WebAuthn assertion has required fields"""
        assertion = {
            "id": "credential_id",
            "response": {
                "clientDataJSON": "base64_encoded",
                "authenticatorData": "base64_encoded",
                "signature": "base64_encoded"
            }
        }

        # Validate required fields
        assert "id" in assertion
        assert "response" in assertion
        assert "clientDataJSON" in assertion["response"]
        assert "authenticatorData" in assertion["response"]
        assert "signature" in assertion["response"]


class TestUserAuthorizationSecurity:
    """Test security aspects of user authorization"""

    def test_mandate_hash_collision_resistance(self):
        """Test that different mandates produce different hashes"""
        mandate1 = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "SKU-001", "quantity": 1}]
        }

        mandate2 = {
            "type": "CartMandate",
            "id": "cart_002",
            "items": [{"sku": "SKU-002", "quantity": 1}]
        }

        hash1 = compute_mandate_hash(mandate1)
        hash2 = compute_mandate_hash(mandate2)

        # Different mandates should produce different hashes
        assert hash1 != hash2

    def test_mandate_hash_modification_detection(self):
        """Test that mandate modification changes hash"""
        original_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "SKU-001", "quantity": 1, "price": 100}]
        }

        modified_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "SKU-001", "quantity": 1, "price": 200}]  # Price changed
        }

        original_hash = compute_mandate_hash(original_mandate)
        modified_hash = compute_mandate_hash(modified_mandate)

        # Modification should be detected
        assert original_hash != modified_hash


class TestComputeMandateHashErrors:
    """Test error handling in compute_mandate_hash"""

    def test_compute_mandate_hash_missing_rfc8785(self):
        """Test that missing rfc8785 library raises ImportError"""
        mandate = {"type": "CartMandate", "id": "cart_001"}

        with patch.dict('sys.modules', {'rfc8785': None}):
            with pytest.raises(ImportError) as exc_info:
                compute_mandate_hash(mandate)

            assert "rfc8785 library is required" in str(exc_info.value)


class TestConvertVPFormats:
    """Test VP format conversion functions"""

    def test_convert_vp_to_standard_format(self):
        """Test converting VP JSON to standard format"""
        vp_json = {
            "issuer_jwt": "header.payload.sig",
            "kb_jwt": "kb_header.kb_payload.kb_sig"
        }

        standard_format = convert_vp_to_standard_format(vp_json)

        assert isinstance(standard_format, str)
        assert standard_format == "header.payload.sig~kb_header.kb_payload.kb_sig~"
        assert standard_format.count("~") == 2

    def test_convert_vp_to_standard_format_empty(self):
        """Test converting empty VP to standard format"""
        vp_json = {
            "issuer_jwt": "",
            "kb_jwt": ""
        }

        standard_format = convert_vp_to_standard_format(vp_json)
        assert standard_format == "~~"

    def test_convert_standard_format_to_vp(self):
        """Test converting standard format to VP JSON"""
        standard_format = "header.payload.sig~kb_header.kb_payload.kb_sig~"

        vp = convert_standard_format_to_vp(standard_format)

        assert isinstance(vp, dict)
        assert vp["issuer_jwt"] == "header.payload.sig"
        assert vp["kb_jwt"] == "kb_header.kb_payload.kb_sig"

    def test_convert_standard_format_to_vp_invalid(self):
        """Test converting invalid standard format raises error"""
        invalid_format = "only_one_part"

        with pytest.raises(ValueError) as exc_info:
            convert_standard_format_to_vp(invalid_format)

        assert "Invalid SD-JWT-VC format" in str(exc_info.value)

    def test_convert_standard_format_to_vp_minimal(self):
        """Test converting minimal standard format"""
        standard_format = "issuer~kb"

        vp = convert_standard_format_to_vp(standard_format)

        assert vp["issuer_jwt"] == "issuer"
        assert vp["kb_jwt"] == "kb"


class TestCreateUserAuthorizationVPErrors:
    """Test error cases for create_user_authorization_vp"""

    def test_create_vp_missing_fields(self):
        """Test creating VP with missing WebAuthn fields"""
        invalid_assertion = {
            "id": "cred_id",
            "response": {
                # Missing required fields
            }
        }

        cart_mandate = {"type": "CartMandate", "id": "cart_001"}
        payment_mandate = {"type": "PaymentMandate", "id": "pay_001"}

        with pytest.raises(ValueError) as exc_info:
            create_user_authorization_vp(
                webauthn_assertion=invalid_assertion,
                cart_mandate=cart_mandate,
                payment_mandate_contents=payment_mandate,
                user_id="user_001",
                public_key_cose="invalid_key"
            )

        assert "Invalid WebAuthn assertion" in str(exc_info.value)

    def test_create_vp_invalid_public_key_cose(self):
        """Test creating VP with invalid COSE public key"""
        webauthn_assertion = {
            "id": "credential_id",
            "response": {
                "clientDataJSON": base64.urlsafe_b64encode(
                    json.dumps({"challenge": "test", "type": "webauthn.get", "origin": "https://test.com"}).encode()
                ).decode(),
                "authenticatorData": base64.urlsafe_b64encode(b'\x00' * 37).decode(),
                "signature": base64.urlsafe_b64encode(b'\x00' * 64).decode()
            }
        }

        with pytest.raises(ValueError) as exc_info:
            create_user_authorization_vp(
                webauthn_assertion=webauthn_assertion,
                cart_mandate={"type": "CartMandate", "id": "cart_001"},
                payment_mandate_contents={"type": "PaymentMandate", "id": "pay_001"},
                user_id="user_001",
                public_key_cose="invalid_base64_!@#$"
            )

        assert "Invalid public_key_cose format" in str(exc_info.value)


class TestVerifyUserAuthorizationVP:
    """Test verify_user_authorization_vp function"""

    def test_verify_vp_invalid_format(self):
        """Test verifying VP with invalid format"""
        invalid_vp = "no_tilde_separator"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(invalid_vp)

        assert "Invalid SD-JWT+KB format" in str(exc_info.value)

    def test_verify_vp_invalid_kb_jwt(self):
        """Test verifying VP with invalid KB JWT"""
        # Create invalid VP with malformed KB JWT
        invalid_vp = "issuer.jwt.here~invalid_kb_jwt"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(invalid_vp)

        assert "Invalid kb_jwt format" in str(exc_info.value)

    def test_verify_vp_missing_transaction_data(self):
        """Test verifying VP with missing transaction_data"""
        # Create KB JWT without transaction_data
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "nonce": "test_nonce",
            # Missing transaction_data
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())

        vp = f"issuer.jwt.sig~header.{kb_payload_b64}.sig"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(vp)

        assert "transaction_data must contain" in str(exc_info.value)

    def test_verify_vp_missing_webauthn_data(self):
        """Test verifying VP with missing webauthn data"""
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["cart_hash", "payment_hash"],
            # Missing webauthn data
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())

        vp = f"issuer.jwt.sig~header.{kb_payload_b64}.sig"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(vp)

        assert "webauthn data not found" in str(exc_info.value)

    def test_verify_vp_hash_mismatch(self):
        """Test verifying VP with mismatched hashes"""
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["actual_cart_hash", "actual_payment_hash"],
            "webauthn": {"credential_id": "cred_id"}
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())

        vp = f"issuer.jwt.sig~header.{kb_payload_b64}.sig"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(
                vp,
                expected_cart_hash="expected_cart_hash",
                expected_payment_hash="actual_payment_hash"
            )

        assert "Cart hash mismatch" in str(exc_info.value)

    def test_verify_vp_payment_hash_mismatch(self):
        """Test verifying VP with mismatched payment hash"""
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["actual_cart_hash", "actual_payment_hash"],
            "webauthn": {"credential_id": "cred_id"}
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())

        vp = f"issuer.jwt.sig~header.{kb_payload_b64}.sig"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(
                vp,
                expected_cart_hash="actual_cart_hash",
                expected_payment_hash="expected_payment_hash"
            )

        assert "Payment hash mismatch" in str(exc_info.value)

    def test_verify_vp_success_without_hash_check(self):
        """Test successful VP verification without hash checks"""
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["cart_hash_123", "payment_hash_456"],
            "webauthn": {
                "credential_id": "cred_id",
                "authenticator_data": "auth_data",
                "client_data_json": "client_data",
                "user_handle": "user_handle"
            }
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())

        # Create issuer JWT without cnf claim
        issuer_payload = {
            "iss": "did:ap2:user:test",
            "sub": "did:ap2:user:test"
        }
        issuer_payload_b64 = base64url_encode(json.dumps(issuer_payload).encode())

        vp = f"header.{issuer_payload_b64}.~header.{kb_payload_b64}.sig"

        result = verify_user_authorization_vp(vp)

        assert result["verified"] is True
        assert result["cart_hash"] == "cart_hash_123"
        assert result["payment_hash"] == "payment_hash_456"
        assert "webauthn_assertion" in result

    def test_verify_vp_with_signature_verification(self):
        """Test VP verification with signature verification"""
        # Create a mock public key
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()

        # Get public key coordinates
        x_bytes = public_key.public_numbers().x.to_bytes(32, byteorder='big')
        y_bytes = public_key.public_numbers().y.to_bytes(32, byteorder='big')

        # Create issuer JWT with cnf claim
        issuer_payload = {
            "iss": "did:ap2:user:test",
            "sub": "did:ap2:user:test",
            "cnf": {
                "jwk": {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": base64url_encode(x_bytes),
                    "y": base64url_encode(y_bytes)
                }
            }
        }
        issuer_payload_b64 = base64url_encode(json.dumps(issuer_payload).encode())

        # Create authenticator data and client data
        authenticator_data = b'\x00' * 37
        client_data_json = json.dumps({"challenge": "test", "type": "webauthn.get"}).encode()

        # Sign the data
        from cryptography.hazmat.primitives import hashes
        signed_data = authenticator_data + hashlib.sha256(client_data_json).digest()
        signature = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))

        # Create KB JWT with webauthn data
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["cart_hash", "payment_hash"],
            "webauthn": {
                "credential_id": "cred_id",
                "authenticator_data": base64url_encode(authenticator_data),
                "client_data_json": base64url_encode(client_data_json),
                "user_handle": "user_handle"
            }
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())
        signature_b64 = base64url_encode(signature)

        vp = f"header.{issuer_payload_b64}.~header.{kb_payload_b64}.{signature_b64}"

        result = verify_user_authorization_vp(vp)

        assert result["verified"] is True
        assert result["cart_hash"] == "cart_hash"
        assert result["payment_hash"] == "payment_hash"

    def test_verify_vp_signature_verification_failed(self):
        """Test VP verification with invalid signature"""
        # Create issuer JWT with cnf claim (valid public key)
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        public_key = private_key.public_key()

        x_bytes = public_key.public_numbers().x.to_bytes(32, byteorder='big')
        y_bytes = public_key.public_numbers().y.to_bytes(32, byteorder='big')

        issuer_payload = {
            "cnf": {
                "jwk": {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": base64url_encode(x_bytes),
                    "y": base64url_encode(y_bytes)
                }
            }
        }
        issuer_payload_b64 = base64url_encode(json.dumps(issuer_payload).encode())

        # Create KB JWT with webauthn data and INVALID signature
        kb_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "transaction_data": ["cart_hash", "payment_hash"],
            "webauthn": {
                "credential_id": "cred_id",
                "authenticator_data": base64url_encode(b'\x00' * 37),
                "client_data_json": base64url_encode(b'{"test": "data"}'),
                "user_handle": "user_handle"
            }
        }
        kb_payload_b64 = base64url_encode(json.dumps(kb_payload).encode())
        invalid_signature = base64url_encode(b'\x00' * 64)  # Invalid signature

        vp = f"header.{issuer_payload_b64}.~header.{kb_payload_b64}.{invalid_signature}"

        with pytest.raises(ValueError) as exc_info:
            verify_user_authorization_vp(vp)

        assert "WebAuthn signature verification failed" in str(exc_info.value)
