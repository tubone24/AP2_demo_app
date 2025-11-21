"""
Tests for Payment Network Service (network.py)

Tests cover:
- PaymentNetworkService initialization
- Agent token generation
- Token verification
- Payment charge processing
- Network information endpoints
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock


class TestPaymentNetworkServiceInit:
    """Test PaymentNetworkService initialization"""

    @patch('services.payment_network.network.RedisClient')
    @patch('services.payment_network.network.TokenStore')
    @patch('services.payment_network.network.TokenHelpers')
    def test_service_initialization(self, mock_helpers, mock_store, mock_redis):
        """Test service initializes with correct configuration"""
        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService(network_name="TestNetwork")

        # Verify network name
        assert service.network_name == "TestNetwork"

        # Verify app was created
        assert service.app is not None

        # Verify Redis client was initialized
        mock_redis.assert_called_once()

        # Verify token helpers were initialized
        mock_helpers.assert_called_once()

    @patch('services.payment_network.network.RedisClient')
    def test_default_network_name(self, mock_redis):
        """Test default network name"""
        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService()

        assert service.network_name == "DemoPaymentNetwork"

    @patch('services.payment_network.network.RedisClient')
    def test_redis_configuration(self, mock_redis, monkeypatch):
        """Test Redis configuration from environment"""
        test_redis_url = "redis://test:6379/5"
        monkeypatch.setenv("REDIS_URL", test_redis_url)

        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService()

        # Verify Redis was called (URL will be from env or default)
        mock_redis.assert_called()


class TestTokenizeEndpoint:
    """Test agent token generation endpoint"""

    @pytest.mark.asyncio
    async def test_tokenize_success(self):
        """Test successful agent token generation"""
        from services.payment_network.network import PaymentNetworkService, TokenizeRequest
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token helpers
            mock_helpers_instance = Mock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.generate_agent_token = AsyncMock(
                return_value=(
                    "agent_tok_test_123",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
                )
            )

            service = PaymentNetworkService(network_name="TestNetwork")
            client = TestClient(service.app)

            request_data = {
                "payment_mandate": {
                    "id": "pm_test_001",
                    "payer_id": "user_001",
                    "amount": {
                        "value": "1000.00",
                        "currency": "JPY"
                    }
                },
                "payment_method_token": "tok_visa_4242"
            }

            response = client.post("/network/tokenize", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert "agent_token" in data
            assert data["network_name"] == "TestNetwork"
            assert data["token_type"] == "agent_token"

    @pytest.mark.asyncio
    async def test_tokenize_missing_payment_mandate_id(self):
        """Test tokenization fails without payment mandate ID"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            request_data = {
                "payment_mandate": {},  # Missing id
                "payment_method_token": "tok_visa_4242"
            }

            response = client.post("/network/tokenize", json=request_data)

            assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_tokenize_invalid_token_format(self):
        """Test tokenization fails with invalid token format"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService()
            client = TestClient(service.app)

            request_data = {
                "payment_mandate": {
                    "id": "pm_test_001"
                },
                "payment_method_token": "invalid_token"  # Doesn't start with tok_
            }

            response = client.post("/network/tokenize", json=request_data)

            assert response.status_code == 400


class TestVerifyTokenEndpoint:
    """Test token verification endpoint"""

    @pytest.mark.asyncio
    async def test_verify_token_success(self):
        """Test successful token verification"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token helpers
            mock_helpers_instance = Mock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(
                    True,
                    {
                        "payment_mandate_id": "pm_001",
                        "payer_id": "user_001",
                        "network_name": "TestNetwork"
                    },
                    None
                )
            )

            service = PaymentNetworkService(network_name="TestNetwork")
            client = TestClient(service.app)

            request_data = {
                "agent_token": "agent_tok_test_123"
            }

            response = client.post("/network/verify-token", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is True
            assert "token_info" in data
            assert data["token_info"]["payment_mandate_id"] == "pm_001"

    @pytest.mark.asyncio
    async def test_verify_token_invalid(self):
        """Test verification of invalid token"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token helpers
            mock_helpers_instance = Mock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(False, None, "Token not found")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            request_data = {
                "agent_token": "agent_tok_invalid"
            }

            response = client.post("/network/verify-token", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["valid"] is False
            assert data["error"] == "Token not found"


class TestChargeEndpoint:
    """Test payment charge endpoint"""

    @pytest.mark.asyncio
    async def test_charge_success(self):
        """Test successful payment charge"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token helpers
            mock_helpers_instance = Mock()
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

            request_data = {
                "agent_token": "agent_tok_test_123",
                "transaction_id": "txn_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_mandate_id": "pm_001",
                "payer_id": "user_001"
            }

            response = client.post("/network/charge", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "captured"
            assert data["transaction_id"] == "txn_001"
            assert "network_transaction_id" in data
            assert "authorization_code" in data

    @pytest.mark.asyncio
    async def test_charge_invalid_token(self):
        """Test charge fails with invalid token"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'), \
             patch('services.payment_network.network.TokenHelpers') as mock_helpers:

            # Mock token helpers
            mock_helpers_instance = Mock()
            mock_helpers.return_value = mock_helpers_instance
            mock_helpers_instance.verify_agent_token = AsyncMock(
                return_value=(False, None, "Invalid token")
            )

            service = PaymentNetworkService()
            client = TestClient(service.app)

            request_data = {
                "agent_token": "agent_tok_invalid",
                "transaction_id": "txn_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_mandate_id": "pm_001",
                "payer_id": "user_001"
            }

            response = client.post("/network/charge", json=request_data)

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "failed"
            assert "Invalid" in data["error"]


class TestHealthEndpoint:
    """Test health check endpoint"""

    def test_health_check(self):
        """Test health check returns healthy status"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService(network_name="TestNetwork")
            client = TestClient(service.app)

            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert data["service"] == "payment_network"
            assert data["network_name"] == "TestNetwork"


class TestNetworkInfoEndpoint:
    """Test network information endpoint"""

    def test_network_info(self):
        """Test network info endpoint"""
        from services.payment_network.network import PaymentNetworkService
        from fastapi.testclient import TestClient

        with patch('services.payment_network.network.RedisClient'):
            service = PaymentNetworkService(network_name="TestNetwork")
            client = TestClient(service.app)

            response = client.get("/network/info")

            assert response.status_code == 200
            data = response.json()
            assert data["network_name"] == "TestNetwork"
            assert "supported_payment_methods" in data
            assert data["tokenization_enabled"] is True
            assert data["agent_transactions_supported"] is True


class TestRequestModels:
    """Test request/response models"""

    def test_tokenize_request_model(self):
        """Test TokenizeRequest model"""
        from services.payment_network.network import TokenizeRequest

        request = TokenizeRequest(
            payment_mandate={"id": "pm_001"},
            payment_method_token="tok_test"
        )

        assert request.payment_mandate == {"id": "pm_001"}
        assert request.payment_method_token == "tok_test"

    def test_tokenize_response_model(self):
        """Test TokenizeResponse model"""
        from services.payment_network.network import TokenizeResponse

        response = TokenizeResponse(
            agent_token="agent_tok_123",
            expires_at="2025-01-01T00:00:00Z",
            network_name="TestNetwork"
        )

        assert response.agent_token == "agent_tok_123"
        assert response.network_name == "TestNetwork"
        assert response.token_type == "agent_token"

    def test_verify_token_request_model(self):
        """Test VerifyTokenRequest model"""
        from services.payment_network.network import VerifyTokenRequest

        request = VerifyTokenRequest(agent_token="agent_tok_123")

        assert request.agent_token == "agent_tok_123"

    def test_verify_token_response_model(self):
        """Test VerifyTokenResponse model"""
        from services.payment_network.network import VerifyTokenResponse

        response = VerifyTokenResponse(
            valid=True,
            token_info={"payment_mandate_id": "pm_001"}
        )

        assert response.valid is True
        assert response.token_info == {"payment_mandate_id": "pm_001"}

    def test_charge_request_model(self):
        """Test ChargeRequest model"""
        from services.payment_network.network import ChargeRequest

        request = ChargeRequest(
            agent_token="agent_tok_123",
            transaction_id="txn_001",
            amount={"value": "1000.00", "currency": "JPY"},
            payment_mandate_id="pm_001",
            payer_id="user_001"
        )

        assert request.agent_token == "agent_tok_123"
        assert request.transaction_id == "txn_001"

    def test_charge_response_model(self):
        """Test ChargeResponse model"""
        from services.payment_network.network import ChargeResponse

        response = ChargeResponse(
            status="captured",
            transaction_id="txn_001",
            network_transaction_id="net_txn_123",
            authorization_code="AUTH123"
        )

        assert response.status == "captured"
        assert response.transaction_id == "txn_001"


class TestTokenStoreIntegration:
    """Test token store integration"""

    @patch('services.payment_network.network.RedisClient')
    @patch('services.payment_network.network.TokenStore')
    def test_token_store_initialization(self, mock_store, mock_redis):
        """Test token store is initialized with correct prefix"""
        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService()

        # Verify TokenStore was called with correct prefix
        mock_store.assert_called()
        call_kwargs = mock_store.call_args[1]
        assert call_kwargs["prefix"] == "agent_token"


class TestEndpointRegistration:
    """Test endpoint registration"""

    @patch('services.payment_network.network.RedisClient')
    def test_all_endpoints_registered(self, mock_redis):
        """Test all endpoints are registered"""
        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService()

        routes = [route.path for route in service.app.routes]

        # Verify all endpoints are registered
        assert "/health" in routes
        assert "/network/tokenize" in routes
        assert "/network/verify-token" in routes
        assert "/network/info" in routes
        assert "/network/charge" in routes

    @patch('services.payment_network.network.RedisClient')
    def test_endpoint_methods(self, mock_redis):
        """Test endpoints have correct HTTP methods"""
        from services.payment_network.network import PaymentNetworkService

        service = PaymentNetworkService()

        # Create a mapping of path to methods
        routes_map = {}
        for route in service.app.routes:
            if hasattr(route, 'methods'):
                routes_map[route.path] = route.methods

        # Verify HTTP methods
        assert "GET" in routes_map.get("/health", set())
        assert "POST" in routes_map.get("/network/tokenize", set())
        assert "POST" in routes_map.get("/network/verify-token", set())
        assert "GET" in routes_map.get("/network/info", set())
        assert "POST" in routes_map.get("/network/charge", set())
