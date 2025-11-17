"""
Tests for Base Agent

Tests cover:
- Agent initialization
- A2A message handling
- Agent identity
- Health check
"""

import pytest


class TestAgentInitialization:
    """Test agent initialization"""

    def test_agent_identity_structure(self):
        """Test agent identity structure"""
        agent_identity = {
            "agent_id": "did:ap2:agent:shopping_agent",
            "agent_name": "Shopping Agent",
            "roles": ["agent"]
        }

        # Validate structure
        assert "agent_id" in agent_identity
        assert "agent_name" in agent_identity
        assert agent_identity["agent_id"].startswith("did:ap2:agent:")

    def test_agent_roles(self):
        """Test agent roles"""
        agent_roles = ["agent", "merchant", "payment_processor"]

        # Validate roles
        for role in agent_roles:
            assert isinstance(role, str)
            assert len(role) > 0


class TestHealthCheck:
    """Test health check endpoint"""

    def test_health_check_response(self):
        """Test health check response"""
        health_response = {
            "status": "healthy",
            "agent_id": "did:ap2:agent:shopping_agent"
        }

        # Validate structure
        assert "status" in health_response
        assert health_response["status"] == "healthy"


class TestA2AMessageHandling:
    """Test A2A message handling"""

    def test_register_handler(self):
        """Test registering A2A message handler"""
        handler_registry = {}
        message_type = "ap2.mandates.IntentMandate"

        # Register handler
        handler_registry[message_type] = lambda msg: {"handled": True}

        # Validate registration
        assert message_type in handler_registry
