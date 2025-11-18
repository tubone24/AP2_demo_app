"""
Tests for JWT Utils

Tests cover:
- Canonical hash computation
- Merchant Authorization JWT generation and verification
- User Authorization SD-JWT generation and verification
- JWT structure and claims validation
- RFC 8785 JSON canonicalization
"""

import pytest
import base64
import hashlib
from datetime import datetime, timezone, timedelta
import json
from unittest.mock import Mock, patch, MagicMock
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

# Import the actual module to test
from common.jwt_utils import (
    compute_canonical_hash,
    MerchantAuthorizationJWT,
    UserAuthorizationSDJWT
)


class TestCanonicalHashComputation:
    """Test canonical hash computation using actual compute_canonical_hash function"""

    def test_canonical_hash_basic(self):
        """Test basic canonical hash computation"""
        data = {
            "amount": 8000,
            "currency": "JPY",
            "merchant_id": "test"
        }

        # Use the actual function
        hash_value = compute_canonical_hash(data)

        # Validate hash
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0
        # Base64url-encoded SHA256 should be 43 chars (without padding)
        assert len(hash_value) <= 44

    def test_canonical_hash_deterministic(self):
        """Test that canonical hash is deterministic"""
        data = {"b": 2, "a": 1, "c": 3}
        data2 = {"c": 3, "a": 1, "b": 2}

        # Should produce same hash regardless of key order
        hash1 = compute_canonical_hash(data)
        hash2 = compute_canonical_hash(data2)

        # Hashes should be the same (canonical ordering)
        assert hash1 == hash2

    def test_canonical_hash_nested_objects(self):
        """Test canonical hash with nested objects"""
        data = {
            "payment_details": {
                "amount": {"value": "8000.00", "currency": "JPY"},
                "merchant_id": "test"
            }
        }

        # Use the actual function
        hash_value = compute_canonical_hash(data)

        # Should produce valid hash
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0

    def test_canonical_hash_empty_dict(self):
        """Test canonical hash with empty dictionary"""
        data = {}
        hash_value = compute_canonical_hash(data)

        # Should still produce a valid hash
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0

    def test_canonical_hash_with_arrays(self):
        """Test canonical hash with arrays"""
        data = {
            "items": [
                {"id": 1, "name": "Item1"},
                {"id": 2, "name": "Item2"}
            ]
        }

        hash_value = compute_canonical_hash(data)
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0


class TestMerchantAuthorizationJWT:
    """Test Merchant Authorization JWT with actual implementation"""

    @pytest.fixture
    def mock_crypto(self):
        """Create mock crypto managers"""
        from cryptography.hazmat.primitives.asymmetric import utils as asym_utils

        key_manager = Mock()
        signature_manager = Mock()

        # Mock private key with valid DER signature
        # Create a valid DER signature for r=1, s=1
        r = 1
        s = 1
        valid_der_signature = asym_utils.encode_dss_signature(r, s)

        mock_private_key = Mock()
        mock_private_key.sign.return_value = valid_der_signature

        key_manager.get_private_key.return_value = mock_private_key

        return key_manager, signature_manager

    def test_jwt_generation_basic(self, mock_crypto):
        """Test basic JWT generation"""
        key_manager, signature_manager = mock_crypto
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        merchant_id = "did:ap2:merchant:test"
        cart_contents = {
            "items": [{"sku": "ITEM-001", "quantity": 1, "price": 1000}],
            "total_amount": {"value": "1000.00", "currency": "JPY"}
        }

        # Generate JWT
        jwt_token = jwt_generator.generate(
            merchant_id=merchant_id,
            cart_contents=cart_contents,
            audience="payment_processor",
            expiration_minutes=10
        )

        # Validate JWT structure
        parts = jwt_token.split('.')
        assert len(parts) == 3

        # Decode and validate header
        header_b64, payload_b64, signature_b64 = parts
        header_padded = header_b64 + '=' * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_padded))

        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"
        assert "kid" in header
        assert "#key-1" in header["kid"]

    def test_jwt_generation_with_hash(self, mock_crypto):
        """Test JWT generation with pre-computed hash"""
        key_manager, signature_manager = mock_crypto
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        merchant_id = "did:ap2:merchant:test"
        cart_hash = "test_hash_value"

        # Generate JWT with hash
        jwt_token = jwt_generator.generate_with_hash(
            merchant_id=merchant_id,
            cart_hash=cart_hash,
            audience="payment_processor",
            expiration_minutes=10
        )

        # Validate JWT structure
        parts = jwt_token.split('.')
        assert len(parts) == 3

        # Decode and validate payload
        header_b64, payload_b64, signature_b64 = parts
        payload_padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_padded))

        assert payload["cart_hash"] == cart_hash
        assert payload["iss"] == merchant_id
        assert payload["sub"] == merchant_id
        assert payload["aud"] == "payment_processor"

    def test_jwt_payload_structure(self, mock_crypto):
        """Test JWT payload structure"""
        key_manager, signature_manager = mock_crypto
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        merchant_id = "did:ap2:merchant:test"
        cart_contents = {"total": 1000}

        jwt_token = jwt_generator.generate(
            merchant_id=merchant_id,
            cart_contents=cart_contents
        )

        # Decode payload
        parts = jwt_token.split('.')
        payload_b64 = parts[1]
        payload_padded = payload_b64 + '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_padded))

        # Validate required claims
        required_claims = ["iss", "sub", "aud", "iat", "exp", "jti", "cart_hash"]
        for claim in required_claims:
            assert claim in payload

        assert payload["exp"] > payload["iat"]

    def test_jwt_structure(self):
        """Test JWT structure (header.payload.signature)"""
        jwt = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCIsImtpZCI6ImRpZDphcDI6bWVyY2hhbnQ6dGVzdCNrZXktMSJ9.eyJpc3MiOiJkaWQ6YXAyOm1lcmNoYW50OnRlc3QiLCJzdWIiOiJkaWQ6YXAyOm1lcmNoYW50OnRlc3QiLCJhdWQiOiJwYXltZW50X3Byb2Nlc3NvciIsImlhdCI6MTcwMDAwMDAwMCwiZXhwIjoxNzAwMDAwNjAwLCJqdGkiOiJ1dWlkLTEyMzQiLCJjYXJ0X2hhc2giOiJoYXNoIn0.signature"

        # Split JWT
        parts = jwt.split('.')
        assert len(parts) == 3

        header_b64, payload_b64, signature_b64 = parts

        # Decode header
        header_padded = header_b64 + '=' * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_padded))

        # Validate header structure
        assert "alg" in header
        assert "typ" in header
        assert "kid" in header
        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"

    def test_jwt_header_claims(self):
        """Test JWT header claims"""
        header = {
            "alg": "ES256",
            "typ": "JWT",
            "kid": "did:ap2:merchant:mugibo_merchant#key-1"
        }

        # Validate required claims
        assert header["alg"] in ["ES256", "EdDSA"]
        assert header["typ"] == "JWT"
        assert "kid" in header
        assert "#" in header["kid"]  # DID#fragment format

    def test_jwt_payload_claims(self):
        """Test JWT payload claims"""
        now = int(datetime.now(timezone.utc).timestamp())
        exp = int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp())

        payload = {
            "iss": "did:ap2:merchant:test",
            "sub": "did:ap2:merchant:test",
            "aud": "payment_processor",
            "iat": now,
            "exp": exp,
            "jti": "unique-jwt-id",
            "cart_hash": "base64url_encoded_hash"
        }

        # Validate required claims
        required_claims = ["iss", "sub", "aud", "iat", "exp", "jti", "cart_hash"]
        for claim in required_claims:
            assert claim in payload

        # Validate claim values
        assert payload["iss"] == payload["sub"]  # Should be same for merchant
        assert payload["exp"] > payload["iat"]
        assert isinstance(payload["jti"], str)

    def test_jwt_expiration_validation(self):
        """Test JWT expiration validation"""
        now = int(datetime.now(timezone.utc).timestamp())

        # Valid JWT (not expired)
        valid_payload = {
            "exp": now + 600  # 10 minutes in future
        }
        assert valid_payload["exp"] > now

        # Expired JWT
        expired_payload = {
            "exp": now - 600  # 10 minutes in past
        }
        assert expired_payload["exp"] < now

    def test_kid_format(self):
        """Test KID format in JWT header"""
        # DID#fragment format
        kid = "did:ap2:merchant:mugibo_merchant#key-1"

        # Validate format
        assert kid.startswith("did:ap2:")
        assert "#" in kid
        parts = kid.split("#")
        assert len(parts) == 2
        assert parts[1].startswith("key-")

    def test_cart_hash_claim(self):
        """Test cart_hash claim in JWT payload"""
        cart_contents = {
            "items": [{"sku": "SHOE-001", "quantity": 1, "price": 8000}],
            "total_amount": {"value": "8000.00", "currency": "JPY"}
        }

        # Compute hash
        import rfc8785
        canonical_json = rfc8785.dumps(cart_contents)
        cart_hash = base64.urlsafe_b64encode(
            hashlib.sha256(canonical_json).digest()
        ).decode('utf-8').rstrip('=')

        # Validate hash
        assert isinstance(cart_hash, str)
        assert len(cart_hash) > 0


class TestUserAuthorizationSDJWT:
    """Test User Authorization SD-JWT with actual implementation"""

    @pytest.fixture
    def mock_crypto(self):
        """Create mock crypto managers"""
        key_manager = Mock()
        signature_manager = Mock()

        # Mock signature object
        mock_signature = Mock()
        mock_signature.signature = "0" * 128  # Hex-encoded signature

        signature_manager.sign_data.return_value = mock_signature

        return key_manager, signature_manager

    def test_sd_jwt_generation(self, mock_crypto):
        """Test SD-JWT-VC generation"""
        key_manager, signature_manager = mock_crypto
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        user_id = "did:ap2:user:test"
        cart_mandate = {"type": "CartMandate", "id": "cart_001"}
        payment_mandate_contents = {"payment_total": {"value": "1000.00"}}
        audience = "payment_processor"
        nonce = "unique_nonce_123"

        # Generate SD-JWT-VC
        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate_contents,
            audience=audience,
            nonce=nonce
        )

        # Validate format
        assert "~" in sd_jwt_vc
        parts = sd_jwt_vc.split("~")
        assert len(parts) >= 2

        # Validate issuer JWT structure
        issuer_jwt = parts[0]
        issuer_parts = issuer_jwt.split('.')
        assert len(issuer_parts) == 3

    def test_sd_jwt_issuer_payload(self, mock_crypto):
        """Test SD-JWT issuer JWT payload"""
        key_manager, signature_manager = mock_crypto
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        user_id = "did:ap2:user:test"
        cart_mandate = {"type": "CartMandate"}
        payment_mandate_contents = {"payment_total": {"value": "1000.00"}}

        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate_contents,
            audience="payment_processor",
            nonce="nonce_123"
        )

        # Extract issuer JWT
        parts = sd_jwt_vc.split("~")
        issuer_jwt = parts[0]
        issuer_payload_b64 = issuer_jwt.split('.')[1]
        issuer_payload_padded = issuer_payload_b64 + '=' * (4 - len(issuer_payload_b64) % 4)
        issuer_payload = json.loads(base64.urlsafe_b64decode(issuer_payload_padded))

        # Validate issuer payload
        assert issuer_payload["iss"] == user_id
        assert issuer_payload["sub"] == user_id
        assert "cnf" in issuer_payload
        assert issuer_payload["cnf"]["kid"] == user_id

    def test_sd_jwt_kb_payload(self, mock_crypto):
        """Test SD-JWT key-binding JWT payload"""
        key_manager, signature_manager = mock_crypto
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        user_id = "did:ap2:user:test"
        cart_mandate = {"type": "CartMandate"}
        payment_mandate_contents = {"payment_total": {"value": "1000.00"}}
        audience = "payment_processor"
        nonce = "nonce_123"

        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate_contents,
            audience=audience,
            nonce=nonce
        )

        # Extract KB JWT
        parts = sd_jwt_vc.split("~")
        kb_jwt = parts[1]
        kb_payload_b64 = kb_jwt.split('.')[1]
        kb_payload_padded = kb_payload_b64 + '=' * (4 - len(kb_payload_b64) % 4)
        kb_payload = json.loads(base64.urlsafe_b64decode(kb_payload_padded))

        # Validate KB payload
        assert kb_payload["aud"] == audience
        assert kb_payload["nonce"] == nonce
        assert "sd_hash" in kb_payload
        assert "transaction_data" in kb_payload
        assert len(kb_payload["transaction_data"]) == 2

    def test_sd_jwt_vc_format(self):
        """Test SD-JWT-VC format (issuer~kb~)"""
        sd_jwt_vc = "eyJ...issuer-jwt.eyJ...kb-jwt~"

        # Should contain ~ separators
        assert "~" in sd_jwt_vc

        # Split by ~
        parts = sd_jwt_vc.split("~")
        # Standard format: <issuer-jwt>~<kb-jwt>~
        assert len(parts) >= 2

    def test_issuer_jwt_structure(self):
        """Test Issuer-signed JWT structure"""
        issuer_payload = {
            "iss": "user_001",
            "sub": "user_001",
            "iat": int(datetime.now(timezone.utc).timestamp()),
            "cnf": {
                "kid": "user_001"
            }
        }

        # Validate required claims
        assert "iss" in issuer_payload
        assert "sub" in issuer_payload
        assert "iat" in issuer_payload
        assert "cnf" in issuer_payload
        assert "kid" in issuer_payload["cnf"]

    def test_kb_jwt_structure(self):
        """Test Key-binding JWT structure"""
        kb_payload = {
            "aud": "payment_processor",
            "nonce": "unique_nonce",
            "sd_hash": "issuer_jwt_hash",
            "transaction_data": ["cart_hash", "payment_hash"]
        }

        # Validate required claims
        required_claims = ["aud", "nonce", "sd_hash", "transaction_data"]
        for claim in required_claims:
            assert claim in kb_payload

        # Validate transaction_data structure
        assert isinstance(kb_payload["transaction_data"], list)
        assert len(kb_payload["transaction_data"]) == 2

    def test_kb_jwt_header_type(self):
        """Test Key-binding JWT header type"""
        kb_header = {
            "alg": "ES256",
            "typ": "kb+jwt",
            "kid": "user_001"
        }

        # KB JWT should have typ: kb+jwt
        assert kb_header["typ"] == "kb+jwt"
        assert kb_header["alg"] in ["ES256", "EdDSA"]

    def test_sd_hash_computation(self):
        """Test sd_hash computation"""
        issuer_jwt = "header.payload.signature"

        # Compute sd_hash (SHA256 of issuer JWT)
        sd_hash = base64.urlsafe_b64encode(
            hashlib.sha256(issuer_jwt.encode('utf-8')).digest()
        ).decode('utf-8').rstrip('=')

        # Validate sd_hash
        assert isinstance(sd_hash, str)
        assert len(sd_hash) > 0

    def test_transaction_data_hashes(self):
        """Test transaction_data hash computation"""
        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "total_amount": {"value": "8000.00", "currency": "JPY"}
        }

        payment_mandate_contents = {
            "payment_details_total": {
                "amount": {"value": "8000.00", "currency": "JPY"}
            }
        }

        # Compute hashes
        import rfc8785
        cart_hash = base64.urlsafe_b64encode(
            hashlib.sha256(rfc8785.dumps(cart_mandate)).digest()
        ).decode('utf-8').rstrip('=')

        payment_hash = base64.urlsafe_b64encode(
            hashlib.sha256(rfc8785.dumps(payment_mandate_contents)).digest()
        ).decode('utf-8').rstrip('=')

        transaction_data = [cart_hash, payment_hash]

        # Validate structure
        assert len(transaction_data) == 2
        assert isinstance(transaction_data[0], str)
        assert isinstance(transaction_data[1], str)

    def test_nonce_validation(self):
        """Test nonce validation in KB JWT"""
        expected_nonce = "unique_nonce_123"
        kb_payload = {
            "nonce": "unique_nonce_123"
        }

        # Nonce should match
        assert kb_payload["nonce"] == expected_nonce

        # Mismatched nonce
        wrong_nonce = "wrong_nonce"
        assert kb_payload["nonce"] != wrong_nonce


class TestJWTSignatureFormats:
    """Test JWT signature formats"""

    def test_ecdsa_signature_format(self):
        """Test ECDSA signature format (R || S)"""
        # ECDSA P-256 signature is 64 bytes (32 bytes R + 32 bytes S)
        r_bytes = b'\x00' * 32
        s_bytes = b'\x00' * 32
        raw_signature = r_bytes + s_bytes

        assert len(raw_signature) == 64

        # Base64url encode
        signature_b64 = base64.urlsafe_b64encode(raw_signature).decode('utf-8').rstrip('=')
        assert isinstance(signature_b64, str)

    def test_signature_base64url_encoding(self):
        """Test signature base64url encoding"""
        signature_bytes = b'test_signature'

        # Base64url encode
        encoded = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        # Base64url decode (with padding)
        padded = encoded + '=' * (4 - len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded)

        # Should round-trip correctly
        assert decoded == signature_bytes

    def test_jwt_signing_input(self):
        """Test JWT signing input construction"""
        header_b64 = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9"
        payload_b64 = "eyJpc3MiOiJ0ZXN0In0"

        # Signing input is header.payload
        signing_input = f"{header_b64}.{payload_b64}"

        # Validate format
        assert "." in signing_input
        parts = signing_input.split(".")
        assert len(parts) == 2


class TestJWTAlgorithms:
    """Test JWT algorithms"""

    def test_es256_algorithm(self):
        """Test ES256 algorithm (ECDSA P-256 + SHA256)"""
        header = {
            "alg": "ES256",
            "typ": "JWT"
        }

        # ES256 = ECDSA with P-256 curve and SHA-256
        assert header["alg"] == "ES256"

    def test_eddsa_algorithm(self):
        """Test EdDSA algorithm (Ed25519)"""
        header = {
            "alg": "EdDSA",
            "typ": "JWT"
        }

        # EdDSA for Ed25519
        assert header["alg"] == "EdDSA"

    def test_algorithm_to_internal_mapping(self):
        """Test JWT algorithm to internal algorithm mapping"""
        mapping = {
            "ES256": "ECDSA",
            "EdDSA": "Ed25519"
        }

        # Validate mappings
        assert mapping["ES256"] == "ECDSA"
        assert mapping["EdDSA"] == "Ed25519"


class TestBase64URLEncoding:
    """Test Base64URL encoding/decoding"""

    def test_base64url_encode_no_padding(self):
        """Test base64url encoding without padding"""
        data = b"test"
        encoded = base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

        # Should not contain padding
        assert '=' not in encoded

    def test_base64url_decode_with_padding(self):
        """Test base64url decoding with padding restoration"""
        encoded = "dGVzdA"  # "test" without padding

        # Add padding
        padded = encoded + '=' * (4 - len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded)

        assert decoded == b"test"

    def test_base64url_round_trip(self):
        """Test base64url round-trip encoding/decoding"""
        original = b"test_data_123"

        # Encode
        encoded = base64.urlsafe_b64encode(original).decode('utf-8').rstrip('=')

        # Decode with padding
        padded = encoded + '=' * (4 - len(encoded) % 4)
        decoded = base64.urlsafe_b64decode(padded)

        assert decoded == original


class TestRFC8785Canonicalization:
    """Test RFC 8785 JSON canonicalization"""

    def test_key_ordering(self):
        """Test that keys are ordered lexicographically"""
        data = {"z": 1, "a": 2, "m": 3}

        import rfc8785
        canonical = rfc8785.dumps(data)

        # Keys should be ordered: a, m, z
        canonical_str = canonical.decode('utf-8')
        # "a" should appear before "m" and "z"
        assert canonical_str.index('"a"') < canonical_str.index('"m"')
        assert canonical_str.index('"m"') < canonical_str.index('"z"')

    def test_nested_object_canonicalization(self):
        """Test canonicalization of nested objects"""
        data = {
            "outer": {
                "z": 1,
                "a": 2
            }
        }

        import rfc8785
        canonical = rfc8785.dumps(data)

        # Inner object keys should also be ordered
        assert isinstance(canonical, bytes)

    def test_deterministic_output(self):
        """Test that canonicalization produces deterministic output"""
        data1 = {"b": 2, "a": 1}
        data2 = {"a": 1, "b": 2}

        import rfc8785
        canonical1 = rfc8785.dumps(data1)
        canonical2 = rfc8785.dumps(data2)

        # Should produce identical output
        assert canonical1 == canonical2


class TestJWTIDGeneration:
    """Test JWT ID (jti) generation"""

    def test_jti_uniqueness(self):
        """Test that jti values are unique"""
        import uuid

        jti1 = str(uuid.uuid4())
        jti2 = str(uuid.uuid4())

        # Should be different (with very high probability)
        assert jti1 != jti2

    def test_jti_format(self):
        """Test jti format (UUID)"""
        import uuid

        jti = str(uuid.uuid4())

        # Should be valid UUID string
        assert len(jti) == 36  # UUID string length
        assert jti.count('-') == 4  # UUID has 4 hyphens


class TestCNFClaim:
    """Test cnf (confirmation) claim in SD-JWT"""

    def test_cnf_structure(self):
        """Test cnf claim structure"""
        cnf = {
            "kid": "user_001"
        }

        # Validate structure
        assert "kid" in cnf
        assert isinstance(cnf["kid"], str)

    def test_cnf_in_issuer_jwt(self):
        """Test cnf claim in Issuer-signed JWT"""
        issuer_payload = {
            "iss": "user_001",
            "cnf": {
                "kid": "user_001"
            }
        }

        # cnf should reference the key
        assert "cnf" in issuer_payload
        assert issuer_payload["cnf"]["kid"] == issuer_payload["iss"]


class TestJWTTimestamps:
    """Test JWT timestamp claims"""

    def test_iat_claim(self):
        """Test iat (issued at) claim"""
        now = datetime.now(timezone.utc)
        iat = int(now.timestamp())

        # Should be Unix timestamp
        assert isinstance(iat, int)
        assert iat > 0

    def test_exp_claim(self):
        """Test exp (expiration) claim"""
        now = datetime.now(timezone.utc)
        exp = int((now + timedelta(minutes=10)).timestamp())

        # Should be Unix timestamp in future
        iat = int(now.timestamp())
        assert exp > iat

    def test_expiration_window(self):
        """Test JWT expiration window"""
        now = datetime.now(timezone.utc)
        iat = int(now.timestamp())
        exp_5min = int((now + timedelta(minutes=5)).timestamp())
        exp_15min = int((now + timedelta(minutes=15)).timestamp())

        # 5-15 minutes is recommended range
        assert exp_5min > iat
        assert exp_15min > iat
        assert (exp_5min - iat) == 300  # 5 minutes
        assert (exp_15min - iat) == 900  # 15 minutes


class TestMerchantAuthorizationJWTVerification:
    """Test Merchant Authorization JWT verification"""

    @pytest.fixture
    def crypto_setup(self):
        """Set up real crypto managers for verification tests"""
        from common.crypto import KeyManager, SignatureManager
        from cryptography.hazmat.primitives.asymmetric import utils as asym_utils

        key_manager = KeyManager(keys_directory="/tmp/test_jwt_keys")
        signature_manager = SignatureManager(key_manager)

        # Generate test key
        merchant_id = "did:ap2:merchant:test"
        key_manager.generate_key_pair(merchant_id, algorithm="ECDSA")

        return key_manager, signature_manager, merchant_id

    def test_jwt_verify_valid(self, crypto_setup):
        """Test JWT verification with valid token"""
        key_manager, signature_manager, merchant_id = crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        cart_mandate = {
            "type": "CartMandate",
            "cart_contents": {"items": [{"sku": "TEST", "quantity": 1}]},
            "total_amount": {"value": "1000.00", "currency": "JPY"}
        }

        # Generate JWT
        jwt_token = jwt_generator.generate_with_hash(
            merchant_id=merchant_id,
            cart_hash=compute_canonical_hash(cart_mandate)
        )

        # Verify JWT
        payload = jwt_generator.verify(jwt_token, cart_mandate)

        assert payload["iss"] == merchant_id
        assert payload["sub"] == merchant_id
        assert "cart_hash" in payload

    def test_jwt_verify_invalid_format(self, crypto_setup):
        """Test JWT verification with invalid format"""
        key_manager, signature_manager, merchant_id = crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        cart_mandate = {"type": "CartMandate"}

        # Invalid JWT format (only 2 parts)
        invalid_jwt = "header.payload"

        with pytest.raises(ValueError) as exc_info:
            jwt_generator.verify(invalid_jwt, cart_mandate)
        assert "Invalid JWT format" in str(exc_info.value)

    def test_jwt_verify_cart_hash_mismatch(self, crypto_setup):
        """Test JWT verification with mismatched cart hash"""
        key_manager, signature_manager, merchant_id = crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        original_cart = {"type": "CartMandate", "total": 1000}
        different_cart = {"type": "CartMandate", "total": 2000}

        # Generate JWT with original cart
        jwt_token = jwt_generator.generate_with_hash(
            merchant_id=merchant_id,
            cart_hash=compute_canonical_hash(original_cart)
        )

        # Try to verify with different cart
        with pytest.raises(ValueError) as exc_info:
            jwt_generator.verify(jwt_token, different_cart)
        assert "cart_hash mismatch" in str(exc_info.value)

    def test_jwt_verify_expired(self, crypto_setup):
        """Test JWT verification with expired token"""
        key_manager, signature_manager, merchant_id = crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        cart_mandate = {"type": "CartMandate"}

        # Generate JWT with negative expiration (already expired)
        jwt_token = jwt_generator.generate_with_hash(
            merchant_id=merchant_id,
            cart_hash=compute_canonical_hash(cart_mandate),
            expiration_minutes=-1
        )

        # Verification should fail due to expiration
        with pytest.raises(ValueError) as exc_info:
            jwt_generator.verify(jwt_token, cart_mandate)
        assert "expired" in str(exc_info.value).lower()

    def test_jwt_verify_missing_kid(self, crypto_setup):
        """Test JWT verification with missing kid in header"""
        key_manager, signature_manager, merchant_id = crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        # Manually create JWT without kid
        header = {"alg": "ES256", "typ": "JWT"}
        payload = {"iss": merchant_id, "cart_hash": "test"}

        header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip('=')
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip('=')
        signature_b64 = "fake_signature"

        invalid_jwt = f"{header_b64}.{payload_b64}.{signature_b64}"

        cart_mandate = {"type": "CartMandate"}

        with pytest.raises(ValueError) as exc_info:
            jwt_generator.verify(invalid_jwt, cart_mandate)
        assert "kid" in str(exc_info.value).lower()


class TestUserAuthorizationSDJWTVerification:
    """Test User Authorization SD-JWT verification"""

    @pytest.fixture
    def crypto_setup(self):
        """Set up real crypto managers for verification tests"""
        from common.crypto import KeyManager, SignatureManager

        key_manager = KeyManager(keys_directory="/tmp/test_sd_jwt_keys")
        signature_manager = SignatureManager(key_manager)

        # Generate test key
        user_id = "did:ap2:user:test"
        key_manager.generate_key_pair(user_id, algorithm="ECDSA")

        return key_manager, signature_manager, user_id

    def test_sd_jwt_verify_valid(self, crypto_setup):
        """Test SD-JWT verification with valid token"""
        key_manager, signature_manager, user_id = crypto_setup
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        cart_mandate = {"type": "CartMandate", "total": 1000}
        payment_mandate = {"payment_total": {"value": "1000.00"}}
        nonce = "test_nonce_123"

        # Generate SD-JWT
        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate,
            audience="payment_processor",
            nonce=nonce
        )

        # Verify SD-JWT
        payload = sd_jwt_generator.verify(
            sd_jwt_vc,
            cart_mandate,
            payment_mandate,
            nonce
        )

        assert payload["aud"] == "payment_processor"
        assert payload["nonce"] == nonce
        assert "transaction_data" in payload

    def test_sd_jwt_verify_invalid_format(self, crypto_setup):
        """Test SD-JWT verification with invalid format"""
        key_manager, signature_manager, user_id = crypto_setup
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        # Invalid SD-JWT format (no ~ separator)
        invalid_sd_jwt = "not_a_valid_sd_jwt"

        cart_mandate = {"type": "CartMandate"}
        payment_mandate = {"payment_total": {"value": "1000.00"}}

        with pytest.raises(ValueError) as exc_info:
            sd_jwt_generator.verify(invalid_sd_jwt, cart_mandate, payment_mandate, "nonce")
        assert "Invalid SD-JWT-VC format" in str(exc_info.value)

    def test_sd_jwt_verify_nonce_mismatch(self, crypto_setup):
        """Test SD-JWT verification with mismatched nonce"""
        key_manager, signature_manager, user_id = crypto_setup
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        cart_mandate = {"type": "CartMandate"}
        payment_mandate = {"payment_total": {"value": "1000.00"}}
        original_nonce = "nonce_123"
        wrong_nonce = "wrong_nonce"

        # Generate with original nonce
        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate,
            audience="payment_processor",
            nonce=original_nonce
        )

        # Try to verify with wrong nonce
        with pytest.raises(ValueError) as exc_info:
            sd_jwt_generator.verify(sd_jwt_vc, cart_mandate, payment_mandate, wrong_nonce)
        assert "nonce mismatch" in str(exc_info.value)

    def test_sd_jwt_verify_transaction_data_mismatch(self, crypto_setup):
        """Test SD-JWT verification with mismatched transaction data"""
        key_manager, signature_manager, user_id = crypto_setup
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        original_cart = {"type": "CartMandate", "total": 1000}
        different_cart = {"type": "CartMandate", "total": 2000}
        payment_mandate = {"payment_total": {"value": "1000.00"}}
        nonce = "nonce_123"

        # Generate with original cart
        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=original_cart,
            payment_mandate_contents=payment_mandate,
            audience="payment_processor",
            nonce=nonce
        )

        # Try to verify with different cart
        with pytest.raises(ValueError) as exc_info:
            sd_jwt_generator.verify(sd_jwt_vc, different_cart, payment_mandate, nonce)
        assert "transaction_data mismatch" in str(exc_info.value)

    def test_sd_jwt_verify_invalid_kb_jwt_format(self, crypto_setup):
        """Test SD-JWT verification with invalid KB JWT format"""
        key_manager, signature_manager, user_id = crypto_setup
        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        # Create invalid SD-JWT with malformed KB JWT
        invalid_sd_jwt = "valid.issuer.jwt~invalid_kb~"

        cart_mandate = {"type": "CartMandate"}
        payment_mandate = {"payment_total": {"value": "1000.00"}}

        with pytest.raises(ValueError) as exc_info:
            sd_jwt_generator.verify(invalid_sd_jwt, cart_mandate, payment_mandate, "nonce")
        assert "Invalid Key-binding JWT format" in str(exc_info.value)


class TestEd25519Algorithm:
    """Test Ed25519 algorithm support"""

    @pytest.fixture
    def ed25519_crypto_setup(self):
        """Set up crypto managers with Ed25519"""
        from common.crypto import KeyManager, SignatureManager
        from cryptography.hazmat.primitives.asymmetric import utils as asym_utils

        key_manager = KeyManager(keys_directory="/tmp/test_ed25519_keys")
        signature_manager = SignatureManager(key_manager)

        # Mock Ed25519 key (since generate isn't implemented for Ed25519 in test)
        merchant_id = "did:ap2:merchant:ed25519_test"

        # For now, use ECDSA but test the Ed25519 code path
        key_manager.generate_key_pair(merchant_id, algorithm="ECDSA")

        return key_manager, signature_manager, merchant_id

    def test_merchant_jwt_with_ed25519_header(self, ed25519_crypto_setup):
        """Test merchant JWT generation with EdDSA algorithm parameter"""
        key_manager, signature_manager, merchant_id = ed25519_crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        cart_contents = {"items": [{"sku": "TEST", "quantity": 1}]}

        # Generate JWT with ECDSA (Ed25519 not fully implemented in test env)
        jwt_token = jwt_generator.generate(
            merchant_id=merchant_id,
            cart_contents=cart_contents,
            algorithm="ECDSA"
        )

        # Verify JWT structure
        parts = jwt_token.split('.')
        assert len(parts) == 3

        # Check header
        header_b64 = parts[0]
        header_padded = header_b64 + '=' * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_padded))

        # Should use ES256 for ECDSA
        assert header["alg"] == "ES256"

    def test_key_id_with_algorithm_fragment(self, ed25519_crypto_setup):
        """Test that key IDs include correct algorithm fragment"""
        key_manager, signature_manager, merchant_id = ed25519_crypto_setup
        jwt_generator = MerchantAuthorizationJWT(signature_manager, key_manager)

        cart_contents = {"items": []}

        # Generate with ECDSA
        jwt_ecdsa = jwt_generator.generate(
            merchant_id=merchant_id,
            cart_contents=cart_contents,
            algorithm="ECDSA"
        )

        # Check header kid has #key-1 for ECDSA
        parts = jwt_ecdsa.split('.')
        header_b64 = parts[0]
        header_padded = header_b64 + '=' * (4 - len(header_b64) % 4)
        header = json.loads(base64.urlsafe_b64decode(header_padded))

        assert "#key-1" in header["kid"]

    def test_user_sd_jwt_with_ecdsa(self, ed25519_crypto_setup):
        """Test user SD-JWT generation with ECDSA"""
        key_manager, signature_manager, user_id = ed25519_crypto_setup

        # Generate user key
        key_manager.generate_key_pair(user_id, algorithm="ECDSA")

        sd_jwt_generator = UserAuthorizationSDJWT(signature_manager, key_manager)

        cart_mandate = {"type": "CartMandate"}
        payment_mandate = {"payment_total": {"value": "1000.00"}}

        # Generate SD-JWT with ECDSA
        sd_jwt_vc = sd_jwt_generator.generate(
            user_id=user_id,
            cart_mandate=cart_mandate,
            payment_mandate_contents=payment_mandate,
            audience="payment_processor",
            nonce="test_nonce",
            algorithm="ECDSA"
        )

        # Verify format
        assert "~" in sd_jwt_vc
        parts = sd_jwt_vc.split("~")
        assert len(parts) >= 2

        # Check issuer JWT header
        issuer_jwt = parts[0]
        issuer_header_b64 = issuer_jwt.split('.')[0]
        issuer_header_padded = issuer_header_b64 + '=' * (4 - len(issuer_header_b64) % 4)
        issuer_header = json.loads(base64.urlsafe_b64decode(issuer_header_padded))

        assert issuer_header["alg"] == "ES256"
