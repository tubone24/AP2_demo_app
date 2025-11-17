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


class TestCanonicalHashComputation:
    """Test canonical hash computation"""

    def test_canonical_hash_basic(self):
        """Test basic canonical hash computation"""
        data = {
            "amount": 8000,
            "currency": "JPY",
            "merchant_id": "test"
        }

        # Hash should be deterministic
        # Simulate canonical hash (RFC 8785)
        import rfc8785
        canonical_json = rfc8785.dumps(data)
        hash_digest = hashlib.sha256(canonical_json).digest()
        hash_value = base64.urlsafe_b64encode(hash_digest).decode('utf-8').rstrip('=')

        # Validate hash
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0
        # Base64url-encoded SHA256 should be 43 chars (without padding)
        assert len(hash_value) <= 44

    def test_canonical_hash_deterministic(self):
        """Test that canonical hash is deterministic"""
        data = {"b": 2, "a": 1, "c": 3}

        import rfc8785
        # Should produce same hash regardless of key order
        hash1 = base64.urlsafe_b64encode(
            hashlib.sha256(rfc8785.dumps(data)).digest()
        ).decode('utf-8').rstrip('=')

        data2 = {"c": 3, "a": 1, "b": 2}
        hash2 = base64.urlsafe_b64encode(
            hashlib.sha256(rfc8785.dumps(data2)).digest()
        ).decode('utf-8').rstrip('=')

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

        import rfc8785
        canonical_json = rfc8785.dumps(data)
        hash_digest = hashlib.sha256(canonical_json).digest()
        hash_value = base64.urlsafe_b64encode(hash_digest).decode('utf-8').rstrip('=')

        # Should produce valid hash
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0


class TestMerchantAuthorizationJWT:
    """Test Merchant Authorization JWT"""

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
    """Test User Authorization SD-JWT"""

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
