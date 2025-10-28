"""
v2/services/merchant_agent/handlers/payment_handler.py

決済リクエスト処理ハンドラー
"""

import uuid
import json as json_lib
from typing import Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from v2.services.merchant_agent.agent import MerchantAgent

import httpx
from v2.common.models import A2AMessage
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='merchant_agent')


async def handle_payment_request(agent: 'MerchantAgent', message: A2AMessage) -> Dict[str, Any]:
    """
    PaymentRequestを受信（Shopping Agentから）

    AP2仕様準拠（Step 24-25, 30-31）：
    1. Merchant AgentがShopping AgentからPaymentRequestを受信
    2. Merchant AgentがPayment ProcessorにPaymentMandateを転送（A2A通信）
    3. Payment Processorが決済処理を実行
    4. Payment ProcessorがMerchant Agentに決済結果を返却
    5. Merchant AgentがShopping Agentに決済結果を返却
    """
    logger.info("[MerchantAgent] Received PaymentRequest from Shopping Agent")
    payload = message.dataPart.payload

    payment_mandate = payload.get("payment_mandate")
    cart_mandate = payload.get("cart_mandate")

    if not payment_mandate:
        logger.error("[MerchantAgent] PaymentMandate not found in PaymentRequest")
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "missing_payment_mandate",
                "error_message": "PaymentMandate is required in PaymentRequest"
            }
        }

    try:
        # Payment ProcessorにPaymentMandateを転送（A2A通信）
        logger.info(
            f"[MerchantAgent] Forwarding PaymentMandate to Payment Processor: "
            f"payment_mandate_id={payment_mandate.get('id')}"
        )

        # A2Aメッセージを作成（署名付き）
        forward_message = agent.a2a_handler.create_response_message(
            recipient="did:ap2:agent:payment_processor",
            data_type="ap2.mandates.PaymentMandate",
            data_id=payment_mandate["id"],
            payload={
                "payment_mandate": payment_mandate,
                "cart_mandate": cart_mandate  # VDC交換
            },
            sign=True
        )

        # Payment ProcessorにA2Aメッセージを送信
        logger.info(
            f"\n{'='*80}\n"
            f"[MerchantAgent → PaymentProcessor] A2Aメッセージ転送\n"
            f"  URL: {agent.payment_processor_url}/a2a/message\n"
            f"  メッセージID: {forward_message.header.message_id}\n"
            f"  タイプ: {forward_message.dataPart.type}\n"
            f"{'='*80}"
        )

        response = await agent.http_client.post(
            f"{agent.payment_processor_url}/a2a/message",
            json=forward_message.model_dump(by_alias=True),
            timeout=30.0
        )
        response.raise_for_status()
        result = response.json()

        logger.info(
            f"\n{'='*80}\n"
            f"[MerchantAgent ← PaymentProcessor] A2Aレスポンス受信\n"
            f"  Status: {response.status_code}\n"
            f"  Response Body: {json_lib.dumps(result, ensure_ascii=False, indent=2)}\n"
            f"{'='*80}"
        )

        # Payment Processorからのレスポンスをそのままshopping agentに返却
        # AP2 Step 30-31: Payment Processor → Merchant Agent → Shopping Agent
        if isinstance(result, dict) and "dataPart" in result:
            data_part = result["dataPart"]
            response_type = data_part.get("@type") or data_part.get("type")

            if response_type == "ap2.responses.PaymentResult":
                logger.info(
                    f"[MerchantAgent] Payment processing completed, forwarding result to Shopping Agent"
                )
                # そのまま返却（Shopping Agentが期待する形式）
                return {
                    "type": "ap2.responses.PaymentResult",
                    "id": data_part.get("id", str(uuid.uuid4())),
                    "payload": data_part["payload"]
                }
            elif response_type == "ap2.errors.Error":
                logger.warning(
                    f"[MerchantAgent] Payment Processor returned error, forwarding to Shopping Agent"
                )
                return {
                    "type": "ap2.errors.Error",
                    "id": data_part.get("id", str(uuid.uuid4())),
                    "payload": data_part["payload"]
                }
            else:
                raise ValueError(f"Unexpected response type from Payment Processor: {response_type}")
        else:
            raise ValueError("Invalid response format from Payment Processor")

    except httpx.HTTPError as e:
        logger.error(f"[handle_payment_request] HTTP error: {e}")
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "payment_processor_communication_failed",
                "error_message": f"Failed to communicate with Payment Processor: {str(e)}"
            }
        }
    except Exception as e:
        logger.error(f"[handle_payment_request] Error: {e}", exc_info=True)
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "payment_request_failed",
                "error_message": str(e)
            }
        }
