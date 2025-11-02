"""
AP2 共通ロギング設定モジュール

環境変数でログレベルを制御可能な統一ロガーを提供します。
HTTPやA2Aのペイロードは自動的にDEBUGレベルで出力されます。
"""

import logging
import os
import sys
import json
from typing import Any, Dict, Optional
from datetime import datetime


class SensitiveDataFilter(logging.Filter):
    """機密データをマスクするフィルター"""

    SENSITIVE_KEYS = {
        'password', 'passphrase', 'secret', 'api_key', 'token',
        'private_key', 'authorization', 'cookie', 'session'
    }

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードから機密データをマスク"""
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            # 既にマスク済みの場合はそのまま
            if '***MASKED***' in record.msg:
                return True

            # JSONペイロードの場合はパースして機密キーをマスク
            try:
                if record.msg.strip().startswith('{'):
                    data = json.loads(record.msg)
                    masked_data = self._mask_sensitive_data(data)
                    record.msg = json.dumps(masked_data, ensure_ascii=False, indent=2)
            except (json.JSONDecodeError, AttributeError):
                pass

        return True

    def _mask_sensitive_data(self, data: Any) -> Any:
        """再帰的に機密データをマスク"""
        if isinstance(data, dict):
            return {
                key: '***MASKED***' if key.lower() in self.SENSITIVE_KEYS
                else self._mask_sensitive_data(value)
                for key, value in data.items()
            }
        elif isinstance(data, list):
            return [self._mask_sensitive_data(item) for item in data]
        else:
            return data


class StructuredFormatter(logging.Formatter):
    """構造化ログフォーマッター（JSON出力対応）"""

    def __init__(self, json_format: bool = False):
        super().__init__()
        self.json_format = json_format

    def format(self, record: logging.LogRecord) -> str:
        """ログレコードをフォーマット"""
        if self.json_format:
            log_data = {
                'timestamp': datetime.utcnow().isoformat() + 'Z',
                'level': record.levelname,
                'logger': record.name,
                'message': record.getMessage(),
                'module': record.module,
                'function': record.funcName,
                'line': record.lineno,
            }

            # 追加フィールドがあれば含める
            if hasattr(record, 'service_name'):
                log_data['service'] = record.service_name
            if hasattr(record, 'request_id'):
                log_data['request_id'] = record.request_id
            if hasattr(record, 'user_id'):
                log_data['user_id'] = record.user_id

            # 例外情報
            if record.exc_info:
                log_data['exception'] = self.formatException(record.exc_info)

            return json.dumps(log_data, ensure_ascii=False)
        else:
            # 人間が読みやすいフォーマット
            timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
            return (
                f"[{timestamp}] {record.levelname:8s} "
                f"{record.name:30s} | {record.getMessage()}"
            )


def setup_logger(
    name: str,
    level: Optional[str] = None,
    json_format: bool = False,
    service_name: Optional[str] = None
) -> logging.Logger:
    """
    統一ロガーをセットアップ

    Args:
        name: ロガー名（通常は __name__ を渡す）
        level: ログレベル（指定なしの場合は環境変数 LOG_LEVEL を使用）
        json_format: JSON形式で出力するか（デフォルト: False）
        service_name: サービス名（ログに含める）

    Returns:
        設定済みのロガー

    環境変数:
        LOG_LEVEL: ログレベル（DEBUG/INFO/WARNING/ERROR/CRITICAL、デフォルト: INFO）
        LOG_FORMAT: ログフォーマット（json/text、デフォルト: text）
    """
    logger = logging.getLogger(name)

    # 既にハンドラーが設定されている場合はそのまま返す
    if logger.handlers:
        return logger

    # ログレベルを決定
    if level is None:
        level = os.getenv('LOG_LEVEL', 'INFO').upper()

    try:
        log_level = getattr(logging, level)
    except AttributeError:
        log_level = logging.INFO
        logger.warning(f"Invalid log level '{level}', using INFO")

    logger.setLevel(log_level)

    # フォーマットを決定
    if json_format or os.getenv('LOG_FORMAT', 'text').lower() == 'json':
        formatter = StructuredFormatter(json_format=True)
    else:
        formatter = StructuredFormatter(json_format=False)

    # コンソールハンドラーを設定
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)

    # 機密データフィルターを追加
    console_handler.addFilter(SensitiveDataFilter())

    logger.addHandler(console_handler)

    # サービス名を保存（ログに含める場合）
    if service_name:
        logger.service_name = service_name

    # 親ロガーへの伝播を防止（重複を避ける）
    logger.propagate = False

    return logger


def log_http_request(
    logger: logging.Logger,
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None
):
    """
    HTTPリクエストをログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        method: HTTPメソッド
        url: リクエストURL
        headers: リクエストヘッダー
        body: リクエストボディ
    """
    # 簡易ログ（INFO）
    logger.info(f"HTTP Request: {method} {url}")

    # 完全なペイロードとヘッダーをJSON形式で出力（DEBUG）
    if logger.isEnabledFor(logging.DEBUG):
        request_data = {
            "type": "HTTP_REQUEST",
            "method": method,
            "url": url,
            "headers": headers or {},
            "body": body
        }
        logger.debug(f"HTTP_REQUEST_RAW: {json.dumps(request_data, ensure_ascii=False, default=str)}")


def log_http_response(
    logger: logging.Logger,
    status_code: int,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Any] = None,
    duration_ms: Optional[float] = None
):
    """
    HTTPレスポンスをログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        status_code: HTTPステータスコード
        headers: レスポンスヘッダー
        body: レスポンスボディ
        duration_ms: リクエスト処理時間（ミリ秒）
    """
    # 簡易ログ（INFO）
    duration_str = f" ({duration_ms:.2f}ms)" if duration_ms else ""
    logger.info(f"HTTP Response: {status_code}{duration_str}")

    # 完全なペイロードとヘッダーをJSON形式で出力（DEBUG）
    if logger.isEnabledFor(logging.DEBUG):
        response_data = {
            "type": "HTTP_RESPONSE",
            "status_code": status_code,
            "headers": headers or {},
            "body": body,
            "duration_ms": duration_ms
        }
        logger.debug(f"HTTP_RESPONSE_RAW: {json.dumps(response_data, ensure_ascii=False, default=str)}")


def log_a2a_message(
    logger: logging.Logger,
    direction: str,
    message_type: str,
    payload: Dict[str, Any],
    peer: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
):
    """
    A2Aメッセージをログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        direction: 方向（"sent" または "received"）
        message_type: メッセージタイプ
        payload: メッセージペイロード
        peer: 通信相手
        headers: HTTPヘッダー（オプション）
    """
    # 簡易ログ（INFO）
    peer_str = f" to/from {peer}" if peer else ""
    logger.info(f"A2A Message {direction}{peer_str}: {message_type}")

    # 完全なペイロードとヘッダーをJSON形式で出力（DEBUG）
    if logger.isEnabledFor(logging.DEBUG):
        a2a_data = {
            "type": "A2A_MESSAGE",
            "direction": direction,
            "message_type": message_type,
            "peer": peer,
            "headers": headers or {},
            "payload": payload
        }
        logger.debug(f"A2A_MESSAGE_RAW: {json.dumps(a2a_data, ensure_ascii=False, default=str)}")


def log_mcp_request(
    logger: logging.Logger,
    tool_name: str,
    arguments: Dict[str, Any],
    url: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None
):
    """
    MCPリクエストをログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        tool_name: MCPツール名
        arguments: ツール引数
        url: MCPサーバーURL（オプション）
        headers: HTTPヘッダー（オプション）
    """
    # 簡易ログ（INFO）
    logger.info(f"MCP Request: {tool_name}")

    # 完全なペイロードとヘッダーをJSON形式で出力（DEBUG）
    if logger.isEnabledFor(logging.DEBUG):
        mcp_data = {
            "type": "MCP_REQUEST",
            "tool_name": tool_name,
            "url": url,
            "headers": headers or {},
            "arguments": arguments
        }
        logger.debug(f"MCP_REQUEST_RAW: {json.dumps(mcp_data, ensure_ascii=False, default=str)}")


def log_mcp_response(
    logger: logging.Logger,
    tool_name: str,
    result: Any,
    duration_ms: Optional[float] = None,
    error: Optional[str] = None
):
    """
    MCPレスポンスをログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        tool_name: MCPツール名
        result: ツール実行結果
        duration_ms: 実行時間（ミリ秒）
        error: エラーメッセージ（失敗時）
    """
    # 簡易ログ（INFO）
    duration_str = f" ({duration_ms:.2f}ms)" if duration_ms else ""
    status = "ERROR" if error else "SUCCESS"
    logger.info(f"MCP Response: {tool_name} - {status}{duration_str}")

    # 完全なペイロードをJSON形式で出力（DEBUG）
    if logger.isEnabledFor(logging.DEBUG):
        mcp_data = {
            "type": "MCP_RESPONSE",
            "tool_name": tool_name,
            "result": result,
            "error": error,
            "duration_ms": duration_ms
        }
        logger.debug(f"MCP_RESPONSE_RAW: {json.dumps(mcp_data, ensure_ascii=False, default=str)}")


def log_crypto_operation(
    logger: logging.Logger,
    operation: str,
    algorithm: str,
    key_id: Optional[str] = None,
    success: bool = True
):
    """
    暗号化操作をログ出力（INFOレベル）

    Args:
        logger: ロガーインスタンス
        operation: 操作名（"sign", "verify", "encrypt", "decrypt"）
        algorithm: アルゴリズム名
        key_id: 鍵ID
        success: 成功/失敗
    """
    status = "SUCCESS" if success else "FAILED"
    key_str = f" (key: {key_id})" if key_id else ""
    logger.info(f"Crypto {operation.upper()}: {algorithm}{key_str} - {status}")


def log_database_operation(
    logger: logging.Logger,
    operation: str,
    table: str,
    record_id: Optional[str] = None,
    duration_ms: Optional[float] = None
):
    """
    データベース操作をログ出力（DEBUGレベル）

    Args:
        logger: ロガーインスタンス
        operation: 操作名（"SELECT", "INSERT", "UPDATE", "DELETE"）
        table: テーブル名
        record_id: レコードID
        duration_ms: 処理時間（ミリ秒）
    """
    duration_str = f" ({duration_ms:.2f}ms)" if duration_ms else ""
    record_str = f" [id: {record_id}]" if record_id else ""
    logger.debug(f"DB {operation}: {table}{record_str}{duration_str}")


# デフォルトロガーを作成
default_logger = setup_logger('ap2', service_name='ap2')


# 便利なショートカット
def get_logger(name: str, service_name: Optional[str] = None) -> logging.Logger:
    """
    ロガーを取得するヘルパー関数

    Args:
        name: ロガー名（通常は __name__）
        service_name: サービス名

    Returns:
        設定済みロガー
    """
    return setup_logger(name, service_name=service_name)


class LoggingAsyncClient:
    """
    ログ記録機能付きhttpx.AsyncClientラッパー（AP2完全準拠）

    すべてのHTTP通信を自動的にログに記録し、ペイロードとヘッダーを
    JSON形式で出力します。

    使用例:
        client = LoggingAsyncClient(logger, timeout=30.0)
        response = await client.post(url, json=data)
    """

    def __init__(self, logger: logging.Logger, **kwargs):
        """
        Args:
            logger: ロガーインスタンス
            **kwargs: httpx.AsyncClientに渡す引数（timeout等）
        """
        import httpx
        self.logger = logger
        self._client = httpx.AsyncClient(**kwargs)

    async def request(self, method: str, url: str, **kwargs) -> Any:
        """
        HTTPリクエストを実行し、ログに記録

        Args:
            method: HTTPメソッド（GET, POST等）
            url: リクエストURL
            **kwargs: httpx.AsyncClient.requestに渡す引数

        Returns:
            httpx.Response
        """
        import time
        start_time = time.time()

        # リクエストボディを取得
        request_body = None
        if 'json' in kwargs:
            request_body = kwargs['json']
        elif 'data' in kwargs:
            request_body = kwargs['data']
        elif 'content' in kwargs:
            try:
                request_body = kwargs['content'].decode('utf-8') if isinstance(kwargs['content'], bytes) else kwargs['content']
            except:
                request_body = None

        # リクエストログ
        log_http_request(
            logger=self.logger,
            method=method,
            url=str(url),
            headers=kwargs.get('headers', {}),
            body=request_body
        )

        # リクエスト実行
        response = await self._client.request(method, url, **kwargs)

        # レスポンスを読み取る（AP2完全準拠: ボディを完全に読み込む）
        await response.aread()

        duration_ms = (time.time() - start_time) * 1000

        # レスポンスボディを取得
        response_body = None
        try:
            response_body = response.json()
        except Exception:
            try:
                response_body = response.text
            except Exception:
                response_body = None

        # レスポンスログ
        log_http_response(
            logger=self.logger,
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response_body,
            duration_ms=duration_ms
        )

        return response

    async def get(self, url: str, **kwargs):
        """GETリクエスト"""
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs):
        """POSTリクエスト"""
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs):
        """PUTリクエスト"""
        return await self.request("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs):
        """DELETEリクエスト"""
        return await self.request("DELETE", url, **kwargs)

    async def patch(self, url: str, **kwargs):
        """PATCHリクエスト"""
        return await self.request("PATCH", url, **kwargs)

    async def aclose(self):
        """HTTPクライアントをクローズ"""
        await self._client.aclose()

    def __getattr__(self, name):
        """その他の属性は内部クライアントに委譲"""
        return getattr(self._client, name)
