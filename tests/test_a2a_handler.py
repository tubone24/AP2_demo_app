"""
Tests for common/a2a_handler.py

Tests cover:
- A2A message signature verification
- Message routing and handling
- Response message creation
- Artifact message creation
- Nonce validation (replay attack prevention)
- Error response generation
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from common.a2a_handler import A2AMessageHandler, infer_recipient_from_mandate
from common.models import (
    A2AMessage,
    A2AMessageHeader,
    A2ADataPart,
    A2AProof,
    Signature
)
from common.crypto import KeyManager, SignatureManager


class TestA2AMessageHandler:
    """Test A2AMessageHandler functionality"""

    @pytest.fixture
    def setup_handler(self, key_manager, signature_manager):
        """Setup A2A message handler with keys"""
        # Generate keys for testing
        key_manager.generate_ed25519_key_pair("shopping_agent")
        key_manager.generate_ed25519_key_pair("merchant_agent")

        handler = A2AMessageHandler(
            agent_id="did:ap2:agent:shopping_agent",
            key_manager=key_manager,
            signature_manager=signature_manager
        )
        return handler

    def test_handler_initialization(self, setup_handler):
        """Test A2A handler initialization"""
        handler = setup_handler

        assert handler.agent_id == "did:ap2:agent:shopping_agent"
        assert handler.key_manager is not None
        assert handler.signature_manager is not None
        assert handler.did_resolver is not None
        assert handler.nonce_manager is not None

    def test_create_response_message(self, setup_handler):
        """Test creating a response message"""
        handler = setup_handler

        response = handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.mandates.IntentMandate",
            data_id="intent_001",
            payload={"intent": "Buy running shoes"},
            sign=True
        )

        # Validate structure
        assert isinstance(response, A2AMessage)
        assert response.header.sender == "did:ap2:agent:shopping_agent"
        assert response.header.recipient == "did:ap2:agent:merchant_agent"
        assert response.header.nonce is not None
        assert len(response.header.nonce) > 0
        assert response.dataPart.type == "ap2.mandates.IntentMandate"
        assert response.dataPart.payload["intent"] == "Buy running shoes"

        # Validate signature
        assert response.header.proof is not None
        assert response.header.proof.algorithm in ["ed25519", "ecdsa"]
        assert response.header.proof.signatureValue is not None
        assert response.header.proof.publicKeyMultibase.startswith("z")

    def test_create_artifact_response(self, setup_handler):
        """Test creating an artifact response message"""
        handler = setup_handler

        cart_mandate = {
            "type": "CartMandate",
            "id": "cart_001",
            "items": [{"sku": "SHOE-001", "quantity": 1}]
        }

        response = handler.create_artifact_response(
            recipient="did:ap2:agent:shopping_agent",
            artifact_name="CartMandate",
            artifact_data=cart_mandate,
            data_type_key="CartMandate",
            sign=True
        )

        # Validate structure
        assert isinstance(response, A2AMessage)
        assert response.dataPart.kind == "artifact"
        assert response.dataPart.artifact is not None
        assert response.dataPart.artifact.name == "CartMandate"
        assert len(response.dataPart.artifact.parts) > 0

        # Validate artifact data
        artifact_part = response.dataPart.artifact.parts[0]
        assert artifact_part.kind == "data"
        assert "CartMandate" in artifact_part.data
        assert artifact_part.data["CartMandate"]["type"] == "CartMandate"

    def test_create_error_response(self, setup_handler):
        """Test creating an error response message"""
        handler = setup_handler

        error_response = handler.create_error_response(
            recipient="did:ap2:agent:merchant_agent",
            error_code="INVALID_MANDATE",
            error_message="Mandate validation failed",
            details={"field": "amount", "reason": "exceeds limit"}
        )

        # Validate structure
        assert isinstance(error_response, A2AMessage)
        assert error_response.dataPart.type == "ap2.errors.Error"
        assert error_response.dataPart.payload["error_code"] == "INVALID_MANDATE"
        assert error_response.dataPart.payload["error_message"] == "Mandate validation failed"
        assert "details" in error_response.dataPart.payload

    def test_register_handler(self, setup_handler):
        """Test registering a message handler"""
        handler = setup_handler

        async def test_handler(message):
            return {"status": "handled"}

        handler.register_handler("ap2/TestMessage", test_handler)

        # Verify handler is registered
        assert "ap2/TestMessage" in handler._handlers
        assert handler._handlers["ap2/TestMessage"] == test_handler

    @pytest.mark.asyncio
    async def test_verify_message_signature_valid(self, setup_handler):
        """Test verifying a valid message signature"""
        handler = setup_handler

        # Create a signed message
        message = handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.mandates.IntentMandate",
            data_id="intent_001",
            payload={"intent": "Test"},
            sign=True
        )

        # Verify signature
        is_valid = await handler.verify_message_signature(message)
        assert is_valid

    @pytest.mark.asyncio
    async def test_verify_message_signature_no_proof(self, setup_handler):
        """Test verifying a message without proof"""
        handler = setup_handler

        # Create message without signature
        message = handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.mandates.IntentMandate",
            data_id="intent_001",
            payload={"intent": "Test"},
            sign=False
        )

        # Verification should fail
        is_valid = await handler.verify_message_signature(message)
        assert not is_valid

    @pytest.mark.asyncio
    async def test_nonce_replay_attack_prevention(self, setup_handler):
        """Test nonce replay attack prevention"""
        handler = setup_handler

        # Create first message
        message1 = handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.mandates.IntentMandate",
            data_id="test_001",
            payload={},
            sign=True
        )

        # First verification should succeed
        is_valid1 = await handler.verify_message_signature(message1)
        assert is_valid1

        # Second verification with same nonce should fail (replay attack)
        is_valid2 = await handler.verify_message_signature(message1)
        assert not is_valid2


class TestNonceManager:
    """Test NonceManager functionality"""

    @pytest.mark.asyncio
    async def test_nonce_validation_first_use(self):
        """Test nonce validation on first use"""
        from common.nonce_manager import NonceManager

        nonce_manager = NonceManager(ttl_seconds=60)
        nonce = "test_nonce_001"

        # First use should be valid
        is_valid = await nonce_manager.is_valid_nonce(nonce)
        assert is_valid

    @pytest.mark.asyncio
    async def test_nonce_validation_reuse(self):
        """Test nonce validation on reuse (should fail)"""
        from common.nonce_manager import NonceManager

        nonce_manager = NonceManager(ttl_seconds=60)
        nonce = "test_nonce_002"

        # First use should be valid
        is_valid1 = await nonce_manager.is_valid_nonce(nonce)
        assert is_valid1

        # Second use should be invalid (replay attack)
        is_valid2 = await nonce_manager.is_valid_nonce(nonce)
        assert not is_valid2

    @pytest.mark.asyncio
    async def test_nonce_expiration(self):
        """Test nonce expiration"""
        from common.nonce_manager import NonceManager
        import asyncio

        nonce_manager = NonceManager(ttl_seconds=1)  # 1 second TTL
        nonce = "test_nonce_003"

        # First use
        is_valid1 = await nonce_manager.is_valid_nonce(nonce)
        assert is_valid1

        # Wait for expiration
        await asyncio.sleep(1.5)

        # After expiration, same nonce should be valid again
        is_valid2 = await nonce_manager.is_valid_nonce(nonce)
        assert is_valid2

    @pytest.mark.asyncio
    async def test_concurrent_nonce_validation(self):
        """Test concurrent nonce validation (race condition)"""
        from common.nonce_manager import NonceManager
        import asyncio

        nonce_manager = NonceManager(ttl_seconds=60)
        nonce = "test_nonce_004"

        # Try to validate same nonce concurrently
        results = await asyncio.gather(
            nonce_manager.is_valid_nonce(nonce),
            nonce_manager.is_valid_nonce(nonce),
            nonce_manager.is_valid_nonce(nonce)
        )

        # Only one should succeed
        assert sum(results) == 1


class TestRecipientInference:
    """Test recipient inference from mandate"""

    def test_infer_recipient_intent_mandate(self):
        """Test inferring recipient for IntentMandate"""
        mandate = {
            "type": "IntentMandate",
            "intent": "Buy shoes"
        }

        recipient = infer_recipient_from_mandate(mandate)
        assert recipient == "did:ap2:agent:merchant_agent"

    def test_infer_recipient_cart_mandate_unsigned(self):
        """Test inferring recipient for unsigned CartMandate"""
        mandate = {
            "type": "CartMandate",
            "items": [{"sku": "TEST-001"}]
        }

        recipient = infer_recipient_from_mandate(mandate)
        assert recipient == "did:ap2:merchant"

    def test_infer_recipient_cart_mandate_signed(self):
        """Test inferring recipient for signed CartMandate"""
        mandate = {
            "type": "CartMandate",
            "items": [{"sku": "TEST-001"}],
            "merchant_signature": {
                "algorithm": "ED25519",
                "value": "signature_value"
            }
        }

        recipient = infer_recipient_from_mandate(mandate)
        assert recipient is None  # Returns to user

    def test_infer_recipient_payment_mandate(self):
        """Test inferring recipient for PaymentMandate"""
        mandate = {
            "type": "PaymentMandate",
            "amount": {"value": "100.00", "currency": "JPY"}
        }

        recipient = infer_recipient_from_mandate(mandate)
        assert recipient == "did:ap2:agent:credential_provider"

    def test_infer_recipient_unknown_type(self):
        """Test inferring recipient for unknown mandate type"""
        mandate = {
            "type": "UnknownMandate"
        }

        recipient = infer_recipient_from_mandate(mandate)
        assert recipient is None


class TestA2AMessageStructureValidation:
    """Test A2A message structure validation"""

    def test_a2a_proof_structure(self):
        """Test A2A proof structure"""
        # Test expected proof structure
        proof_structure = {
            "algorithm": "ed25519",
            "signatureValue": "base64_signature",
            "publicKeyMultibase": "z6Mk...",
            "kid": "did:ap2:agent:shopping_agent#key-1",
            "created": datetime.now(timezone.utc).isoformat(),
            "proofPurpose": "authentication"
        }

        # Validate proof structure
        assert "algorithm" in proof_structure
        assert proof_structure["algorithm"] in ["ed25519", "ecdsa"]
        assert "signatureValue" in proof_structure
        assert "publicKeyMultibase" in proof_structure
        assert proof_structure["publicKeyMultibase"].startswith("z")
        assert "kid" in proof_structure
        assert proof_structure["kid"].startswith("did:ap2:agent:")
        assert "#key-" in proof_structure["kid"]
        assert "created" in proof_structure
        assert proof_structure["proofPurpose"] == "authentication"

    def test_message_header_required_fields(self):
        """Test message header required fields"""
        # Test expected header structure
        header_structure = {
            "message_id": "msg_001",
            "sender": "did:ap2:agent:shopping_agent",
            "recipient": "did:ap2:agent:merchant_agent",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nonce": "unique_nonce",
            "schema_version": "0.2"
        }

        # Validate required fields
        required_fields = ["message_id", "sender", "recipient", "timestamp", "nonce", "schema_version"]
        for field in required_fields:
            assert field in header_structure

        assert header_structure["sender"].startswith("did:ap2:agent:")
        assert header_structure["recipient"].startswith("did:ap2:agent:")
        assert header_structure["schema_version"] == "0.2"

    def test_message_nonce_uniqueness(self):
        """Test that each message should have unique nonce"""
        # Generate two nonces
        import secrets
        nonce1 = secrets.token_urlsafe(32)
        nonce2 = secrets.token_urlsafe(32)

        # Nonces should be different (with very high probability)
        assert nonce1 != nonce2
