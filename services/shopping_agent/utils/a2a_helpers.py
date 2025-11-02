"""
v2/services/shopping_agent/utils/a2a_helpers.py

A2A通信関連のヘルパーメソッド
"""

import uuid
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class A2AHelpers:
    """A2A通信に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, a2a_handler, http_client, merchant_agent_url, tracer, a2a_timeout: float = 300.0):
        """
        Args:
            a2a_handler: A2Aハンドラーのインスタンス
            http_client: HTTPクライアント
            merchant_agent_url: Merchant AgentのURL
            tracer: OpenTelemetryトレーサー
            a2a_timeout: A2A通信のタイムアウト（秒）
        """
        self.a2a_handler = a2a_handler
        self.http_client = http_client
        self.merchant_agent_url = merchant_agent_url
        self.tracer = tracer
        self.a2a_timeout = a2a_timeout

    async def send_cart_request_via_a2a(
        self,
        cart_request: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        CartRequestをMerchant AgentにA2A経由で送信

        Args:
            cart_request: CartRequest

        Returns:
            Dict[str, Any]: A2Aレスポンス

        Raises:
            httpx.HTTPError: HTTP通信エラー
        """
        # A2Aメッセージを作成（署名付き）
        message = self.a2a_handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.requests.CartRequest",
            data_id=str(uuid.uuid4()),
            payload=cart_request,
            sign=True
        )

        # Merchant AgentにA2Aメッセージを送信
        import json as json_lib
        logger.info(
            f"\n{'='*80}\n"
            f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信\n"
            f"  URL: {self.merchant_agent_url}/a2a/message\n"
            f"  メッセージID: {message.header.message_id}\n"
            f"  タイプ: {message.dataPart.type}\n"
            f"  ペイロード: {json_lib.dumps(cart_request, ensure_ascii=False, indent=2)}\n"
            f"{'='*80}"
        )

        # OpenTelemetry 手動トレーシング: A2A通信
        from common.telemetry import create_http_span
        with create_http_span(
            self.tracer,
            "POST",
            f"{self.merchant_agent_url}/a2a/message",
            **{
                "a2a.message_type": "ap2.requests.CartRequest",
                "a2a.recipient": "did:ap2:agent:merchant_agent",
                "a2a.message_id": message.header.message_id
            }
        ) as span:
            response = await self.http_client.post(
                f"{self.merchant_agent_url}/a2a/message",
                json=message.model_dump(by_alias=True),
                timeout=self.a2a_timeout
            )
            response.raise_for_status()
            span.set_attribute("http.status_code", response.status_code)
            result = response.json()

        logger.info(
            f"\n{'='*80}\n"
            f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
            f"  Status: {response.status_code}\n"
            f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
            f"{'='*80}"
        )

        return result
