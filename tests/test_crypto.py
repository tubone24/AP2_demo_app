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
