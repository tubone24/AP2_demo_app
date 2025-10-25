"""
MCP (Model Context Protocol) Client

Streamable HTTP Transport準拠のMCPクライアント実装。

仕様:
- MCP Specification 2025-03-26
- Streamable HTTP transport
- JSON-RPC 2.0メッセージング
- セッション管理（Mcp-Session-Id header）
"""

import json
from typing import Dict, Any, Optional
import httpx

from common.logger import get_logger
from common.telemetry import get_tracer, create_http_span, is_telemetry_enabled

logger = get_logger(__name__, service_name='mcp_client')
tracer = get_tracer(__name__)


class MCPClient:
    """Streamable HTTP Transport準拠のMCPクライアント

    JSON-RPC 2.0でMCPサーバーと通信し、ツールを呼び出す。
    セッション管理機能を備え、ステートフルな操作をサポート。

    使用例:
        client = MCPClient(base_url="http://merchant_agent_mcp:8011")
        await client.initialize()

        result = await client.call_tool("analyze_intent", {
            "intent_mandate": {...}
        })
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 300.0,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        """
        Args:
            base_url: MCPサーバーのベースURL（例: "http://merchant_agent_mcp:8011"）
            timeout: タイムアウト時間（秒）
            http_client: 既存のhttpx.AsyncClientインスタンス（オプション）
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.http_client = http_client or httpx.AsyncClient(timeout=timeout)

        # セッション管理
        self.session_id: Optional[str] = None
        self.server_info: Optional[Dict[str, Any]] = None

        logger.info(f"[MCPClient] Initialized: {base_url}")

    async def initialize(self) -> Dict[str, Any]:
        """MCPサーバーとの接続を初期化

        initialize メソッドを呼び出し、セッションIDを取得

        Returns:
            サーバー情報と機能
        """
        response = await self._send_jsonrpc(
            method="initialize",
            params={
                "protocolVersion": "2025-03-26",
                "clientInfo": {
                    "name": "ap2_langgraph_client",
                    "version": "1.0.0"
                }
            }
        )

        self.server_info = response

        logger.info(f"[MCPClient] Initialized session: {self.session_id}")
        logger.info(f"[MCPClient] Server capabilities: {response.get('capabilities', {})}")

        return response

    async def list_tools(self) -> Dict[str, Any]:
        """利用可能なツールリストを取得

        Returns:
            {"tools": [...]}
        """
        response = await self._send_jsonrpc(
            method="tools/list",
            params={}
        )

        logger.info(f"[MCPClient] Available tools: {[t['name'] for t in response.get('tools', [])]}")
        return response

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """MCPツールを呼び出し

        Args:
            tool_name: ツール名（例: "analyze_intent"）
            arguments: ツール引数（JSON-serializable dict）

        Returns:
            ツール実行結果（JSON）

        Raises:
            httpx.HTTPError: HTTP通信エラー
            ValueError: JSON-RPCエラー
        """
        response = await self._send_jsonrpc(
            method="tools/call",
            params={
                "name": tool_name,
                "arguments": arguments
            }
        )

        # MCP仕様: content[0].textからJSONを抽出
        content = response.get("content", [])
        if content and content[0].get("type") == "text":
            result_text = content[0]["text"]
            try:
                result = json.loads(result_text)
                logger.info(f"[MCPClient] Tool {tool_name} executed successfully")
                return result
            except json.JSONDecodeError:
                logger.warning(f"[MCPClient] Tool {tool_name} returned non-JSON text")
                return {"text": result_text}

        return response

    async def _send_jsonrpc(
        self,
        method: str,
        params: Dict[str, Any],
        message_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """JSON-RPCリクエストを送信

        Args:
            method: JSON-RPCメソッド名
            params: パラメータ
            message_id: メッセージID（Noneの場合は自動生成）

        Returns:
            JSON-RPCレスポンスのresultフィールド

        Raises:
            httpx.HTTPError: HTTP通信エラー
            ValueError: JSON-RPCエラーレスポンス
        """
        # メッセージID生成
        if message_id is None:
            import random
            message_id = random.randint(1, 1000000)

        # JSON-RPCメッセージ構築
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": message_id
        }

        # HTTPヘッダー
        headers = {
            "Content-Type": "application/json"
        }

        # セッションID追加
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        # HTTP POST送信
        # OpenTelemetry 手動トレーシング: MCP通信
        try:
            with create_http_span(
                tracer,
                "POST",
                f"{self.base_url}/",
                **{
                    "mcp.method": method,
                    "mcp.message_id": message_id,
                    "rpc.system": "jsonrpc",
                    "rpc.service": "mcp"
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.base_url}/",
                    json=message,
                    headers=headers
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)

            # セッションID取得（initializeレスポンスから）
            if method == "initialize" and "Mcp-Session-Id" in response.headers:
                self.session_id = response.headers["Mcp-Session-Id"]

            # JSON-RPCレスポンス解析
            response_data = response.json()

            # エラーチェック
            if "error" in response_data:
                error = response_data["error"]
                raise ValueError(f"JSON-RPC error {error['code']}: {error['message']}")

            return response_data.get("result", {})

        except httpx.HTTPError as e:
            logger.error(f"[MCPClient] HTTP error calling {method}: {e}", exc_info=True)
            raise
        except ValueError as e:
            logger.error(f"[MCPClient] JSON-RPC error calling {method}: {e}", exc_info=True)
            raise
        except Exception as e:
            logger.error(f"[MCPClient] Unexpected error calling {method}: {e}", exc_info=True)
            raise

    async def close(self):
        """HTTPクライアントをクローズ"""
        if self.http_client:
            await self.http_client.aclose()
            logger.info("[MCPClient] Closed HTTP client")
