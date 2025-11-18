"""
Tests for MCP Client and Server

Tests cover:
- MCPClient initialization
- MCPClient structure validation
- Basic configuration
- HTTP communication and error handling
- Tool invocation
"""

import pytest
import httpx
from unittest.mock import Mock, AsyncMock, patch
import json


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


class TestMCPClientCommunication:
    """Test MCPClient HTTP communication"""

    @pytest.mark.asyncio
    async def test_initialize_success(self):
        """Test successful initialization"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Mcp-Session-Id": "test-session-123"}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "test_server",
                    "version": "1.0.0"
                }
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        result = await client.initialize()

        assert client.session_id == "test-session-123"
        assert result["protocolVersion"] == "2025-03-26"
        assert "capabilities" in result
        mock_http.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_tools_success(self):
        """Test successful tool listing"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "tool1", "description": "Test tool 1"},
                    {"name": "tool2", "description": "Test tool 2"}
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        result = await client.list_tools()

        assert "tools" in result
        assert len(result["tools"]) == 2
        assert result["tools"][0]["name"] == "tool1"

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test successful tool call"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"status": "success", "result": "test_data"}'
                    }
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        result = await client.call_tool("test_tool", {"arg1": "value1"})

        assert result["status"] == "success"
        assert result["result"] == "test_data"

    @pytest.mark.asyncio
    async def test_call_tool_non_json_response(self):
        """Test tool call with non-JSON text response"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": "Plain text response"
                    }
                ]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        result = await client.call_tool("test_tool", {})

        assert result["text"] == "Plain text response"

    @pytest.mark.asyncio
    async def test_send_jsonrpc_with_session_id(self):
        """Test JSON-RPC request includes session ID"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {}
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)
        client.session_id = "test-session-456"

        await client._send_jsonrpc("test_method", {})

        # Verify session ID was included in headers
        call_args = mock_http.post.call_args
        assert call_args.kwargs["headers"]["Mcp-Session-Id"] == "test-session-456"

    @pytest.mark.asyncio
    async def test_jsonrpc_error_response(self):
        """Test handling of JSON-RPC error response"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        with pytest.raises(ValueError, match="JSON-RPC error -32600"):
            await client._send_jsonrpc("test_method", {})

    @pytest.mark.asyncio
    async def test_http_error_handling(self):
        """Test handling of HTTP errors"""
        from common.mcp_client import MCPClient

        # Mock HTTP client that raises HTTPError
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.post = AsyncMock(side_effect=httpx.HTTPError("Connection failed"))

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        with pytest.raises(httpx.HTTPError):
            await client._send_jsonrpc("test_method", {})

    @pytest.mark.asyncio
    async def test_close_client(self):
        """Test closing HTTP client"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_http.aclose = AsyncMock()

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        await client.close()

        mock_http.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool_empty_content(self):
        """Test tool call with empty content"""
        from common.mcp_client import MCPClient

        # Mock HTTP client
        mock_http = AsyncMock(spec=httpx.AsyncClient)
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": []
            }
        }
        mock_response.raise_for_status = Mock()
        mock_http.post = AsyncMock(return_value=mock_response)

        client = MCPClient(base_url="http://localhost:8000", http_client=mock_http)

        result = await client.call_tool("test_tool", {})

        # Should return the result as-is when content is empty
        assert result == {"content": []}


class TestMCPServer:
    """Test MCPServer"""

    def test_mcp_server_initialization(self):
        """Test MCPServer initialization"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server", version="1.0.0")

        assert server.server_name == "test_server"
        assert server.version == "1.0.0"
        assert server.tools == {}
        assert server.tool_schemas == {}
        assert server.sessions == {}

    def test_mcp_server_default_capabilities(self):
        """Test MCPServer default capabilities"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        assert "tools" in server.capabilities

    def test_mcp_server_custom_capabilities(self):
        """Test MCPServer with custom capabilities"""
        from common.mcp_server import MCPServer

        custom_caps = {"tools": {}, "resources": {}}
        server = MCPServer(server_name="test_server", capabilities=custom_caps)

        assert server.capabilities == custom_caps

    def test_mcp_server_has_fastapi_app(self):
        """Test that MCPServer creates FastAPI app"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        assert server.app is not None
        assert hasattr(server.app, 'routes')

    @pytest.mark.asyncio
    async def test_tool_decorator(self):
        """Test tool registration with decorator"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool", description="Test tool")
        async def test_func(params):
            return {"result": "test"}

        assert "test_tool" in server.tools
        assert "test_tool" in server.tool_schemas
        assert server.tool_schemas["test_tool"]["description"] == "Test tool"

    @pytest.mark.asyncio
    async def test_register_tool_method(self):
        """Test direct tool registration"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        async def test_func(params):
            return {"result": "test"}

        server.register_tool("test_tool", test_func, description="Test tool")

        assert "test_tool" in server.tools
        assert "test_tool" in server.tool_schemas

    @pytest.mark.asyncio
    async def test_handle_initialize(self):
        """Test initialize method handling"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server", version="2.0.0")

        result = await server._handle_initialize({
            "protocolVersion": "2025-03-26",
            "clientInfo": {"name": "test_client"}
        })

        assert result["protocolVersion"] == "2025-03-26"
        assert result["serverInfo"]["name"] == "test_server"
        assert result["serverInfo"]["version"] == "2.0.0"
        assert "capabilities" in result

    @pytest.mark.asyncio
    async def test_handle_tools_list_empty(self):
        """Test tools/list with no tools"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        result = await server._handle_tools_list()

        assert "tools" in result
        assert result["tools"] == []

    @pytest.mark.asyncio
    async def test_handle_tools_list_with_tools(self):
        """Test tools/list with registered tools"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("tool1", description="First tool")
        async def tool1(params):
            return {}

        @server.tool("tool2", description="Second tool")
        async def tool2(params):
            return {}

        result = await server._handle_tools_list()

        assert len(result["tools"]) == 2
        assert result["tools"][0]["name"] in ["tool1", "tool2"]
        assert result["tools"][1]["name"] in ["tool1", "tool2"]

    @pytest.mark.asyncio
    async def test_handle_tool_call_success(self):
        """Test successful tool call"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool")
        async def test_func(params):
            return {"result": params.get("input", "default")}

        result = await server._handle_tool_call({
            "name": "test_tool",
            "arguments": {"input": "test_value"}
        }, session_id=None)

        assert "content" in result
        assert result["content"][0]["type"] == "text"
        assert "test_value" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_handle_tool_call_not_found(self):
        """Test tool call with non-existent tool"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        with pytest.raises(ValueError, match="Tool not found"):
            await server._handle_tool_call({
                "name": "nonexistent_tool",
                "arguments": {}
            }, session_id=None)

    @pytest.mark.asyncio
    async def test_handle_tool_call_with_content_format(self):
        """Test tool call when tool returns MCP content format"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool")
        async def test_func(params):
            return {
                "content": [{"type": "text", "text": "Direct content"}],
                "isError": False
            }

        result = await server._handle_tool_call({
            "name": "test_tool",
            "arguments": {}
        }, session_id=None)

        assert result["content"][0]["text"] == "Direct content"
        assert result["isError"] is False

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_initialize(self):
        """Test JSON-RPC initialize message"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"}
        }, session_id=None)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert "result" in response
        assert "session_id" in response
        # Verify session was created
        assert response["session_id"] in server.sessions

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_list(self):
        """Test JSON-RPC tools/list message"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("tool1")
        async def tool1(params):
            return {}

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }, session_id=None)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 2
        assert "result" in response
        assert len(response["result"]["tools"]) == 1

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_tools_call(self):
        """Test JSON-RPC tools/call message"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool")
        async def test_func(params):
            return {"result": "success"}

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {}}
        }, session_id=None)

        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 3
        assert "result" in response
        assert "content" in response["result"]

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_invalid_version(self):
        """Test JSON-RPC with invalid version"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        response = await server._handle_jsonrpc({
            "jsonrpc": "1.0",
            "id": 1,
            "method": "initialize"
        }, session_id=None)

        assert "error" in response
        assert response["error"]["code"] == -32600

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_method_not_found(self):
        """Test JSON-RPC with unknown method"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "unknown_method"
        }, session_id=None)

        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_invalid_session(self):
        """Test tools/call with invalid session ID"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool")
        async def test_func(params):
            return {}

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "test_tool", "arguments": {}}
        }, session_id="invalid_session_id")

        assert "error" in response
        assert response["error"]["code"] == -32001

    @pytest.mark.asyncio
    async def test_handle_jsonrpc_exception_handling(self):
        """Test JSON-RPC exception handling"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        @server.tool("error_tool")
        async def error_func(params):
            raise Exception("Tool error")

        response = await server._handle_jsonrpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "error_tool", "arguments": {}}
        }, session_id=None)

        assert "error" in response
        assert response["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_tool_call_with_session_data(self):
        """Test tool call receives session data"""
        from common.mcp_server import MCPServer

        server = MCPServer(server_name="test_server")

        # Create a session
        session_id = "test-session-123"
        server.sessions[session_id] = {
            "created_at": "2024-01-01T00:00:00Z",
            "test_data": "session_value"
        }

        @server.tool("test_tool")
        async def test_func(params):
            return {
                "session_id": params.get("_session_id"),
                "session_data": params.get("_session_data")
            }

        result = await server._handle_tool_call({
            "name": "test_tool",
            "arguments": {}
        }, session_id=session_id)

        content_text = result["content"][0]["text"]
        data = json.loads(content_text)
        assert data["session_id"] == session_id
        assert data["session_data"]["test_data"] == "session_value"


class TestMCPServerHTTPEndpoints:
    """Test MCPServer HTTP endpoints with TestClient"""

    def test_http_post_initialize(self):
        """Test HTTP POST /  for initialize"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")
        client = TestClient(server.app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"}
        }, headers={"Accept": "application/json"})

        assert response.status_code == 200
        data = response.json()
        assert data["jsonrpc"] == "2.0"
        assert "result" in data
        # Session ID should be in header
        assert "Mcp-Session-Id" in response.headers

    def test_http_post_tools_list(self):
        """Test HTTP POST / for tools/list"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")

        @server.tool("test_tool")
        async def test_func(params):
            return {}

        client = TestClient(server.app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }, headers={"Accept": "application/json"})

        assert response.status_code == 200
        data = response.json()
        assert len(data["result"]["tools"]) == 1

    def test_http_post_tools_call(self):
        """Test HTTP POST / for tools/call"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")

        @server.tool("echo_tool")
        async def echo_func(params):
            return {"echo": params.get("message", "")}

        client = TestClient(server.app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "echo_tool",
                "arguments": {"message": "hello"}
            }
        }, headers={"Accept": "application/json"})

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
        assert "content" in data["result"]

    def test_http_post_invalid_accept_header(self):
        """Test HTTP POST with invalid Accept header"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")
        client = TestClient(server.app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }, headers={"Accept": "text/plain"})

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32600

    def test_http_post_invalid_json(self):
        """Test HTTP POST with invalid JSON"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")
        client = TestClient(server.app)

        response = client.post("/",
            content="invalid json{",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json"
            }
        )

        assert response.status_code == 400
        data = response.json()
        assert "error" in data
        assert data["error"]["code"] == -32700

    def test_http_get_server_info(self):
        """Test HTTP GET / for server info"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server", version="3.0.0")

        @server.tool("tool1")
        async def tool1(params):
            return {}

        @server.tool("tool2")
        async def tool2(params):
            return {}

        client = TestClient(server.app)

        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test_server"
        assert data["version"] == "3.0.0"
        assert "tool1" in data["capabilities"]["tools"]
        assert "tool2" in data["capabilities"]["tools"]

    def test_http_get_with_session_id(self):
        """Test HTTP GET / with session ID"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")
        client = TestClient(server.app)

        response = client.get("/", headers={"Mcp-Session-Id": "test-session"})

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session"

    def test_http_post_with_wildcard_accept(self):
        """Test HTTP POST with */* Accept header"""
        from common.mcp_server import MCPServer
        from fastapi.testclient import TestClient

        server = MCPServer(server_name="test_server")
        client = TestClient(server.app)

        response = client.post("/", json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {}
        }, headers={"Accept": "*/*"})

        assert response.status_code == 200
        data = response.json()
        assert "result" in data
