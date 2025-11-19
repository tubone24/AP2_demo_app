"""
Tests for Payment Network Utils

Tests cover:
- token_helpers.py (payment_network)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch


# ============================================================================
# Payment Network Token Helpers Tests
# ============================================================================


class TestTokenHelpers:
    """Test payment_network token helpers"""

    @pytest.mark.asyncio
    async def test_generate_agent_token(self):
        """Test agent token generation"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        # Mock TokenStore
        token_store = Mock()
        token_store.save_token = AsyncMock(return_value=True)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        payment_mandate = {
            "id": "payment_mandate_123",
            "payer_id": "user_001",
            "amount": {"value": "10000", "currency": "JPY"}
        }
        payment_method_token = "pm_token_abc123"
        attestation_verified = True

        # Generate token
        agent_token, expires_at_iso = await helpers.generate_agent_token(
            payment_mandate,
            payment_method_token,
            attestation_verified,
            expiry_hours=2
        )

        # Verify token format
        assert agent_token.startswith("agent_tok_testnetwork_")
        assert len(agent_token) > 32

        # Verify expires_at is an ISO timestamp
        assert expires_at_iso.endswith("Z") or "+" in expires_at_iso

        # Verify save_token was called
        token_store.save_token.assert_called_once()
        call_args = token_store.save_token.call_args

        # Verify token data
        token_data = call_args[0][1]
        assert token_data["payment_mandate_id"] == "payment_mandate_123"
        assert token_data["payment_method_token"] == "pm_token_abc123"
        assert token_data["payer_id"] == "user_001"
        assert token_data["network_name"] == "TestNetwork"
        assert token_data["attestation_verified"] is True

        # Verify TTL
        ttl_seconds = call_args[1]["ttl_seconds"]
        assert ttl_seconds == 2 * 3600  # 2 hours

    @pytest.mark.asyncio
    async def test_generate_agent_token_default_expiry(self):
        """Test agent token generation with default expiry"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()
        token_store.save_token = AsyncMock(return_value=True)

        helpers = TokenHelpers(network_name="TestNet", token_store=token_store)

        payment_mandate = {"id": "pm_001", "payer_id": "user_002", "amount": {}}
        payment_method_token = "pm_token"

        # Use default expiry (1 hour)
        agent_token, expires_at_iso = await helpers.generate_agent_token(
            payment_mandate,
            payment_method_token,
            attestation_verified=False
        )

        # Verify default TTL
        call_args = token_store.save_token.call_args
        ttl_seconds = call_args[1]["ttl_seconds"]
        assert ttl_seconds == 3600  # 1 hour default

    @pytest.mark.asyncio
    async def test_verify_agent_token_success(self):
        """Test successful agent token verification"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()

        # Mock token data
        now = datetime.now(timezone.utc)
        future = now + timedelta(hours=1)
        token_data = {
            "payment_mandate_id": "pm_123",
            "payment_method_token": "pm_token_abc",
            "payer_id": "user_001",
            "amount": {"value": "10000", "currency": "JPY"},
            "network_name": "TestNetwork",
            "issued_at": now.isoformat(),
            "expires_at": future.isoformat()
        }

        token_store.get_token = AsyncMock(return_value=token_data)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        # Verify token
        valid, token_info, error = await helpers.verify_agent_token("agent_tok_test_123")

        # Should be valid
        assert valid is True
        assert error is None
        assert token_info is not None

        # Verify token info structure
        assert token_info["payment_mandate_id"] == "pm_123"
        assert token_info["payer_id"] == "user_001"
        assert token_info["network_name"] == "TestNetwork"

    @pytest.mark.asyncio
    async def test_verify_agent_token_not_found(self):
        """Test agent token verification when token not found"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()
        token_store.get_token = AsyncMock(return_value=None)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        # Verify non-existent token
        valid, token_info, error = await helpers.verify_agent_token("invalid_token")

        # Should be invalid
        assert valid is False
        assert token_info is None
        assert error == "Agent Token not found"

    @pytest.mark.asyncio
    async def test_verify_agent_token_expired(self):
        """Test agent token verification when token is expired"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()

        # Mock expired token data
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=2)  # Expired 2 hours ago
        token_data = {
            "payment_mandate_id": "pm_123",
            "payment_method_token": "pm_token_abc",
            "payer_id": "user_001",
            "amount": {},
            "network_name": "TestNetwork",
            "issued_at": past.isoformat(),
            "expires_at": (now - timedelta(hours=1)).isoformat()  # Expired 1 hour ago
        }

        token_store.get_token = AsyncMock(return_value=token_data)
        token_store.delete_token = AsyncMock(return_value=True)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        # Verify expired token
        valid, token_info, error = await helpers.verify_agent_token("expired_token")

        # Should be invalid
        assert valid is False
        assert token_info is None
        assert error == "Agent Token expired"

        # Verify token was deleted
        token_store.delete_token.assert_called_once_with("expired_token")

    @pytest.mark.asyncio
    async def test_verify_agent_token_edge_case_just_expired(self):
        """Test agent token verification at exact expiry boundary"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()

        # Mock token data that expires exactly now
        now = datetime.now(timezone.utc)
        token_data = {
            "payment_mandate_id": "pm_123",
            "payment_method_token": "pm_token",
            "payer_id": "user_001",
            "amount": {},
            "network_name": "TestNetwork",
            "issued_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now - timedelta(microseconds=1)).isoformat()  # Just expired
        }

        token_store.get_token = AsyncMock(return_value=token_data)
        token_store.delete_token = AsyncMock(return_value=True)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        # Verify just-expired token
        valid, token_info, error = await helpers.verify_agent_token("edge_token")

        # Should be invalid
        assert valid is False
        assert error == "Agent Token expired"

    @pytest.mark.asyncio
    async def test_token_uniqueness(self):
        """Test that generated tokens are unique"""
        from services.payment_network.utils.token_helpers import TokenHelpers

        token_store = Mock()
        token_store.save_token = AsyncMock(return_value=True)

        helpers = TokenHelpers(network_name="TestNetwork", token_store=token_store)

        payment_mandate = {"id": "pm_001", "payer_id": "user_001", "amount": {}}
        payment_method_token = "pm_token"

        # Generate multiple tokens
        tokens = set()
        for _ in range(10):
            agent_token, _ = await helpers.generate_agent_token(
                payment_mandate,
                payment_method_token,
                attestation_verified=True
            )
            tokens.add(agent_token)

        # All tokens should be unique
        assert len(tokens) == 10
