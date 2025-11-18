"""
Tests for Base Agent

Tests cover:
- Agent initialization
- CORS setup
- Common endpoints (health, root, agent-card)
- AgentPassphraseManager
- Key initialization
"""

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Import the actual module to test
from common.base_agent import BaseAgent, AgentPassphraseManager


class ConcreteAgent(BaseAgent):
    """Concrete implementation of BaseAgent for testing"""

    def register_a2a_handlers(self):
        """Register test handlers"""
        self.a2a_handler.register_handler(
            "test/Message",
            lambda msg: {"type": "test/Response", "id": "test", "payload": {}}
        )

    def register_endpoints(self):
        """Register test endpoints"""
        @self.app.get("/test")
        async def test_endpoint():
            return {"test": "endpoint"}

    def get_ap2_roles(self):
        """Return test roles"""
        return ["merchant", "shopper"]

    def get_agent_description(self):
        """Return test description"""
        return "Test Agent for unit testing"


class TestAgentPassphraseManager:
    """Test AgentPassphraseManager"""

    def test_get_passphrase_from_env(self):
        """Test getting passphrase from environment variable"""
        with patch.dict(os.environ, {"AP2_TEST_AGENT_PASSPHRASE": "test_passphrase"}):
            passphrase = AgentPassphraseManager.get_passphrase("test_agent")
            assert passphrase == "test_passphrase"

    def test_get_passphrase_missing_env(self):
        """Test error when environment variable is missing"""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError) as exc_info:
                AgentPassphraseManager.get_passphrase("missing_agent")
            assert "AP2_MISSING_AGENT_PASSPHRASE" in str(exc_info.value)

    def test_passphrase_env_key_format(self):
        """Test that environment key is properly formatted"""
        with patch.dict(os.environ, {"AP2_MY_AGENT_PASSPHRASE": "secret"}):
            passphrase = AgentPassphraseManager.get_passphrase("my_agent")
            assert passphrase == "secret"


class TestAgentInitialization:
    """Test agent initialization with mocked dependencies"""

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_agent_basic_initialization(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test basic agent initialization"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance

        # Mock key loading
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase",
            keys_directory="/tmp/test_keys"
        )

        # Validate initialization
        assert agent.agent_id == "did:ap2:agent:test"
        assert agent.agent_name == "Test Agent"
        assert agent.passphrase == "test_passphrase"
        assert isinstance(agent.app, FastAPI)

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_agent_cors_setup(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test CORS middleware setup"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Check that CORS middleware was added (by checking middleware stack)
        assert len(agent.app.user_middleware) > 0

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_key_initialization_success(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test successful key initialization"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent (should not raise)
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Verify keys were loaded
        assert mock_key_instance.load_private_key_encrypted.call_count == 2  # ECDSA + Ed25519

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_key_initialization_failure(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test key initialization failure"""
        # Mock KeyManager that raises error
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.side_effect = Exception("Key not found")

        # Should raise RuntimeError
        with pytest.raises(RuntimeError) as exc_info:
            ConcreteAgent(
                agent_id="did:ap2:agent:test",
                agent_name="Test Agent",
                passphrase="test_passphrase"
            )

        assert "ECDSA鍵が見つかりません" in str(exc_info.value)


class TestCommonEndpoints:
    """Test common endpoints"""

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_root_endpoint(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test root endpoint"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Test root endpoint
        client = TestClient(agent.app)
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["agent_id"] == "did:ap2:agent:test"
        assert data["agent_name"] == "Test Agent"
        assert data["status"] == "running"

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_health_endpoint(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test health endpoint"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Test health endpoint
        client = TestClient(agent.app)
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_agent_card_endpoint(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test agent card endpoint"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Test agent card endpoint
        client = TestClient(agent.app)
        response = client.get("/.well-known/agent-card.json")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Agent"
        assert data["description"] == "Test Agent for unit testing"
        assert "capabilities" in data
        assert "extensions" in data["capabilities"]

    @patch('common.base_agent.KeyManager')
    @patch('common.base_agent.SignatureManager')
    @patch('common.base_agent.A2AMessageHandler')
    @patch('common.base_agent.setup_telemetry')
    def test_custom_endpoint_registration(self, mock_telemetry, mock_a2a, mock_sig_mgr, mock_key_mgr):
        """Test that custom endpoints are registered"""
        # Mock KeyManager
        mock_key_instance = Mock()
        mock_key_mgr.return_value = mock_key_instance
        mock_key_instance.load_private_key_encrypted.return_value = None

        # Create agent
        agent = ConcreteAgent(
            agent_id="did:ap2:agent:test",
            agent_name="Test Agent",
            passphrase="test_passphrase"
        )

        # Test custom endpoint
        client = TestClient(agent.app)
        response = client.get("/test")

        assert response.status_code == 200
        data = response.json()
        assert data["test"] == "endpoint"
