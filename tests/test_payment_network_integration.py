"""
Tests for Payment Network integration (based on test_network.py)

Tests cover:
- Health check endpoint
- Network info endpoint
- Agent token issuance
- Token verification
- Full tokenization flow
"""

import pytest
from unittest.mock import patch, AsyncMock


class TestPaymentNetworkIntegration:
    """Integration tests for Payment Network Service"""

    @pytest.mark.asyncio
    async def test_health_check_integration(self):
        """Test health check endpoint returns correct structure"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()

            # Verify response structure
            assert "status" in data
            assert "service" in data
            assert "network_name" in data
            assert "timestamp" in data

            # Verify values
            assert data["status"] == "healthy"
            assert data["service"] == "payment_network"

    @pytest.mark.asyncio
    async def test_network_info_integration(self):
        """Test network info endpoint returns correct structure"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            response = client.get("/network/info")

            assert response.status_code == 200
            data = response.json()

            # Verify response structure
            assert "network_name" in data
            assert "supported_payment_methods" in data
            assert "tokenization_enabled" in data
            assert "agent_transactions_supported" in data
            assert "timestamp" in data

            # Verify values
            assert isinstance(data["supported_payment_methods"], list)
            assert data["tokenization_enabled"] is True
            assert data["agent_transactions_supported"] is True

    @pytest.mark.asyncio
    async def test_agent_token_issuance_flow(self):
        """Test complete agent token issuance flow"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient
        from datetime import datetime, timezone, timedelta

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token generation
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.generate_agent_token = AsyncMock(
                return_value=(
                    "agent_tok_test_001",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            # Step 1: Issue agent token
            tokenize_request = {
                "payment_mandate": {
                    "id": "pm_test_001",
                    "payer_id": "user_demo_001",
                    "amount": {
                        "value": "10000.00",
                        "currency": "JPY"
                    }
                },
                "attestation": {
                    "type": "passkey",
                    "verified": True
                },
                "payment_method_token": "tok_visa_4242",
                "transaction_context": {
                    "test": True
                }
            }

            response = client.post("/network/tokenize", json=tokenize_request)

            assert response.status_code == 200
            data = response.json()

            # Verify tokenization response
            assert "agent_token" in data
            assert "expires_at" in data
            assert "network_name" in data
            assert "token_type" in data

            assert data["token_type"] == "agent_token"
            agent_token = data["agent_token"]

            # Step 2: Verify the issued token
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(
                    True,
                    {
                        "payment_mandate_id": "pm_test_001",
                        "payer_id": "user_demo_001",
                        "network_name": service.network_name
                    },
                    None
                )
            )

            verify_request = {
                "agent_token": agent_token
            }

            response = client.post("/network/verify-token", json=verify_request)

            assert response.status_code == 200
            data = response.json()

            # Verify token verification response
            assert data["valid"] is True
            assert "token_info" in data
            assert data["token_info"]["payment_mandate_id"] == "pm_test_001"

    @pytest.mark.asyncio
    async def test_tokenization_with_attestation(self):
        """Test tokenization with device attestation"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient
        from datetime import datetime, timezone, timedelta

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token generation
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.generate_agent_token = AsyncMock(
                return_value=(
                    "agent_tok_with_attestation",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            # Request with attestation
            tokenize_request = {
                "payment_mandate": {
                    "id": "pm_test_002",
                    "payer_id": "user_demo_001",
                    "amount": {
                        "value": "5000.00",
                        "currency": "JPY"
                    }
                },
                "attestation": {
                    "type": "passkey",
                    "verified": True,
                    "authenticator_data": "mock_data"
                },
                "payment_method_token": "tok_visa_4242"
            }

            response = client.post("/network/tokenize", json=tokenize_request)

            assert response.status_code == 200
            data = response.json()

            assert "agent_token" in data
            assert data["agent_token"] == "agent_tok_with_attestation"

    @pytest.mark.asyncio
    async def test_invalid_payment_method_token(self):
        """Test tokenization fails with invalid payment method token"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            # Request with invalid token (doesn't start with tok_)
            tokenize_request = {
                "payment_mandate": {
                    "id": "pm_test_003",
                    "payer_id": "user_demo_001",
                    "amount": {
                        "value": "1000.00",
                        "currency": "JPY"
                    }
                },
                "payment_method_token": "invalid_token_format"
            }

            response = client.post("/network/tokenize", json=tokenize_request)

            assert response.status_code == 400
            assert "Invalid payment_method_token format" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_tokenization_without_mandate_id(self):
        """Test tokenization fails without payment mandate ID"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            # Request without mandate ID
            tokenize_request = {
                "payment_mandate": {
                    # Missing "id" field
                    "payer_id": "user_demo_001",
                    "amount": {
                        "value": "1000.00",
                        "currency": "JPY"
                    }
                },
                "payment_method_token": "tok_visa_4242"
            }

            response = client.post("/network/tokenize", json=tokenize_request)

            assert response.status_code == 400
            assert "Missing payment_mandate.id" in response.json()["detail"]


class TestPaymentCharge:
    """Test payment charge functionality"""

    @pytest.mark.asyncio
    async def test_charge_with_valid_token(self):
        """Test payment charge with valid agent token"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token verification
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(
                    True,
                    {"payment_mandate_id": "pm_001"},
                    None
                )
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            charge_request = {
                "agent_token": "agent_tok_valid",
                "transaction_id": "txn_test_001",
                "amount": {
                    "value": "10000.00",
                    "currency": "JPY"
                },
                "payment_mandate_id": "pm_001",
                "payer_id": "user_demo_001"
            }

            response = client.post("/network/charge", json=charge_request)

            assert response.status_code == 200
            data = response.json()

            # Verify charge response
            assert data["status"] == "captured"
            assert data["transaction_id"] == "txn_test_001"
            assert "network_transaction_id" in data
            assert "authorization_code" in data

            # Verify network transaction ID format
            assert data["network_transaction_id"].startswith("net_txn_")

            # Verify authorization code format
            assert data["authorization_code"].startswith("AUTH")

    @pytest.mark.asyncio
    async def test_charge_with_invalid_token(self):
        """Test payment charge with invalid agent token"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token verification failure
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(False, None, "Token expired")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            charge_request = {
                "agent_token": "agent_tok_invalid",
                "transaction_id": "txn_test_002",
                "amount": {
                    "value": "5000.00",
                    "currency": "JPY"
                },
                "payment_mandate_id": "pm_002",
                "payer_id": "user_demo_001"
            }

            response = client.post("/network/charge", json=charge_request)

            assert response.status_code == 200
            data = response.json()

            # Verify charge failed
            assert data["status"] == "failed"
            assert "Invalid agent token" in data["error"]

    @pytest.mark.asyncio
    async def test_charge_generates_unique_ids(self):
        """Test charge generates unique transaction and authorization IDs"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token verification
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(True, {"payment_mandate_id": "pm_001"}, None)
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            # Make multiple charge requests
            network_txn_ids = []
            auth_codes = []

            for i in range(3):
                charge_request = {
                    "agent_token": "agent_tok_valid",
                    "transaction_id": f"txn_test_{i:03d}",
                    "amount": {"value": "1000.00", "currency": "JPY"},
                    "payment_mandate_id": "pm_001",
                    "payer_id": "user_demo_001"
                }

                response = client.post("/network/charge", json=charge_request)
                data = response.json()

                network_txn_ids.append(data["network_transaction_id"])
                auth_codes.append(data["authorization_code"])

            # Verify all IDs are unique
            assert len(set(network_txn_ids)) == 3
            assert len(set(auth_codes)) == 3


class TestErrorHandling:
    """Test error handling"""

    @pytest.mark.asyncio
    async def test_tokenize_error_handling(self):
        """Test tokenization error handling"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token generation to raise exception
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.generate_agent_token = AsyncMock(
                side_effect=Exception("Token generation failed")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            tokenize_request = {
                "payment_mandate": {
                    "id": "pm_test_001",
                    "payer_id": "user_001",
                    "amount": {"value": "1000.00", "currency": "JPY"}
                },
                "payment_method_token": "tok_visa_4242"
            }

            response = client.post("/network/tokenize", json=tokenize_request)

            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_verify_token_error_handling(self):
        """Test token verification error handling"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token verification to raise exception
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                side_effect=Exception("Verification failed")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            verify_request = {
                "agent_token": "agent_tok_test"
            }

            response = client.post("/network/verify-token", json=verify_request)

            assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_charge_error_handling(self):
        """Test charge error handling"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token verification to raise exception
            mock_helpers_instance = AsyncMock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                side_effect=Exception("Verification failed")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            charge_request = {
                "agent_token": "agent_tok_test",
                "transaction_id": "txn_001",
                "amount": {"value": "1000.00", "currency": "JPY"},
                "payment_mandate_id": "pm_001",
                "payer_id": "user_001"
            }

            response = client.post("/network/charge", json=charge_request)

            # Charge endpoint catches exceptions and returns failed status
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "failed"
