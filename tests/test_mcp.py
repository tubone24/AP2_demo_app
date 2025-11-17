"""
Tests for MCP Client and Server

Tests cover:
- MCPClient initialization
- MCPClient structure validation
- Basic configuration
"""

import pytest


class TestMCPClientInitialization:
    """Test MCPClient initialization"""

    def test_mcp_client_initialization(self):
        """Test MCPClient can be initialized"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Verify basic attributes
        assert client.base_url == "http://localhost:8000"
        assert client.session_id is None
        assert client.server_info is None

    def test_mcp_client_base_url_trailing_slash(self):
        """Test that trailing slash is removed from base_url"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000/")

        # Trailing slash should be removed
        assert client.base_url == "http://localhost:8000"

    def test_mcp_client_timeout(self):
        """Test MCPClient timeout configuration"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000", timeout=60.0)

        # Verify timeout is set
        assert client.timeout == 60.0

    def test_mcp_client_default_timeout(self):
        """Test MCPClient default timeout"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Default timeout should be 300.0
        assert client.timeout == 300.0


class TestMCPClientAttributes:
    """Test MCPClient attributes"""

    def test_mcp_client_has_http_client(self):
        """Test that MCPClient has http_client attribute"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Should have http_client
        assert hasattr(client, 'http_client')
        assert client.http_client is not None

    def test_mcp_client_has_session_id(self):
        """Test that MCPClient has session_id attribute"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # session_id should be None initially
        assert hasattr(client, 'session_id')
        assert client.session_id is None

    def test_mcp_client_has_server_info(self):
        """Test that MCPClient has server_info attribute"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # server_info should be None initially
        assert hasattr(client, 'server_info')
        assert client.server_info is None


class TestMCPClientMethods:
    """Test MCPClient methods exist"""

    def test_mcp_client_has_initialize_method(self):
        """Test that MCPClient has initialize method"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Should have initialize method
        assert hasattr(client, 'initialize')
        assert callable(client.initialize)

    def test_mcp_client_has_list_tools_method(self):
        """Test that MCPClient has list_tools method"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Should have list_tools method
        assert hasattr(client, 'list_tools')
        assert callable(client.list_tools)

    def test_mcp_client_has_call_tool_method(self):
        """Test that MCPClient has call_tool method"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8000")

        # Should have call_tool method
        assert hasattr(client, 'call_tool')
        assert callable(client.call_tool)


class TestMCPConfiguration:
    """Test MCP configuration"""

    def test_mcp_client_can_be_imported(self):
        """Test that MCPClient can be imported"""
        try:
            from common.mcp_client import MCPClient
            assert MCPClient is not None
        except ImportError:
            pytest.fail("MCPClient cannot be imported")

    def test_mcp_server_can_be_imported(self):
        """Test that MCP server module can be imported"""
        try:
            import common.mcp_server
            assert common.mcp_server is not None
        except ImportError:
            pytest.fail("mcp_server module cannot be imported")


class TestMCPClientURLHandling:
    """Test MCPClient URL handling"""

    def test_mcp_client_http_url(self):
        """Test MCPClient with HTTP URL"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://example.com:8000")

        assert client.base_url == "http://example.com:8000"

    def test_mcp_client_https_url(self):
        """Test MCPClient with HTTPS URL"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="https://example.com:8000")

        assert client.base_url == "https://example.com:8000"

    def test_mcp_client_localhost_url(self):
        """Test MCPClient with localhost URL"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://localhost:8011")

        assert client.base_url == "http://localhost:8011"

    def test_mcp_client_service_name_url(self):
        """Test MCPClient with service name URL (Docker)"""
        from common.mcp_client import MCPClient

        client = MCPClient(base_url="http://merchant_agent_mcp:8011")

        assert client.base_url == "http://merchant_agent_mcp:8011"


class TestMCPLogging:
    """Test MCP logging integration"""

    def test_mcp_client_uses_logger(self):
        """Test that MCPClient uses logger"""
        from common.mcp_client import MCPClient, logger

        # Logger should be defined
        assert logger is not None

    def test_mcp_client_uses_tracer(self):
        """Test that MCPClient uses tracer"""
        from common.mcp_client import MCPClient, tracer

        # Tracer should be defined
        assert tracer is not None
