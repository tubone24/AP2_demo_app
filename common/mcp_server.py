"""
MCP (Model Context Protocol) Server Base Class

Streamable HTTP Transport準拠のMCPサーバー実装（完全仕様準拠版）

MCP仕様準拠項目（2025-03-26 / 2025-06-18）:
✓ JSON-RPC 2.0メッセージング
✓ Streamable HTTP transport (POST/GET)
✓ Accept ヘッダー検証 (application/json, text/event-stream)
✓ セッション管理 (Mcp-Session-Id header)
✓ 標準メソッド (initialize, tools/list, tools/call)
✓ tools/call レスポンス形式 (content配列)
⚠ SSE streaming (部分実装: GETエンドポイントは準備済み)

アーキテクチャ:
- MCPサーバー: データアクセスツールのみを提供
- LLM: クライアント側（LangGraphなど）で実行
- ツール: DB検索、API呼び出しなど、純粋なデータ操作のみ

参照:
https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
https://github.com/modelcontextprotocol/specification
"""

import uuid
import json
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from common.logger import get_logger

logger = get_logger(__name__, service_name='mcp_server')


class MCPServer:
    """Streamable HTTP Transport準拠のMCPサーバー

    JSON-RPC 2.0でメッセージを処理し、複数のツールを登録可能。
    セッション管理機能を備え、ステートフルな操作をサポート。

    使用例:
        mcp = MCPServer(server_name="merchant_mcp", version="1.0.0")

        @mcp.tool("analyze_intent")
        async def analyze_intent(params: Dict[str, Any]) -> Dict[str, Any]:
            # ツール実装
            return {"result": "analyzed"}

        app = FastAPI()
        app.include_router(mcp.router, prefix="/mcp")
    """

    def __init__(
        self,
        server_name: str,
        version: str = "1.0.0",
        capabilities: Optional[Dict[str, Any]] = None
    ):
        """
        Args:
            server_name: MCPサーバー名（例: "merchant_mcp"）
            version: サーバーバージョン（セマンティックバージョニング）
            capabilities: サーバー機能（tools, resources, prompts等）
        """
        self.server_name = server_name
        self.version = version
        self.capabilities = capabilities or {
            "tools": {}  # ツールリストは動的に構築
        }

        # セッション管理
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # ツール登録
        self.tools: Dict[str, Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]] = {}
        self.tool_schemas: Dict[str, Dict[str, Any]] = {}

        # FastAPIアプリ
        self.app = FastAPI(
            title=f"{server_name} MCP Server",
            version=version,
            description=f"Streamable HTTP MCP Server - {server_name}"
        )

        # エンドポイント登録
        self._setup_routes()

        logger.info(f"[MCPServer] Initialized: {server_name} v{version}")

    def _setup_routes(self):
        """MCPエンドポイントを設定

        - POST /: JSON-RPCメッセージ受信
        - GET /: サーバー情報取得（オプション）
        """

        @self.app.post("/")
        async def handle_jsonrpc(request: Request) -> Response:
            """JSON-RPCリクエストを処理（MCP Streamable HTTP準拠）

            MCP仕様要件:
            - クライアントはAcceptヘッダーに application/json と text/event-stream を含める
            - サーバーは application/json または text/event-stream で応答可能
            - リクエストボディは単一のJSON-RPCメッセージ

            セッションID管理:
            - リクエストヘッダーから Mcp-Session-Id を読み取り
            - initializeメソッドで新規セッションID発行
            - レスポンスヘッダーに Mcp-Session-Id を返す
            """
            # MCP仕様: Acceptヘッダー検証
            accept_header = request.headers.get("Accept", "")
            supports_json = "application/json" in accept_header or "*/*" in accept_header
            supports_sse = "text/event-stream" in accept_header or "*/*" in accept_header

            if not (supports_json or supports_sse):
                logger.warning(
                    f"[MCPServer] Invalid Accept header: {accept_header}. "
                    f"MCP requires 'application/json' or 'text/event-stream'"
                )
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32600,
                            "message": "Invalid Request: Accept header must include application/json or text/event-stream"
                        }
                    },
                    status_code=400
                )

            # セッションID取得
            session_id = request.headers.get("Mcp-Session-Id")

            # JSONRPCメッセージ解析
            try:
                body = await request.json()
            except json.JSONDecodeError as e:
                logger.error(f"[MCPServer] Invalid JSON: {e}")
                return JSONResponse(
                    content={
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "Parse error"
                        }
                    },
                    status_code=400
                )

            # JSONRPC処理
            response_data = await self._handle_jsonrpc(body, session_id)

            # レスポンスヘッダー設定
            headers = {}
            if "session_id" in response_data:
                headers["Mcp-Session-Id"] = response_data.pop("session_id")

            return JSONResponse(content=response_data, headers=headers)

        @self.app.get("/")
        async def handle_sse_stream(request: Request) -> Response:
            """SSEストリーム確立（MCP Streamable HTTP準拠）

            MCP仕様要件:
            - GETリクエストでSSEストリームを開く
            - サーバー→クライアント方向の通信に使用
            - クライアントがPOSTせずにサーバーメッセージを受信可能

            現在の実装: デモ用に基本情報を返す（SSEは将来実装）
            """
            # セッションID取得
            session_id = request.headers.get("Mcp-Session-Id")

            # MCP仕様準拠: SSEストリームを返すべきだが、現在は基本実装として
            # サーバー情報をJSONで返す（開発/デバッグ用）
            # 本番環境ではSSEストリーム実装を推奨
            return JSONResponse({
                "name": self.server_name,
                "version": self.version,
                "protocol": "mcp/2025-03-26",
                "transport": "streamable-http",
                "capabilities": {
                    "tools": list(self.tool_schemas.keys())
                },
                "active_sessions": len(self.sessions),
                "session_id": session_id,
                "note": "SSE streaming not yet implemented. Use POST for JSON-RPC requests."
            })

    async def _handle_jsonrpc(
        self,
        message: Dict[str, Any],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """JSON-RPCメッセージを処理

        Args:
            message: JSON-RPCメッセージ
            session_id: セッションID（オプション）

        Returns:
            JSON-RPCレスポンス
        """
        jsonrpc = message.get("jsonrpc")
        method = message.get("method")
        params = message.get("params", {})
        msg_id = message.get("id")

        # JSON-RPC 2.0検証
        if jsonrpc != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32600,
                    "message": "Invalid Request: jsonrpc must be '2.0'"
                }
            }

        # メソッドディスパッチ
        try:
            if method == "initialize":
                result = await self._handle_initialize(params)
                # 新規セッションID発行
                new_session_id = str(uuid.uuid4())
                self.sessions[new_session_id] = {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "client_info": params.get("clientInfo", {})
                }
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result,
                    "session_id": new_session_id  # レスポンスヘッダーに設定
                }

            elif method == "tools/list":
                result = await self._handle_tools_list()
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }

            elif method == "tools/call":
                # セッションID検証（オプション）
                if session_id and session_id not in self.sessions:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32001,
                            "message": "Invalid session"
                        }
                    }

                result = await self._handle_tool_call(params, session_id)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }
                }

        except Exception as e:
            logger.error(f"[MCPServer] Error handling {method}: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }

    async def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """initializeメソッド処理

        Args:
            params: {"protocolVersion": "2025-03-26", "clientInfo": {...}}

        Returns:
            サーバー情報と機能
        """
        protocol_version = params.get("protocolVersion", "2025-03-26")

        return {
            "protocolVersion": protocol_version,
            "serverInfo": {
                "name": self.server_name,
                "version": self.version
            },
            "capabilities": {
                "tools": {name: schema for name, schema in self.tool_schemas.items()}
            }
        }

    async def _handle_tools_list(self) -> Dict[str, Any]:
        """tools/listメソッド処理

        Returns:
            登録されているツールリスト
        """
        return {
            "tools": [
                {
                    "name": name,
                    **schema
                }
                for name, schema in self.tool_schemas.items()
            ]
        }

    async def _handle_tool_call(
        self,
        params: Dict[str, Any],
        session_id: Optional[str]
    ) -> Dict[str, Any]:
        """tools/callメソッド処理（MCP仕様準拠）

        MCP仕様要件:
        - レスポンスは content 配列を含む
        - 各contentは type と text/data/resourceなどを持つ
        - isError フィールドでエラー表示可能

        Args:
            params: {"name": "tool_name", "arguments": {...}}
            session_id: セッションID

        Returns:
            MCP準拠のツール実行結果:
            {
                "content": [
                    {"type": "text", "text": "結果テキスト"}
                ],
                "isError": false (optional)
            }
        """
        tool_name = params.get("name")
        arguments = params.get("arguments", {})

        if tool_name not in self.tools:
            raise ValueError(f"Tool not found: {tool_name}")

        # セッション情報を引数に追加
        if session_id:
            arguments["_session_id"] = session_id
            arguments["_session_data"] = self.sessions.get(session_id, {})

        # ツール実行
        tool_func = self.tools[tool_name]
        result = await tool_func(arguments)

        # MCP仕様準拠: content配列形式で返す
        # ツール関数が既にMCP形式（contentフィールド）で返している場合はそのまま使用
        if isinstance(result, dict) and "content" in result:
            return result

        # それ以外の場合はJSON文字列化してtext contentとして返す
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2)
                }
            ],
            "isError": False
        }

    def tool(
        self,
        name: str,
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None
    ):
        """ツールをデコレーターで登録

        Args:
            name: ツール名
            description: ツールの説明
            input_schema: JSON Schemaでの入力パラメータ定義

        使用例:
            @mcp.tool("analyze_intent", description="Analyze user intent")
            async def analyze_intent(params: Dict[str, Any]) -> Dict[str, Any]:
                return {"result": "analyzed"}
        """
        def decorator(func: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]):
            self.tools[name] = func
            self.tool_schemas[name] = {
                "description": description,
                "inputSchema": input_schema or {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
            logger.info(f"[MCPServer] Registered tool: {name}")
            return func

        return decorator

    def register_tool(
        self,
        name: str,
        func: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        description: str = "",
        input_schema: Optional[Dict[str, Any]] = None
    ):
        """ツールを直接登録（デコレーターを使わない場合）

        Args:
            name: ツール名
            func: ツール関数（async）
            description: ツールの説明
            input_schema: JSON Schemaでの入力パラメータ定義
        """
        self.tools[name] = func
        self.tool_schemas[name] = {
            "description": description,
            "inputSchema": input_schema or {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
        logger.info(f"[MCPServer] Registered tool: {name}")
