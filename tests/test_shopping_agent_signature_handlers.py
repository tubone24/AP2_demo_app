"""
Tests for Shopping Agent Signature Handlers

Tests cover:
- signature_handlers.py (shopping_agent)
"""

import pytest
import httpx
from unittest.mock import AsyncMock, Mock
from fastapi import HTTPException


# ============================================================================
# Shopping Agent Signature Handlers Tests
# ============================================================================


class TestSignatureHandlers:
    """Test shopping_agent signature handlers"""

    @pytest.mark.asyncio
    async def test_verify_cart_signature_with_cp_success(self):
        """Test successful cart signature verification"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": True,
            "details": {
                "counter": 1,
                "attestation_type": "packed"
            }
        }
        http_client.post = AsyncMock(return_value=mock_response)

        cart_mandate = {"id": "cart_001", "amount": "10000"}
        webauthn_assertion = {"id": "assertion_001", "response": {}}
        user_id = "user_001"

        # Verify
        result = await SignatureHandlers.verify_cart_signature_with_cp(
            http_client,
            "http://cp.example.com",
            cart_mandate,
            webauthn_assertion,
            user_id
        )

        # Assertions
        assert result["verified"] is True
        assert result["details"]["counter"] == 1
        http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_cart_signature_with_cp_failed_verification(self):
        """Test cart signature verification failure"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with verification failure
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "verified": False,
            "details": {"error": "Invalid signature"}
        }
        http_client.post = AsyncMock(return_value=mock_response)

        cart_mandate = {"id": "cart_001"}
        webauthn_assertion = {}
        user_id = "user_001"

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await SignatureHandlers.verify_cart_signature_with_cp(
                http_client,
                "http://cp.example.com",
                cart_mandate,
                webauthn_assertion,
                user_id
            )

        assert exc_info.value.status_code == 400
        assert "Invalid WebAuthn signature" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_cart_signature_with_cp_http_error_status(self):
        """Test cart signature verification with HTTP error status"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with error status
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 500
        http_client.post = AsyncMock(return_value=mock_response)

        cart_mandate = {"id": "cart_001"}
        webauthn_assertion = {}
        user_id = "user_001"

        # Should raise HTTPException
        with pytest.raises(HTTPException) as exc_info:
            await SignatureHandlers.verify_cart_signature_with_cp(
                http_client,
                "http://cp.example.com",
                cart_mandate,
                webauthn_assertion,
                user_id
            )

        assert exc_info.value.status_code == 400
        assert "WebAuthn signature verification failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_cart_signature_with_cp_connection_error(self):
        """Test cart signature verification with connection error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with connection error
        http_client = Mock(spec=httpx.AsyncClient)
        http_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

        cart_mandate = {"id": "cart_001"}
        webauthn_assertion = {}
        user_id = "user_001"

        # Should raise HTTPException with status 503
        with pytest.raises(HTTPException) as exc_info:
            await SignatureHandlers.verify_cart_signature_with_cp(
                http_client,
                "http://cp.example.com",
                cart_mandate,
                webauthn_assertion,
                user_id
            )

        assert exc_info.value.status_code == 503
        assert "Credential Provider unavailable" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_cart_signature_with_cp_unexpected_error(self):
        """Test cart signature verification with unexpected error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with unexpected error
        http_client = Mock(spec=httpx.AsyncClient)
        http_client.post = AsyncMock(side_effect=Exception("Unexpected error"))

        cart_mandate = {"id": "cart_001"}
        webauthn_assertion = {}
        user_id = "user_001"

        # Should raise HTTPException with status 500
        with pytest.raises(HTTPException) as exc_info:
            await SignatureHandlers.verify_cart_signature_with_cp(
                http_client,
                "http://cp.example.com",
                cart_mandate,
                webauthn_assertion,
                user_id
            )

        assert exc_info.value.status_code == 500
        assert "WebAuthn verification failed" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_verify_payment_attestation_with_cp_success(self):
        """Test successful payment attestation verification"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "verified": True,
            "token": "payment_token_abc",
            "details": {"counter": 2}
        }
        http_client.post = AsyncMock(return_value=mock_response)

        payment_mandate = {"id": "payment_001", "amount": "5000"}
        attestation = {"id": "attestation_001"}

        # Verify
        result = await SignatureHandlers.verify_payment_attestation_with_cp(
            http_client,
            "http://cp.example.com",
            payment_mandate,
            attestation
        )

        # Assertions
        assert result["verified"] is True
        assert result["token"] == "payment_token_abc"
        http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_verify_payment_attestation_with_cp_verification_failed(self):
        """Test payment attestation verification when verification fails"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with failed verification
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "verified": False,
            "details": {"error": "Invalid attestation"}
        }
        http_client.post = AsyncMock(return_value=mock_response)

        payment_mandate = {"id": "payment_001"}
        attestation = {}

        # Should not raise, but return failed result
        result = await SignatureHandlers.verify_payment_attestation_with_cp(
            http_client,
            "http://cp.example.com",
            payment_mandate,
            attestation
        )

        assert result["verified"] is False
        assert "error" in result["details"]

    @pytest.mark.asyncio
    async def test_verify_payment_attestation_with_cp_http_error(self):
        """Test payment attestation verification with HTTP error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with HTTP error
        http_client = Mock(spec=httpx.AsyncClient)
        http_client.post = AsyncMock(side_effect=httpx.TimeoutException("Request timeout"))

        payment_mandate = {"id": "payment_001"}
        attestation = {}

        # Should raise httpx.HTTPError
        with pytest.raises(httpx.HTTPError):
            await SignatureHandlers.verify_payment_attestation_with_cp(
                http_client,
                "http://cp.example.com",
                payment_mandate,
                attestation
            )

    @pytest.mark.asyncio
    async def test_verify_payment_attestation_with_cp_unexpected_error(self):
        """Test payment attestation verification with unexpected error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with unexpected error
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.raise_for_status = Mock(side_effect=Exception("Parsing error"))
        http_client.post = AsyncMock(return_value=mock_response)

        payment_mandate = {"id": "payment_001"}
        attestation = {}

        # Should raise Exception
        with pytest.raises(Exception):
            await SignatureHandlers.verify_payment_attestation_with_cp(
                http_client,
                "http://cp.example.com",
                payment_mandate,
                attestation
            )

    @pytest.mark.asyncio
    async def test_retrieve_public_key_from_cp_success(self):
        """Test successful public key retrieval"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {
            "public_key_cose": "base64_encoded_public_key_data"
        }
        http_client.post = AsyncMock(return_value=mock_response)

        credential_id = "credential_abc123"
        user_id = "user_001"

        # Retrieve
        result = await SignatureHandlers.retrieve_public_key_from_cp(
            http_client,
            "http://cp.example.com",
            credential_id,
            user_id
        )

        # Assertions
        assert result == "base64_encoded_public_key_data"
        http_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_retrieve_public_key_from_cp_no_credential_id(self):
        """Test public key retrieval with no credential_id"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        http_client = Mock(spec=httpx.AsyncClient)

        # Should return None without making request
        result = await SignatureHandlers.retrieve_public_key_from_cp(
            http_client,
            "http://cp.example.com",
            "",  # Empty credential_id
            "user_001"
        )

        assert result is None
        http_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_retrieve_public_key_from_cp_http_error(self):
        """Test public key retrieval with HTTP error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with HTTP error
        http_client = Mock(spec=httpx.AsyncClient)
        http_client.post = AsyncMock(side_effect=httpx.HTTPStatusError(
            "Not found",
            request=Mock(),
            response=Mock(status_code=404)
        ))

        credential_id = "credential_abc123"
        user_id = "user_001"

        # Should return None (not raise)
        result = await SignatureHandlers.retrieve_public_key_from_cp(
            http_client,
            "http://cp.example.com",
            credential_id,
            user_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_public_key_from_cp_unexpected_error(self):
        """Test public key retrieval with unexpected error"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client with unexpected error
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.side_effect = Exception("JSON parsing error")
        http_client.post = AsyncMock(return_value=mock_response)

        credential_id = "credential_abc123"
        user_id = "user_001"

        # Should return None (not raise)
        result = await SignatureHandlers.retrieve_public_key_from_cp(
            http_client,
            "http://cp.example.com",
            credential_id,
            user_id
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_retrieve_public_key_from_cp_with_custom_timeout(self):
        """Test public key retrieval with custom timeout"""
        from services.shopping_agent.utils.signature_handlers import SignatureHandlers

        # Mock HTTP client
        http_client = Mock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"public_key_cose": "test_key"}
        http_client.post = AsyncMock(return_value=mock_response)

        credential_id = "credential_abc123"
        user_id = "user_001"

        # Retrieve with custom timeout
        result = await SignatureHandlers.retrieve_public_key_from_cp(
            http_client,
            "http://cp.example.com",
            credential_id,
            user_id,
            timeout=5.0
        )

        # Verify timeout was passed
        call_args = http_client.post.call_args
        assert call_args.kwargs.get("timeout") == 5.0
        assert result == "test_key"
