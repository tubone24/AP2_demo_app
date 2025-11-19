"""
Tests for common/crypto.py

Tests cover:
- Key generation and management (ECDSA, Ed25519)
- Signature creation and verification
- Mandate signing and verification
- JSON canonicalization
- Secure storage encryption/decryption
- WebAuthn challenge management
- Device attestation
"""

import pytest
import json
from datetime import datetime, timezone

from common.crypto import (
    KeyManager,
    SignatureManager,
    SecureStorage,
    WebAuthnChallengeManager,
    DeviceAttestationManager,
    canonicalize_json,
    canonicalize_a2a_message,
    compute_mandate_hash,
    verify_mandate_hash,
    CryptoError
)
from common.models import Signature, AttestationType


class TestJSONCanonicalization:
    """Test JSON canonicalization functions"""

    def test_canonicalize_json_basic(self):
        """Test basic JSON canonicalization"""
        data = {"name": "Test", "age": 30, "city": "Tokyo"}
        canonical = canonicalize_json(data)

        # Should be valid JSON
        assert json.loads(canonical) == data

        # Should be deterministic
        assert canonicalize_json(data) == canonicalize_json(data)

    def test_canonicalize_json_with_exclusion(self):
        """Test JSON canonicalization with key exclusion"""
        data = {"name": "Test", "signature": "xxx", "proof": "yyy"}
        canonical = canonicalize_json(data, exclude_keys=["signature", "proof"])

        result = json.loads(canonical)
        assert "name" in result
        assert "signature" not in result
        assert "proof" not in result

    def test_canonicalize_a2a_message(self):
        """Test A2A message canonicalization"""
        message = {
            "header": {
                "message_id": "msg_001",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "proof": {"signatureValue": "xxx"}
            },
            "dataPart": {
                "type": "ap2/IntentMandate",
                "id": "intent_001",
                "payload": {}
            }
        }

        canonical = canonicalize_a2a_message(message)
        result = json.loads(canonical)

        # proof should be excluded from header
        assert "proof" not in result.get("header", {})

    def test_compute_mandate_hash(self):
        """Test mandate hash computation"""
        mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "TEST-001", "quantity": 1}]
        }

        hash_hex = compute_mandate_hash(mandate, hash_format='hex')
        hash_b64 = compute_mandate_hash(mandate, hash_format='base64')

        assert len(hash_hex) == 64  # SHA-256 hex is 64 chars
        assert len(hash_b64) > 0

        # Should be deterministic
        assert compute_mandate_hash(mandate) == compute_mandate_hash(mandate)

    def test_verify_mandate_hash(self):
        """Test mandate hash verification"""
        mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "TEST-001", "quantity": 1}]
        }

        expected_hash = compute_mandate_hash(mandate)
        assert verify_mandate_hash(mandate, expected_hash)

        # Wrong hash should fail
        assert not verify_mandate_hash(mandate, "wrong_hash")


class TestKeyManager:
    """Test KeyManager functionality"""

    def test_generate_ecdsa_key_pair(self, key_manager, test_passphrase):
        """Test ECDSA key pair generation"""
        private_key, public_key = key_manager.generate_key_pair("test_key")

        assert private_key is not None
        assert public_key is not None

        # Save and load
        key_file = key_manager.save_private_key_encrypted(
            "test_key", private_key, test_passphrase
        )
        assert key_file.endswith("test_key_private.pem")

        loaded_key = key_manager.load_private_key_encrypted(
            "test_key", test_passphrase
        )
        assert loaded_key is not None

    def test_generate_ed25519_key_pair(self, key_manager, test_passphrase):
        """Test Ed25519 key pair generation"""
        private_key, public_key = key_manager.generate_ed25519_key_pair("test_ed25519_key")

        assert private_key is not None
        assert public_key is not None

        # Save with key_id (without suffix)
        # Note: save_private_key_encrypted saves as "key_id_private.pem"
        # but load_private_key_encrypted for ED25519 looks for "key_id_ed25519_private.pem"
        # So we save with the suffix included in the key_id to match current behavior
        key_file = key_manager.save_private_key_encrypted(
            "test_ed25519_key_ed25519", private_key, test_passphrase
        )
        assert key_file.endswith("test_ed25519_key_ed25519_private.pem")

        # Load with original key_id (load will add _ed25519 suffix automatically)
        loaded_key = key_manager.load_private_key_encrypted(
            "test_ed25519_key", test_passphrase, algorithm="ED25519"
        )
        assert loaded_key is not None

    def test_get_private_key(self, key_manager):
        """Test retrieving private key from memory"""
        private_key, _ = key_manager.generate_key_pair("memory_key")

        retrieved_key = key_manager.get_private_key("memory_key")
        assert retrieved_key is not None
        assert retrieved_key == private_key

    def test_public_key_to_multibase(self, key_manager):
        """Test public key to multibase conversion"""
        _, public_key = key_manager.generate_ed25519_key_pair("multibase_test")

        multibase_str = key_manager.public_key_to_multibase(public_key)
        assert multibase_str.startswith("z")  # base58-btc prefix

        # Should be reversible
        recovered_key = key_manager.public_key_from_multibase(multibase_str)
        assert recovered_key is not None


class TestSignatureManager:
    """Test SignatureManager functionality"""

    def test_sign_and_verify_data_ed25519(self, key_manager, signature_manager):
        """Test Ed25519 signature creation and verification"""
        # Generate key pair
        key_manager.generate_ed25519_key_pair("sign_test_ed25519")

        # Test data
        data = {"message": "Hello, World!", "timestamp": "2025-11-17T00:00:00Z"}

        # Sign
        signature = signature_manager.sign_data(data, "sign_test_ed25519", algorithm="ED25519")

        assert signature.algorithm == "ED25519"
        assert len(signature.value) > 0
        assert signature.publicKeyMultibase.startswith("z")

        # Verify
        is_valid = signature_manager.verify_signature(data, signature)
        assert is_valid

    def test_sign_and_verify_data_ecdsa(self, key_manager, signature_manager):
        """Test ECDSA signature creation and verification"""
        # Generate key pair
        key_manager.generate_key_pair("sign_test_ecdsa")

        # Test data
        data = {"message": "Hello, ECDSA!", "timestamp": "2025-11-17T00:00:00Z"}

        # Sign
        signature = signature_manager.sign_data(data, "sign_test_ecdsa", algorithm="ECDSA")

        assert signature.algorithm == "ECDSA"
        assert len(signature.value) > 0

        # Verify
        is_valid = signature_manager.verify_signature(data, signature)
        assert is_valid

    def test_verify_timestamp(self, signature_manager):
        """Test timestamp verification"""
        # Current timestamp should be valid
        current_time = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        assert signature_manager.verify_timestamp(current_time)

        # Very old timestamp should fail (beyond tolerance)
        old_time = "2020-01-01T00:00:00Z"
        assert not signature_manager.verify_timestamp(old_time)

    def test_sign_and_verify_mandate(self, key_manager, signature_manager):
        """Test mandate signing and verification"""
        # Generate key
        key_manager.generate_ed25519_key_pair("mandate_sign_test")

        # Test mandate
        mandate = {
            "type": "IntentMandate",
            "id": "intent_001",
            "intent": "Buy running shoes",
            "constraints": {"max_price": 10000}
        }

        # Sign
        signature = signature_manager.sign_mandate(mandate, "mandate_sign_test")
        assert signature is not None

        # Verify
        is_valid = signature_manager.verify_mandate_signature(mandate, signature)
        assert is_valid


class TestSecureStorage:
    """Test SecureStorage functionality"""

    def test_encrypt_and_decrypt(self, secure_storage, test_passphrase):
        """Test data encryption and decryption"""
        test_data = {
            "secret": "my_secret_value",
            "api_key": "12345-abcde",
            "metadata": {"user": "test"}
        }

        # Encrypt and save
        file_path = secure_storage.encrypt_and_save(
            test_data,
            "test_secret.enc",
            test_passphrase
        )
        assert file_path.endswith("test_secret.enc")

        # Load and decrypt
        decrypted_data = secure_storage.load_and_decrypt(
            "test_secret.enc",
            test_passphrase
        )

        assert decrypted_data == test_data

    def test_decrypt_with_wrong_passphrase(self, secure_storage, test_passphrase):
        """Test decryption with wrong passphrase"""
        test_data = {"secret": "test"}

        secure_storage.encrypt_and_save(test_data, "wrong_pass.enc", test_passphrase)

        with pytest.raises(CryptoError):
            secure_storage.load_and_decrypt("wrong_pass.enc", "wrong_passphrase")


class TestWebAuthnChallengeManager:
    """Test WebAuthnChallengeManager functionality"""

    def test_generate_challenge(self, webauthn_challenge_manager):
        """Test challenge generation"""
        result = webauthn_challenge_manager.generate_challenge(
            user_id="user_001",
            context="intent_signature"
        )

        assert "challenge_id" in result
        assert "challenge" in result
        assert result["challenge_id"].startswith("ch_")
        assert len(result["challenge"]) > 0

    def test_verify_and_consume_challenge(self, webauthn_challenge_manager):
        """Test challenge verification and consumption"""
        user_id = "user_001"

        # Generate
        result = webauthn_challenge_manager.generate_challenge(user_id)
        challenge_id = result["challenge_id"]
        challenge = result["challenge"]

        # Verify and consume (should succeed once)
        assert webauthn_challenge_manager.verify_and_consume_challenge(
            challenge_id, challenge, user_id
        )

        # Second attempt should fail (already used)
        assert not webauthn_challenge_manager.verify_and_consume_challenge(
            challenge_id, challenge, user_id
        )

    def test_challenge_expiration(self, webauthn_challenge_manager):
        """Test challenge expiration"""
        # Create manager with 0-second TTL for testing
        short_ttl_manager = WebAuthnChallengeManager(challenge_ttl_seconds=0)

        result = short_ttl_manager.generate_challenge("user_001")

        # Should fail immediately due to 0 TTL
        import time
        time.sleep(0.1)  # Small delay to ensure expiration

        assert not short_ttl_manager.verify_and_consume_challenge(
            result["challenge_id"],
            result["challenge"],
            "user_001"
        )


class TestDeviceAttestationManager:
    """Test DeviceAttestationManager functionality"""

    def test_create_device_attestation(self, key_manager, device_attestation_manager):
        """Test device attestation creation"""
        # Generate device key
        key_manager.generate_key_pair("device_001")

        # Create attestation
        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_001",
            payment_mandate_id="payment_001",
            device_key_id="device_001",
            attestation_type=AttestationType.BIOMETRIC,
            platform="iOS"
        )

        assert attestation.device_id == "device_001"
        assert attestation.attestation_type == AttestationType.BIOMETRIC
        assert attestation.platform == "iOS"
        assert len(attestation.attestation_value) > 0
        assert attestation.device_public_key_multibase is not None

    def test_verify_device_attestation(self, key_manager, device_attestation_manager):
        """Test device attestation verification"""
        # Generate device key
        key_manager.generate_key_pair("device_002")

        # Create attestation
        payment_mandate_id = "payment_002"
        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_002",
            payment_mandate_id=payment_mandate_id,
            device_key_id="device_002",
            attestation_type=AttestationType.BIOMETRIC
        )

        # Verify
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation,
            payment_mandate_id,
            max_age_seconds=300
        )

        assert is_valid

    def test_verify_device_attestation_wrong_mandate_id(
        self, key_manager, device_attestation_manager
    ):
        """Test device attestation verification with wrong mandate ID"""
        key_manager.generate_key_pair("device_003")

        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_003",
            payment_mandate_id="payment_003",
            device_key_id="device_003"
        )

        # Verify with wrong mandate ID (should fail)
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation,
            "wrong_payment_id",
            max_age_seconds=300
        )

        assert not is_valid


class TestKeyManagerAdvanced:
    """Test KeyManager advanced functionality and edge cases"""

    def test_save_and_load_public_key(self, key_manager):
        """Test saving and loading public key"""
        # Generate key pair
        private_key, public_key = key_manager.generate_key_pair("public_key_test")

        # Save public key
        key_file = key_manager.save_public_key("public_key_test", public_key)
        assert key_file.endswith("public_key_test_public.pem")

        # Load public key
        loaded_public_key = key_manager.load_public_key("public_key_test")
        assert loaded_public_key is not None

        # Verify loaded key matches original
        original_pem = key_manager.public_key_to_pem(public_key)
        loaded_pem = key_manager.public_key_to_pem(loaded_public_key)
        assert original_pem == loaded_pem

    def test_load_public_key_with_did_merchant(self, key_manager):
        """Test loading public key with merchant DID format"""
        # Generate and save a key with "merchant" as key_id
        private_key, public_key = key_manager.generate_key_pair("merchant")
        key_manager.save_public_key("merchant", public_key)

        # Load with DID format
        loaded_key = key_manager.load_public_key("did:ap2:merchant:mugibo_merchant")
        assert loaded_key is not None

    def test_load_public_key_with_did_agent(self, key_manager):
        """Test loading public key with agent DID format"""
        # Generate and save a key with "shopping_agent" as key_id
        private_key, public_key = key_manager.generate_key_pair("shopping_agent")
        key_manager.save_public_key("shopping_agent", public_key)

        # Load with DID format
        loaded_key = key_manager.load_public_key("did:ap2:agent:shopping_agent#key-1")
        assert loaded_key is not None

    def test_load_public_key_with_did_cp(self, key_manager):
        """Test loading public key with CP DID format"""
        # Generate and save a key with "demo_cp" as key_id
        private_key, public_key = key_manager.generate_key_pair("demo_cp")
        key_manager.save_public_key("demo_cp", public_key)

        # Load with DID format
        loaded_key = key_manager.load_public_key("did:ap2:cp:demo_cp")
        assert loaded_key is not None

    def test_load_public_key_not_found(self, key_manager):
        """Test loading public key that doesn't exist"""
        with pytest.raises(CryptoError, match="公開鍵ファイルが見つかりません"):
            key_manager.load_public_key("nonexistent_key")

    def test_get_private_key_with_did_formats(self, key_manager):
        """Test getting private key with various DID formats"""
        # Generate keys
        key_manager.generate_key_pair("merchant")
        key_manager.generate_key_pair("shopping_agent")
        key_manager.generate_ed25519_key_pair("test_agent")

        # Test merchant DID
        merchant_key = key_manager.get_private_key("did:ap2:merchant:test_merchant")
        assert merchant_key is not None

        # Test agent DID
        agent_key = key_manager.get_private_key("did:ap2:agent:shopping_agent")
        assert agent_key is not None

        # Test Ed25519 with DID
        ed_key = key_manager.get_private_key("did:ap2:agent:test_agent", algorithm="ED25519")
        assert ed_key is not None

    def test_public_key_to_pem(self, key_manager):
        """Test public key to PEM conversion"""
        _, public_key = key_manager.generate_key_pair("pem_test")
        pem_str = key_manager.public_key_to_pem(public_key)

        assert isinstance(pem_str, str)
        assert pem_str.startswith("-----BEGIN PUBLIC KEY-----")
        assert pem_str.endswith("-----END PUBLIC KEY-----\n")

    def test_get_public_key_pem(self, key_manager):
        """Test get_public_key_pem convenience method"""
        # Generate and save key
        _, public_key = key_manager.generate_key_pair("pem_convenience_test")
        key_manager.save_public_key("pem_convenience_test", public_key)

        # Get PEM using convenience method
        pem_str = key_manager.get_public_key_pem("pem_convenience_test")

        assert isinstance(pem_str, str)
        assert pem_str.startswith("-----BEGIN PUBLIC KEY-----")

    def test_get_public_key_pem_not_found(self, key_manager):
        """Test get_public_key_pem with non-existent key"""
        with pytest.raises(CryptoError, match="公開鍵ファイルが見つかりません"):
            key_manager.get_public_key_pem("nonexistent_key")

    def test_load_private_key_file_not_found(self, key_manager, test_passphrase):
        """Test loading private key when file doesn't exist"""
        with pytest.raises(CryptoError, match="秘密鍵ファイルが見つかりません"):
            key_manager.load_private_key_encrypted("nonexistent_key", test_passphrase)

    def test_load_private_key_wrong_passphrase(self, key_manager, test_passphrase):
        """Test loading private key with wrong passphrase"""
        # Generate and save key
        private_key, _ = key_manager.generate_key_pair("wrong_pass_test")
        key_manager.save_private_key_encrypted("wrong_pass_test", private_key, test_passphrase)

        # Try to load with wrong passphrase
        with pytest.raises(CryptoError, match="パスフレーズが正しくない"):
            key_manager.load_private_key_encrypted("wrong_pass_test", "wrong_password")

    def test_public_key_to_multibase_ecdsa(self, key_manager):
        """Test ECDSA public key to multibase conversion"""
        _, public_key = key_manager.generate_key_pair("ecdsa_multibase")
        multibase_str = key_manager.public_key_to_multibase(public_key)

        # Should start with 'z' for base58btc
        assert multibase_str.startswith("z")

        # Should be reversible
        recovered_key = key_manager.public_key_from_multibase(multibase_str)
        assert recovered_key is not None

    def test_public_key_from_multibase_invalid_length_ed25519(self, key_manager):
        """Test public_key_from_multibase with invalid Ed25519 key length"""
        # Create an invalid multibase string (too short for Ed25519)
        import multibase
        invalid_key = bytes([0xed, 0x01]) + b'\x00' * 20  # Only 20 bytes instead of 32
        multibase_str = multibase.encode('base58btc', invalid_key).decode('utf-8')

        with pytest.raises(CryptoError, match="Invalid Ed25519 public key length"):
            key_manager.public_key_from_multibase(multibase_str)

    def test_public_key_from_multibase_invalid_length_p256(self, key_manager):
        """Test public_key_from_multibase with invalid P-256 key length"""
        import multibase
        # Create an invalid multibase string (wrong length for P-256)
        invalid_key = bytes([0x12, 0x00]) + b'\x00' * 20  # Only 20 bytes instead of 33
        multibase_str = multibase.encode('base58btc', invalid_key).decode('utf-8')

        with pytest.raises(CryptoError, match="Invalid P-256 compressed public key length"):
            key_manager.public_key_from_multibase(multibase_str)

    def test_public_key_from_multibase_too_short(self, key_manager):
        """Test public_key_from_multibase with too short data"""
        import multibase
        # Create a multibase string that's too short (< 2 bytes)
        multibase_str = multibase.encode('base58btc', b'\x00').decode('utf-8')

        with pytest.raises(CryptoError, match="Invalid publicKeyMultibase: too short"):
            key_manager.public_key_from_multibase(multibase_str)

    def test_public_key_from_multibase_unsupported_header(self, key_manager):
        """Test public_key_from_multibase with unsupported multicodec header"""
        import multibase
        # Create a multibase string with unsupported header
        invalid_key = bytes([0xFF, 0xFF]) + b'\x00' * 32
        multibase_str = multibase.encode('base58btc', invalid_key).decode('utf-8')

        with pytest.raises(CryptoError, match="Unsupported multicodec header"):
            key_manager.public_key_from_multibase(multibase_str)

    def test_compressed_point_to_der_invalid_prefix(self, key_manager):
        """Test _compressed_point_to_der with invalid compressed point prefix"""
        # Create an invalid compressed point (invalid prefix byte)
        invalid_point = bytes([0x01]) + b'\x00' * 32

        with pytest.raises(CryptoError, match="Invalid compressed point prefix"):
            key_manager._compressed_point_to_der(invalid_point)


class TestSignatureManagerAdvanced:
    """Test SignatureManager advanced functionality and edge cases"""

    def test_sign_data_with_missing_private_key(self, key_manager, signature_manager):
        """Test signing data when private key is not found"""
        with pytest.raises(CryptoError, match="秘密鍵が見つかりません"):
            signature_manager.sign_data({"test": "data"}, "nonexistent_key")

    def test_sign_data_with_unsupported_algorithm(self, key_manager, signature_manager):
        """Test signing data with unsupported algorithm"""
        key_manager.generate_key_pair("test_key")

        with pytest.raises(CryptoError, match="サポートされていないアルゴリズム"):
            signature_manager.sign_data({"test": "data"}, "test_key", algorithm="UNSUPPORTED")

    def test_sign_data_with_string(self, key_manager, signature_manager):
        """Test signing string data with Ed25519"""
        key_manager.generate_ed25519_key_pair("string_sign_test")

        signature = signature_manager.sign_data("test string", "string_sign_test", algorithm="ED25519")
        assert signature is not None
        assert signature.algorithm == "ED25519"

        # Verify signature
        is_valid = signature_manager.verify_signature("test string", signature)
        assert is_valid

    def test_sign_data_with_bytes(self, key_manager, signature_manager):
        """Test signing bytes data with Ed25519"""
        key_manager.generate_ed25519_key_pair("bytes_sign_test")

        test_bytes = b"test bytes data"
        signature = signature_manager.sign_data(test_bytes, "bytes_sign_test", algorithm="ED25519")
        assert signature is not None

        # Verify signature
        is_valid = signature_manager.verify_signature(test_bytes, signature)
        assert is_valid

    def test_verify_signature_with_invalid_signature(self, key_manager, signature_manager):
        """Test verifying an invalid signature"""
        key_manager.generate_ed25519_key_pair("invalid_sig_test")

        # Create a valid signature
        signature = signature_manager.sign_data({"data": "original"}, "invalid_sig_test", algorithm="ED25519")

        # Try to verify with different data
        is_valid = signature_manager.verify_signature({"data": "modified"}, signature)
        assert not is_valid

    def test_verify_signature_with_corrupted_signature_value(self, key_manager, signature_manager):
        """Test verifying a signature with corrupted signature value"""
        key_manager.generate_ed25519_key_pair("corrupted_sig_test")

        # Create a valid signature
        signature = signature_manager.sign_data({"data": "test"}, "corrupted_sig_test", algorithm="ED25519")

        # Corrupt the signature value
        signature.value = "corrupted_base64_data"

        # Verification should fail gracefully
        is_valid = signature_manager.verify_signature({"data": "test"}, signature)
        assert not is_valid

    def test_sign_and_verify_a2a_message_ed25519(self, key_manager, signature_manager):
        """Test A2A message signing and verification with Ed25519"""
        # Generate key
        key_manager.generate_ed25519_key_pair("a2a_test_ed25519")

        # Create A2A message
        a2a_message = {
            "header": {
                "message_id": "msg_001",
                "sender": "did:ap2:agent:shopping_agent",
                "recipient": "did:ap2:agent:merchant_agent",
                "proof": {"signatureValue": "placeholder"}
            },
            "dataPart": {
                "type": "ap2/IntentMandate",
                "id": "intent_001",
                "payload": {"intent": "Buy shoes"}
            }
        }

        # Sign
        signature = signature_manager.sign_a2a_message(
            a2a_message, "a2a_test_ed25519", algorithm="ED25519"
        )
        assert signature is not None
        assert signature.algorithm == "ED25519"

        # Verify
        is_valid = signature_manager.verify_a2a_message_signature(a2a_message, signature)
        assert is_valid

    def test_sign_and_verify_a2a_message_ecdsa(self, key_manager, signature_manager):
        """Test A2A message signing and verification with ECDSA"""
        # Generate key
        key_manager.generate_key_pair("a2a_test_ecdsa")

        # Create A2A message
        a2a_message = {
            "header": {
                "message_id": "msg_002",
                "sender": "did:ap2:agent:test_agent",
                "recipient": "did:ap2:agent:recipient",
            },
            "dataPart": {
                "type": "ap2/CartMandate",
                "id": "cart_001"
            }
        }

        # Sign with ECDSA
        signature = signature_manager.sign_a2a_message(
            a2a_message, "a2a_test_ecdsa", algorithm="ECDSA"
        )
        assert signature is not None
        assert signature.algorithm == "ECDSA"

        # Verify
        is_valid = signature_manager.verify_a2a_message_signature(a2a_message, signature)
        assert is_valid

    def test_verify_timestamp_with_custom_tolerance(self, signature_manager):
        """Test timestamp verification with custom tolerance"""
        from datetime import datetime, timezone, timedelta

        # Create a timestamp 10 seconds ago
        past_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        timestamp_str = past_time.isoformat().replace('+00:00', 'Z')

        # Should fail with 5 second tolerance
        assert not signature_manager.verify_timestamp(timestamp_str, tolerance_seconds=5)

        # Should pass with 30 second tolerance
        assert signature_manager.verify_timestamp(timestamp_str, tolerance_seconds=30)

    def test_verify_timestamp_with_invalid_format(self, signature_manager):
        """Test timestamp verification with invalid format"""
        with pytest.raises(ValueError, match="Invalid timestamp format"):
            signature_manager.verify_timestamp("invalid-timestamp-format")

    def test_verify_timestamp_without_timezone(self, signature_manager):
        """Test timestamp verification with timestamp lacking timezone info"""
        from datetime import datetime

        # Create timestamp without timezone (should be treated as UTC)
        timestamp_str = datetime.utcnow().isoformat()

        # Should be valid
        assert signature_manager.verify_timestamp(timestamp_str)

    def test_sign_intent_mandate(self, key_manager, signature_manager):
        """Test signing IntentMandate (special handling)"""
        key_manager.generate_ed25519_key_pair("intent_mandate_test")

        intent_mandate = {
            "type": "IntentMandate",
            "id": "intent_001",
            "intent": "Buy running shoes",
            "constraints": {"max_price": 10000},
            "extra_field": "should_not_be_signed"
        }

        # Sign (should only sign intent and constraints)
        signature = signature_manager.sign_mandate(intent_mandate, "intent_mandate_test")
        assert signature is not None

        # Verify
        is_valid = signature_manager.verify_mandate_signature(intent_mandate, signature)
        assert is_valid

    def test_sign_cart_mandate_with_excluded_fields(self, key_manager, signature_manager):
        """Test signing CartMandate with fields that should be excluded"""
        key_manager.generate_ed25519_key_pair("cart_mandate_test")

        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "TEST-001", "quantity": 1}],
            "user_signature": "should_be_excluded",
            "merchant_signature": "should_be_excluded",
            "merchant_authorization": "should_be_excluded",
            "mandate_metadata": "should_be_excluded"
        }

        # Sign (excluded fields should not affect signature)
        signature = signature_manager.sign_mandate(cart_mandate, "cart_mandate_test")
        assert signature is not None

        # Verify
        is_valid = signature_manager.verify_mandate_signature(cart_mandate, signature)
        assert is_valid


class TestSecureStorageAdvanced:
    """Test SecureStorage advanced functionality and edge cases"""

    def test_load_and_decrypt_file_not_found(self, secure_storage, test_passphrase):
        """Test loading non-existent encrypted file"""
        with pytest.raises(CryptoError, match="ファイルが見つかりません"):
            secure_storage.load_and_decrypt("nonexistent_file.enc", test_passphrase)

    def test_encrypt_decrypt_complex_data(self, secure_storage, test_passphrase):
        """Test encrypting and decrypting complex nested data"""
        complex_data = {
            "level1": {
                "level2": {
                    "level3": ["item1", "item2", {"nested": True}]
                },
                "array": [1, 2, 3, 4, 5]
            },
            "unicode": "日本語テスト",
            "special_chars": "!@#$%^&*()"
        }

        # Encrypt and save
        file_path = secure_storage.encrypt_and_save(
            complex_data, "complex_test.enc", test_passphrase
        )

        # Load and decrypt
        decrypted = secure_storage.load_and_decrypt("complex_test.enc", test_passphrase)

        assert decrypted == complex_data

    def test_encrypt_decrypt_unicode_data(self, secure_storage, test_passphrase):
        """Test encrypting and decrypting Unicode data"""
        unicode_data = {
            "japanese": "こんにちは世界",
            "emoji": "🔐🔑🛡️",
            "chinese": "你好世界",
            "arabic": "مرحبا بالعالم"
        }

        # Encrypt and save
        secure_storage.encrypt_and_save(unicode_data, "unicode_test.enc", test_passphrase)

        # Load and decrypt
        decrypted = secure_storage.load_and_decrypt("unicode_test.enc", test_passphrase)

        assert decrypted == unicode_data


class TestWebAuthnChallengeManagerAdvanced:
    """Test WebAuthnChallengeManager advanced functionality and edge cases"""

    def test_cleanup_expired_challenges(self):
        """Test cleanup of expired challenges"""
        # Create manager with 0-second TTL
        manager = WebAuthnChallengeManager(challenge_ttl_seconds=0)

        # Generate some challenges
        manager.generate_challenge("user_001", context="test1")
        manager.generate_challenge("user_002", context="test2")
        manager.generate_challenge("user_003", context="test3")

        import time
        time.sleep(0.1)  # Wait for expiration

        # Cleanup
        manager.cleanup_expired_challenges()

        # Verify all challenges are cleaned up
        assert len(manager._challenges) == 0

    def test_verify_challenge_not_found(self, webauthn_challenge_manager):
        """Test verifying non-existent challenge"""
        result = webauthn_challenge_manager.verify_and_consume_challenge(
            "nonexistent_id", "challenge_value", "user_001"
        )
        assert not result

    def test_verify_challenge_value_mismatch(self, webauthn_challenge_manager):
        """Test verifying challenge with wrong value"""
        result = webauthn_challenge_manager.generate_challenge("user_001")
        challenge_id = result["challenge_id"]

        # Try with wrong challenge value
        is_valid = webauthn_challenge_manager.verify_and_consume_challenge(
            challenge_id, "wrong_challenge_value", "user_001"
        )
        assert not is_valid

    def test_verify_challenge_user_id_mismatch(self, webauthn_challenge_manager):
        """Test verifying challenge with wrong user ID"""
        result = webauthn_challenge_manager.generate_challenge("user_001")
        challenge_id = result["challenge_id"]
        challenge = result["challenge"]

        # Try with wrong user ID
        is_valid = webauthn_challenge_manager.verify_and_consume_challenge(
            challenge_id, challenge, "wrong_user"
        )
        assert not is_valid

    def test_generate_challenge_with_context(self, webauthn_challenge_manager):
        """Test generating challenge with context information"""
        result = webauthn_challenge_manager.generate_challenge(
            "user_001", context="payment_authorization"
        )

        assert "challenge_id" in result
        assert "challenge" in result
        assert result["challenge_id"].startswith("ch_")

        # Verify context is stored
        stored = webauthn_challenge_manager._challenges[result["challenge_id"]]
        assert stored["context"] == "payment_authorization"


class TestDeviceAttestationManagerAdvanced:
    """Test DeviceAttestationManager advanced functionality and edge cases"""

    def test_generate_challenge_direct(self, device_attestation_manager):
        """Test generating challenge directly"""
        challenge = device_attestation_manager.generate_challenge()

        assert isinstance(challenge, str)
        assert len(challenge) > 0

        # Should be valid base64
        import base64
        decoded = base64.b64decode(challenge)
        assert len(decoded) == 32  # 256 bits

    def test_create_device_attestation_with_missing_key(self, device_attestation_manager):
        """Test creating device attestation when device key is missing"""
        with pytest.raises(CryptoError, match="デバイス秘密鍵が見つかりません"):
            device_attestation_manager.create_device_attestation(
                device_id="device_missing",
                payment_mandate_id="payment_001",
                device_key_id="nonexistent_key"
            )

    def test_create_device_attestation_with_all_fields(self, key_manager, device_attestation_manager):
        """Test creating device attestation with all optional fields"""
        # Generate device key
        key_manager.generate_key_pair("device_full")

        # Create attestation with all fields
        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_full",
            payment_mandate_id="payment_full",
            device_key_id="device_full",
            attestation_type=AttestationType.BIOMETRIC,
            platform="Android",
            os_version="14.0",
            app_version="1.2.3",
            timestamp="2025-11-18T12:00:00Z",
            challenge="custom_challenge",
            webauthn_signature="sig_data",
            webauthn_authenticator_data="auth_data",
            webauthn_client_data_json="client_data"
        )

        assert attestation.platform == "Android"
        assert attestation.os_version == "14.0"
        assert attestation.app_version == "1.2.3"
        assert attestation.challenge == "custom_challenge"
        assert attestation.webauthn_signature == "sig_data"

    def test_verify_device_attestation_timestamp_in_future(self, key_manager, device_attestation_manager):
        """Test verifying device attestation with timestamp in the future"""
        key_manager.generate_key_pair("device_future")

        from datetime import datetime, timezone, timedelta

        # Create attestation with future timestamp
        future_time = datetime.now(timezone.utc) + timedelta(hours=1)
        future_timestamp = future_time.isoformat().replace('+00:00', 'Z')

        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_future",
            payment_mandate_id="payment_future",
            device_key_id="device_future",
            timestamp=future_timestamp
        )

        # Verification should fail (timestamp in future)
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation, "payment_future", max_age_seconds=300
        )
        assert not is_valid

    def test_verify_device_attestation_expired(self, key_manager, device_attestation_manager):
        """Test verifying expired device attestation"""
        key_manager.generate_key_pair("device_expired")

        from datetime import datetime, timezone, timedelta

        # Create attestation with old timestamp
        old_time = datetime.now(timezone.utc) - timedelta(hours=1)
        old_timestamp = old_time.isoformat().replace('+00:00', 'Z')

        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_expired",
            payment_mandate_id="payment_expired",
            device_key_id="device_expired",
            timestamp=old_timestamp
        )

        # Verification should fail (expired)
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation, "payment_expired", max_age_seconds=60  # 1 minute max
        )
        assert not is_valid

    def test_verify_device_attestation_wrong_signature(self, key_manager, device_attestation_manager):
        """Test verifying device attestation with corrupted signature"""
        key_manager.generate_key_pair("device_corrupt")

        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_corrupt",
            payment_mandate_id="payment_correct",
            device_key_id="device_corrupt"
        )

        # Corrupt the attestation value
        attestation.attestation_value = "corrupted_signature_data"

        # Verification should fail
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation, "payment_correct"
        )
        assert not is_valid

    def test_parse_authenticator_data_valid(self, device_attestation_manager):
        """Test parsing valid authenticator data"""
        import base64
        import struct

        # Create valid authenticator data
        rp_id_hash = b'\x00' * 32  # 32 bytes
        flags = 0x01  # User present flag
        sign_count = 42

        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Parse
        parsed = device_attestation_manager._parse_authenticator_data(authenticator_data_b64)

        assert parsed["flags"] == flags
        assert parsed["sign_count"] == sign_count
        assert len(parsed["rp_id_hash"]) == 64  # 32 bytes in hex

    def test_parse_authenticator_data_too_short(self, device_attestation_manager):
        """Test parsing authenticator data that's too short"""
        import base64

        # Create data that's too short (less than 37 bytes)
        short_data = b'\x00' * 20
        short_data_b64 = base64.urlsafe_b64encode(short_data).decode('utf-8').rstrip('=')

        # Should raise ValueError
        with pytest.raises(ValueError, match="AuthenticatorData too short"):
            device_attestation_manager._parse_authenticator_data(short_data_b64)

    def test_verify_webauthn_signature_missing_client_data(self, device_attestation_manager):
        """Test WebAuthn signature verification with missing clientDataJSON"""
        webauthn_result = {
            "authenticatorData": "test_data",
            "signature": "test_sig"
            # Missing clientDataJSON
        }

        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, "challenge", "public_key", 0
        )
        assert not is_valid
        assert counter == 0

    def test_verify_webauthn_signature_missing_authenticator_data(self, device_attestation_manager):
        """Test WebAuthn signature verification with missing authenticatorData"""
        import base64
        import json

        client_data = {"type": "webauthn.get", "challenge": "test_challenge"}
        client_data_json = json.dumps(client_data).encode('utf-8')
        client_data_b64 = base64.urlsafe_b64encode(client_data_json).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_b64,
            "signature": "test_sig"
            # Missing authenticatorData
        }

        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, "test_challenge", "public_key", 0
        )
        assert not is_valid

    def test_verify_webauthn_signature_challenge_mismatch(self, device_attestation_manager):
        """Test WebAuthn signature verification with challenge mismatch"""
        import base64
        import json

        client_data = {"type": "webauthn.get", "challenge": "wrong_challenge"}
        client_data_json = json.dumps(client_data).encode('utf-8')
        client_data_b64 = base64.urlsafe_b64encode(client_data_json).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_b64
        }

        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, "expected_challenge", "public_key", 0
        )
        assert not is_valid

    def test_verify_webauthn_signature_invalid_type(self, device_attestation_manager):
        """Test WebAuthn signature verification with invalid authentication type"""
        import base64
        import json

        client_data = {"type": "webauthn.create", "challenge": "test_challenge"}
        client_data_json = json.dumps(client_data).encode('utf-8')
        client_data_b64 = base64.urlsafe_b64encode(client_data_json).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_b64
        }

        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, "test_challenge", "public_key", 0
        )
        assert not is_valid


class TestUtilityFunctionsAdvanced:
    """Test utility functions with edge cases and error handling"""

    def test_compute_mandate_hash_with_base64_format(self):
        """Test computing mandate hash in base64 format"""
        mandate = {
            "type": "CartMandate",
            "id": "cart_002",
            "items": [{"sku": "TEST-002", "quantity": 2}]
        }

        hash_b64 = compute_mandate_hash(mandate, hash_format='base64')

        # Should be valid base64
        import base64
        decoded = base64.b64decode(hash_b64)
        assert len(decoded) == 32  # SHA-256 is 32 bytes

    def test_compute_mandate_hash_unsupported_format(self):
        """Test computing mandate hash with unsupported format"""
        mandate = {"type": "TestMandate", "id": "test_001"}

        with pytest.raises(ValueError, match="Unsupported hash format"):
            compute_mandate_hash(mandate, hash_format='unsupported')

    def test_verify_mandate_hash_base64(self):
        """Test verifying mandate hash in base64 format"""
        mandate = {"type": "TestMandate", "id": "test_002"}

        expected_hash = compute_mandate_hash(mandate, hash_format='base64')
        is_valid = verify_mandate_hash(mandate, expected_hash, hash_format='base64')

        assert is_valid

    def test_canonicalize_json_with_enum_values(self):
        """Test JSON canonicalization with Enum values"""
        from common.models import AttestationType

        data = {
            "attestation_type": AttestationType.BIOMETRIC,
            "nested": {
                "type": AttestationType.WEBAUTHN
            }
        }

        canonical = canonicalize_json(data)

        # Should convert enums to their values
        import json
        result = json.loads(canonical)
        assert result["attestation_type"] == "biometric"
        assert result["nested"]["type"] == "webauthn"

    def test_canonicalize_json_with_nested_enums(self):
        """Test JSON canonicalization with deeply nested Enum values"""
        from common.models import AttestationType

        data = {
            "level1": {
                "level2": {
                    "level3": {
                        "attestation": AttestationType.BIOMETRIC
                    }
                }
            }
        }

        canonical = canonicalize_json(data)

        import json
        result = json.loads(canonical)
        assert result["level1"]["level2"]["level3"]["attestation"] == "biometric"

    def test_canonicalize_json_with_list_of_enums(self):
        """Test JSON canonicalization with list containing Enum values"""
        from common.models import AttestationType

        data = {
            "types": [
                AttestationType.BIOMETRIC,
                AttestationType.WEBAUTHN
            ]
        }

        canonical = canonicalize_json(data)

        import json
        result = json.loads(canonical)
        assert result["types"] == ["biometric", "webauthn"]

    def test_canonicalize_a2a_message_preserves_data_part(self):
        """Test that A2A message canonicalization preserves dataPart"""
        message = {
            "header": {
                "message_id": "msg_003",
                "sender": "test_sender",
                "proof": {"signatureValue": "should_be_removed"}
            },
            "dataPart": {
                "type": "ap2/TestMessage",
                "payload": {"important": "data"}
            }
        }

        canonical = canonicalize_a2a_message(message)
        import json
        result = json.loads(canonical)

        # Proof should be removed
        assert "proof" not in result.get("header", {})

        # dataPart should be preserved
        assert "dataPart" in result
        assert result["dataPart"]["payload"]["important"] == "data"


class TestImportErrorHandling:
    """Test import error handling and edge cases"""

    def test_canonicalize_json_without_rfc8785(self):
        """Test canonicalize_json raises error when rfc8785 is not available"""
        import common.crypto as crypto_module

        # Save original value
        original_value = crypto_module.RFC8785_AVAILABLE

        try:
            # Simulate rfc8785 not being available
            crypto_module.RFC8785_AVAILABLE = False

            # Should raise ImportError
            with pytest.raises(ImportError, match="rfc8785 library is required"):
                canonicalize_json({"test": "data"})
        finally:
            # Restore original value
            crypto_module.RFC8785_AVAILABLE = original_value

    def test_public_key_to_multibase_without_multibase(self, key_manager):
        """Test public_key_to_multibase raises error when multibase is not available"""
        import common.crypto as crypto_module

        # Generate a key
        _, public_key = key_manager.generate_key_pair("test_multibase")

        # Save original value
        original_value = crypto_module.MULTIBASE_AVAILABLE

        try:
            # Simulate multibase not being available
            crypto_module.MULTIBASE_AVAILABLE = False

            # Should raise ImportError
            with pytest.raises(ImportError, match="multibase library is required"):
                key_manager.public_key_to_multibase(public_key)
        finally:
            # Restore original value
            crypto_module.MULTIBASE_AVAILABLE = original_value

    def test_public_key_from_multibase_without_multibase(self, key_manager):
        """Test public_key_from_multibase raises error when multibase is not available"""
        import common.crypto as crypto_module

        # Save original value
        original_value = crypto_module.MULTIBASE_AVAILABLE

        try:
            # Simulate multibase not being available
            crypto_module.MULTIBASE_AVAILABLE = False

            # Should raise ImportError
            with pytest.raises(ImportError, match="multibase library is required"):
                key_manager.public_key_from_multibase("z6MkTest")
        finally:
            # Restore original value
            crypto_module.MULTIBASE_AVAILABLE = original_value

    def test_public_key_to_multibase_unsupported_key_type(self, key_manager):
        """Test public_key_to_multibase with unsupported key type"""
        # Create a mock unsupported key type
        class UnsupportedKey:
            pass

        unsupported_key = UnsupportedKey()

        with pytest.raises(CryptoError, match="Unsupported public key type"):
            key_manager.public_key_to_multibase(unsupported_key)


class TestDIDParsingEdgeCases:
    """Test DID parsing edge cases and fallback logic"""

    def test_load_public_key_with_unknown_entity_type(self, key_manager):
        """Test loading public key with unknown DID entity type (fallback case)"""
        # Generate and save a key with "test_entity" as key_id
        _, public_key = key_manager.generate_key_pair("test_entity")
        key_manager.save_public_key("test_entity", public_key)

        # Test with an unknown entity type DID (should use fallback logic)
        loaded_key = key_manager.load_public_key("did:ap2:unknown:test_entity")
        assert loaded_key is not None

    def test_get_private_key_with_unknown_entity_type(self, key_manager):
        """Test getting private key with unknown DID entity type (fallback case)"""
        # Generate a key with "test_entity" as key_id
        key_manager.generate_key_pair("test_entity")

        # Test with an unknown entity type DID (should use fallback logic)
        private_key = key_manager.get_private_key("did:ap2:unknown:test_entity")
        assert private_key is not None


class TestSignatureManagerEdgeCases:
    """Test SignatureManager edge cases"""

    def test_hash_data_with_non_dict_non_str(self, signature_manager):
        """Test _hash_data with data that's not dict or str"""
        # Test with integer
        hash_result = signature_manager._hash_data(12345)
        assert hash_result is not None
        assert len(hash_result) == 32  # SHA-256 is 32 bytes

    def test_convert_enums_method(self, signature_manager):
        """Test _convert_enums internal method"""
        from common.models import AttestationType

        # Test with dict containing enums
        data_with_enums = {
            "type": AttestationType.BIOMETRIC,
            "nested": {
                "attestation": AttestationType.WEBAUTHN
            },
            "list": [AttestationType.BIOMETRIC, "string", 123]
        }

        converted = signature_manager._convert_enums(data_with_enums)

        assert converted["type"] == "biometric"
        assert converted["nested"]["attestation"] == "webauthn"
        assert converted["list"][0] == "biometric"
        assert converted["list"][1] == "string"
        assert converted["list"][2] == 123


class TestCanonicalizeA2AMessageEdgeCases:
    """Test canonicalize_a2a_message edge cases"""

    def test_canonicalize_a2a_message_with_non_dict_values(self):
        """Test canonicalize_a2a_message with non-dict values (line 153)"""
        message = {
            "header": {
                "message_id": "msg_004",
                "sender": "test_sender"
            },
            "dataPart": "simple_string_value",  # Non-dict value
            "timestamp": 1234567890  # Non-dict value
        }

        canonical = canonicalize_a2a_message(message)
        import json
        result = json.loads(canonical)

        # Non-dict values should be preserved
        assert result["dataPart"] == "simple_string_value"
        assert result["timestamp"] == 1234567890


class TestWebAuthnSignatureVerification:
    """Test complete WebAuthn signature verification flow"""

    def test_verify_webauthn_signature_complete_flow(self, key_manager, device_attestation_manager):
        """Test complete WebAuthn signature verification with valid data"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # Generate a P-256 key pair for WebAuthn
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key format
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2,  # kty: EC2
            3: -7,  # alg: ES256
            -1: 1,  # crv: P-256
            -2: x_bytes,  # x coordinate
            -3: y_bytes   # y coordinate
        }
        public_key_cose = cbor2.dumps(cose_key)
        public_key_cose_b64 = base64.b64encode(public_key_cose).decode('utf-8')

        # Create challenge
        challenge = "test_challenge_value_123"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01  # User present
        sign_count = 1
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create signed data
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = authenticator_data + client_data_hash

        # Sign with private key
        signature_bytes = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        # Create WebAuthn result
        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": signature_b64
        }

        # Verify
        is_valid, new_counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result,
            challenge,
            public_key_cose_b64,
            stored_counter=0,
            rp_id=rp_id
        )

        assert is_valid
        assert new_counter == 1

    def test_verify_webauthn_signature_with_zero_counters(self, key_manager, device_attestation_manager):
        """Test WebAuthn signature verification with zero counters (AP2 compliant)"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        # Create challenge
        challenge = "test_challenge_zero"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData with counter = 0
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 0  # Zero counter
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create and sign data
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = authenticator_data + client_data_hash
        signature_bytes = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": signature_b64
        }

        # Verify with stored_counter = 0
        is_valid, new_counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, stored_counter=0, rp_id=rp_id
        )

        assert is_valid
        assert new_counter == 0

    def test_verify_webauthn_signature_counter_anomaly(self, key_manager, device_attestation_manager):
        """Test WebAuthn signature verification with counter anomaly"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        challenge = "test_challenge_counter"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData with counter = 5 (but stored counter is 10)
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 5  # Lower than stored counter
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create and sign data
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = authenticator_data + client_data_hash
        signature_bytes = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": signature_b64
        }

        # Verify with stored_counter = 10 (should fail due to counter anomaly)
        is_valid, new_counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, stored_counter=10, rp_id=rp_id
        )

        assert not is_valid
        assert new_counter == 10  # Should return stored counter on failure

    def test_verify_webauthn_signature_rp_id_mismatch(self, key_manager, device_attestation_manager):
        """Test WebAuthn signature verification with RP ID hash mismatch"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        challenge = "test_challenge_rp"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData with WRONG RP ID hash
        wrong_rp_id = "example.com"
        rp_id_hash = hashlib.sha256(wrong_rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 1
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create and sign data
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = authenticator_data + client_data_hash
        signature_bytes = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": signature_b64
        }

        # Verify with correct RP ID (should fail due to mismatch)
        is_valid, new_counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, stored_counter=0, rp_id="localhost"
        )

        assert not is_valid

    def test_verify_webauthn_signature_with_response_wrapper(self, key_manager, device_attestation_manager):
        """Test WebAuthn signature verification with response wrapper structure"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import hashes

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        challenge = "test_challenge_wrapper"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 2
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create and sign data
        client_data_hash = hashlib.sha256(client_data_json_bytes).digest()
        signed_data = authenticator_data + client_data_hash
        signature_bytes = private_key.sign(signed_data, ec.ECDSA(hashes.SHA256()))
        signature_b64 = base64.urlsafe_b64encode(signature_bytes).decode('utf-8').rstrip('=')

        # Create WebAuthn result with 'response' wrapper
        webauthn_result = {
            "response": {
                "clientDataJSON": client_data_json_b64,
                "authenticatorData": authenticator_data_b64,
                "signature": signature_b64
            }
        }

        # Verify
        is_valid, new_counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, stored_counter=0, rp_id=rp_id
        )

        assert is_valid
        assert new_counter == 2


class TestDeviceAttestationTimezoneHandling:
    """Test device attestation timezone handling edge cases"""

    def test_verify_device_attestation_without_timezone_info(self, key_manager, device_attestation_manager):
        """Test verifying device attestation with timestamp lacking timezone info (line 1649)"""
        from datetime import datetime

        # Generate device key
        key_manager.generate_key_pair("device_tz_test")

        # Create attestation with timestamp lacking timezone (will be treated as UTC)
        timestamp_no_tz = datetime.utcnow().isoformat()

        attestation = device_attestation_manager.create_device_attestation(
            device_id="device_tz_test",
            payment_mandate_id="payment_tz_test",
            device_key_id="device_tz_test",
            timestamp=timestamp_no_tz
        )

        # Verify (should handle missing timezone by adding UTC)
        is_valid = device_attestation_manager.verify_device_attestation(
            attestation, "payment_tz_test", max_age_seconds=300
        )

        assert is_valid


class TestWebAuthnVerificationErrorPaths:
    """Test WebAuthn verification error paths and edge cases"""

    def test_verify_webauthn_signature_missing_challenge_field(self, device_attestation_manager):
        """Test WebAuthn verification when challenge field is missing from clientDataJSON"""
        import base64
        import json

        # Create clientDataJSON without challenge field
        client_data = {
            "type": "webauthn.get",
            "origin": "https://localhost"
            # Missing "challenge" field
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": "test_auth_data",
            "signature": "test_sig"
        }

        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, "expected_challenge", "public_key", 0
        )

        assert not is_valid
        assert counter == 0

    def test_verify_webauthn_signature_cbor2_not_available(self, device_attestation_manager):
        """Test WebAuthn verification when cbor2 is not available"""
        import common.crypto as crypto_module
        import base64
        import json
        import struct
        import hashlib

        # Save original value
        original_value = crypto_module.CBOR2_AVAILABLE

        try:
            # Simulate cbor2 not being available
            crypto_module.CBOR2_AVAILABLE = False

            # Create valid WebAuthn data
            challenge = "test_challenge"
            client_data = {
                "type": "webauthn.get",
                "challenge": challenge,
                "origin": "https://localhost"
            }
            client_data_json_bytes = json.dumps(client_data).encode('utf-8')
            client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

            rp_id = "localhost"
            rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
            flags = 0x01
            sign_count = 1
            authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
            authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

            webauthn_result = {
                "clientDataJSON": client_data_json_b64,
                "authenticatorData": authenticator_data_b64,
                "signature": "test_sig"
            }

            # Should fail because cbor2 is not available
            is_valid, counter = device_attestation_manager.verify_webauthn_signature(
                webauthn_result, challenge, "public_key_cose", 0, rp_id=rp_id
            )

            assert not is_valid
            assert counter == 0
        finally:
            # Restore original value
            crypto_module.CBOR2_AVAILABLE = original_value

    def test_verify_webauthn_signature_invalid_cose_key_format(self, device_attestation_manager):
        """Test WebAuthn verification with invalid COSE key format"""
        import base64
        import json
        import struct
        import hashlib

        challenge = "test_challenge"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 1
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create invalid COSE key (not a dict, just a string encoded as CBOR)
        import cbor2
        invalid_cose_key = cbor2.dumps("not_a_dict")
        invalid_cose_key_b64 = base64.b64encode(invalid_cose_key).decode('utf-8')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": "test_sig"
        }

        # Should fail because COSE key is not a dict
        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, invalid_cose_key_b64, 0, rp_id=rp_id
        )

        assert not is_valid
        assert counter == 0

    def test_verify_webauthn_signature_missing_signature_field(self, device_attestation_manager):
        """Test WebAuthn verification with missing signature field"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        challenge = "test_challenge"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 1
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create WebAuthn result WITHOUT signature field
        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64
            # Missing "signature" field
        }

        # Should fail because signature is missing
        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, 0, rp_id=rp_id
        )

        assert not is_valid
        assert counter == 0

    def test_verify_webauthn_signature_invalid_signature_exception(self, device_attestation_manager):
        """Test WebAuthn verification with invalid signature (triggers InvalidSignature exception)"""
        import base64
        import json
        import struct
        import hashlib
        from cryptography.hazmat.primitives.asymmetric import ec

        # Generate a P-256 key pair
        private_key = ec.generate_private_key(ec.SECP256R1())
        public_key = private_key.public_key()

        # Create COSE public key
        public_numbers = public_key.public_numbers()
        x_bytes = public_numbers.x.to_bytes(32, byteorder='big')
        y_bytes = public_numbers.y.to_bytes(32, byteorder='big')

        import cbor2
        cose_key = {
            1: 2, 3: -7, -1: 1, -2: x_bytes, -3: y_bytes
        }
        public_key_cose_b64 = base64.b64encode(cbor2.dumps(cose_key)).decode('utf-8')

        challenge = "test_challenge"

        # Create clientDataJSON
        client_data = {
            "type": "webauthn.get",
            "challenge": challenge,
            "origin": "https://localhost"
        }
        client_data_json_bytes = json.dumps(client_data).encode('utf-8')
        client_data_json_b64 = base64.urlsafe_b64encode(client_data_json_bytes).decode('utf-8').rstrip('=')

        # Create authenticatorData
        rp_id = "localhost"
        rp_id_hash = hashlib.sha256(rp_id.encode('utf-8')).digest()
        flags = 0x01
        sign_count = 1
        authenticator_data = rp_id_hash + struct.pack('B', flags) + struct.pack('>I', sign_count)
        authenticator_data_b64 = base64.urlsafe_b64encode(authenticator_data).decode('utf-8').rstrip('=')

        # Create WRONG signature (will trigger InvalidSignature exception)
        wrong_signature = b'\x00' * 64  # Invalid signature bytes
        signature_b64 = base64.urlsafe_b64encode(wrong_signature).decode('utf-8').rstrip('=')

        webauthn_result = {
            "clientDataJSON": client_data_json_b64,
            "authenticatorData": authenticator_data_b64,
            "signature": signature_b64
        }

        # Should fail because signature is invalid
        is_valid, counter = device_attestation_manager.verify_webauthn_signature(
            webauthn_result, challenge, public_key_cose_b64, 0, rp_id=rp_id
        )

        assert not is_valid
        assert counter == 0
