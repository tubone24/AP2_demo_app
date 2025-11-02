"""
v2/services/shopping_agent/utils/merchant_integration.py

Merchant Agent連携処理のヘルパーメソッド
"""

import json
import logging
import asyncio
from typing import Dict, Any, List
import httpx

logger = logging.getLogger(__name__)


class MerchantIntegrationHelpers:
    """Merchant Agent連携に関連するヘルパーメソッドを提供するクラス"""

    @staticmethod
    async def search_products_via_merchant(
        a2a_handler,
        http_client: httpx.AsyncClient,
        merchant_agent_url: str,
        intent_mandate: Dict[str, Any],
        session: Dict[str, Any],
        tracer,
        create_http_span,
        a2a_communication_timeout: float
    ) -> List[Dict[str, Any]]:
        """
        Merchant AgentにIntentMandateを送信してカート候補を取得

        Args:
            a2a_handler: A2Aメッセージハンドラー
            http_client: HTTPクライアント
            merchant_agent_url: Merchant Agent URL
            intent_mandate: IntentMandate
            session: セッション情報
            tracer: OpenTelemetryトレーサー
            create_http_span: HTTP spanヘルパー
            a2a_communication_timeout: A2A通信タイムアウト

        Returns:
            List[Dict[str, Any]]: カート候補リスト
        """
        logger.info(
            f"[MerchantIntegration] Requesting cart candidates from Merchant Agent "
            f"for IntentMandate: {intent_mandate['id']}"
        )

        try:
            # AP2仕様準拠：配送先情報を含めてMerchant Agentに送信
            shipping_address = session.get("shipping_address")

            # ペイロードにIntentMandateと配送先を含める
            payload = {
                "intent_mandate": intent_mandate,
                "shipping_address": shipping_address
            }

            # A2Aメッセージを作成（署名付き）
            message = a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",
                data_type="ap2.mandates.IntentMandate",
                data_id=intent_mandate["id"],
                payload=payload,
                sign=True
            )

            # 重要：A2AメッセージIDを保存（CartMandateとConsentから参照）
            intent_message_id = message.header.message_id
            session["intent_message_id"] = intent_message_id

            logger.info(
                f"[MerchantIntegration] Intent A2A message created: "
                f"message_id={intent_message_id}, intent_mandate_id={intent_mandate['id']}"
            )

            # Merchant AgentにA2Aメッセージを送信
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信\n"
                f"  URL: {merchant_agent_url}/a2a/message\n"
                f"  メッセージID: {message.header.message_id}\n"
                f"  タイプ: {message.dataPart.type}\n"
                f"  ペイロード: {json.dumps(intent_mandate, ensure_ascii=False, indent=2)}\n"
                f"{'='*80}"
            )

            # OpenTelemetry 手動トレーシング: A2A通信
            with create_http_span(
                tracer,
                "POST",
                f"{merchant_agent_url}/a2a/message",
                **{
                    "a2a.message_type": "ap2.mandates.IntentMandate",
                    "a2a.recipient": "did:ap2:agent:merchant_agent",
                    "a2a.message_id": message.header.message_id
                }
            ) as span:
                response = await http_client.post(
                    f"{merchant_agent_url}/a2a/message",
                    json=message.model_dump(by_alias=True),
                    timeout=a2a_communication_timeout
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Body: {json.dumps(result, ensure_ascii=False, indent=2)[:1000]}...\n"
                f"{'='*80}"
            )

            # A2AレスポンスからCart Candidatesを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                response_type = data_part.get("@type") or data_part.get("type")

                # AP2/A2A仕様準拠：CartCandidatesレスポンス
                if response_type == "ap2.responses.CartCandidates":
                    cart_candidates = data_part["payload"].get("cart_candidates", [])
                    logger.info(
                        f"[MerchantIntegration] Received {len(cart_candidates)} "
                        f"cart candidates from Merchant Agent"
                    )
                    return cart_candidates

                # 後方互換性：ProductListレスポンス（旧形式）
                elif response_type == "ap2.responses.ProductList":
                    logger.warning(
                        "[MerchantIntegration] Received ProductList (old format). "
                        "Converting to cart candidates."
                    )
                    products = data_part["payload"].get("products", [])
                    logger.info(f"[MerchantIntegration] Received {len(products)} products (old format)")
                    return products

                # エラーレスポンス
                elif response_type == "ap2.errors.Error":
                    error_payload = data_part.get("payload", {})
                    error_msg = error_payload.get("error_message", "Unknown error")
                    logger.error(f"[MerchantIntegration] Merchant Agent returned error: {error_msg}")
                    raise ValueError(f"Merchant Agent error: {error_msg}")

                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[MerchantIntegration] HTTP error: {e}")
            raise ValueError(f"Failed to search products via Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[MerchantIntegration] Error: {e}", exc_info=True)
            raise

    @staticmethod
    async def wait_for_merchant_approval(
        http_client: httpx.AsyncClient,
        merchant_url: str,
        cart_mandate_id: str,
        timeout: int,
        poll_interval: int
    ) -> Dict[str, Any]:
        """
        Merchant承認待ち（ポーリング）

        Args:
            http_client: HTTPクライアント
            merchant_url: Merchant URL
            cart_mandate_id: CartMandate ID
            timeout: タイムアウト（秒）
            poll_interval: ポーリング間隔（秒）

        Returns:
            Dict[str, Any]: 署名済みCartMandate
        """
        logger.info(
            f"[MerchantIntegration] Waiting for Merchant approval: "
            f"cart_id={cart_mandate_id}, timeout={timeout}s"
        )

        start_time = asyncio.get_event_loop().time()

        while True:
            elapsed = asyncio.get_event_loop().time() - start_time

            if elapsed > timeout:
                raise TimeoutError(
                    f"Merchant approval timeout after {timeout}s for CartMandate: {cart_mandate_id}"
                )

            try:
                # Merchantに署名済みCartMandateをポーリング
                response = await http_client.get(
                    f"{merchant_url}/cart-mandates/signed/{cart_mandate_id}",
                    timeout=10.0
                )

                if response.status_code == 200:
                    signed_cart = response.json()
                    logger.info(
                        f"[MerchantIntegration] Merchant approval received: cart_id={cart_mandate_id}"
                    )
                    return signed_cart

                elif response.status_code == 404:
                    # まだ承認されていない
                    logger.debug(
                        f"[MerchantIntegration] Cart not yet approved: cart_id={cart_mandate_id}, "
                        f"elapsed={elapsed:.1f}s"
                    )
                    await asyncio.sleep(poll_interval)
                    continue

                else:
                    raise ValueError(f"Unexpected status code from Merchant: {response.status_code}")

            except httpx.HTTPError as e:
                logger.error(f"[MerchantIntegration] HTTP error while polling: {e}")
                await asyncio.sleep(poll_interval)
                continue

    @staticmethod
    async def process_payment_via_merchant(
        a2a_handler,
        http_client: httpx.AsyncClient,
        merchant_agent_url: str,
        payment_mandate: Dict[str, Any],
        cart_mandate: Dict[str, Any],
        tracer,
        create_http_span,
        a2a_communication_timeout: float
    ) -> Dict[str, Any]:
        """
        Merchant Agent経由でPayment Processorに決済処理を依頼

        AP2 Step 24-25-30-31の完全実装:
        Step 24: Shopping Agent → Merchant Agent (A2A通信)
        Step 25: Merchant Agent → Payment Processor (A2A転送)
        Step 30: Payment Processor → Merchant Agent (決済結果)
        Step 31: Merchant Agent → Shopping Agent (決済結果転送)

        Args:
            a2a_handler: A2Aメッセージハンドラー
            http_client: HTTPクライアント
            merchant_agent_url: Merchant Agent URL
            payment_mandate: PaymentMandate
            cart_mandate: CartMandate（領収書生成に必要）
            tracer: OpenTelemetryトレーサー
            create_http_span: HTTP spanヘルパー
            a2a_communication_timeout: A2A通信タイムアウト

        Returns:
            Dict[str, Any]: 決済結果

        Raises:
            ValueError: 決済処理失敗時
        """
        logger.info(
            f"[MerchantIntegration] Requesting payment processing via Merchant Agent "
            f"for PaymentMandate: {payment_mandate['id']}"
        )

        try:
            # A2Aメッセージのペイロード：PaymentMandateとCartMandateを含める
            # VDC交換の原則：暗号的に署名されたVDCをエージェント間で交換
            payload = {
                "payment_mandate": payment_mandate,
                "cart_mandate": cart_mandate  # 領収書生成に必要
            }

            # A2Aメッセージを作成（署名付き）
            # AP2 Step 24: Merchant Agent経由での決済処理依頼
            message = a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",  # Merchant Agentに送信
                data_type="ap2.mandates.PaymentMandate",  # AP2仕様準拠: PaymentMandateを使用
                data_id=payment_mandate["id"],
                payload=payload,
                sign=True
            )

            # Merchant AgentにA2Aメッセージを送信
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → MerchantAgent] A2Aメッセージ送信（PaymentRequest）\n"
                f"  URL: {merchant_agent_url}/a2a/message\n"
                f"  メッセージID: {message.header.message_id}\n"
                f"  タイプ: {message.dataPart.type}\n"
                f"  PaymentMandate ID: {payment_mandate['id']}\n"
                f"{'='*80}"
            )

            # OpenTelemetry 手動トレーシング: A2A通信
            with create_http_span(
                tracer,
                "POST",
                f"{merchant_agent_url}/a2a/message",
                **{
                    "a2a.message_type": "ap2.mandates.PaymentMandate",
                    "a2a.recipient": "did:ap2:agent:merchant_agent",
                    "a2a.message_id": message.header.message_id
                }
            ) as span:
                response = await http_client.post(
                    f"{merchant_agent_url}/a2a/message",
                    json=message.model_dump(by_alias=True),
                    timeout=a2a_communication_timeout
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
                result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← MerchantAgent] A2Aレスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"  Response Type: {result.get('dataPart', {}).get('@type', 'unknown')}\n"
                f"{'='*80}"
            )

            # A2Aレスポンスからpayloadを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")

                if response_type == "ap2.responses.PaymentResult":
                    payload = data_part["payload"]
                    logger.info(
                        f"[MerchantIntegration] Payment processing completed: "
                        f"status={payload.get('status')}"
                    )
                    return payload
                elif response_type == "ap2.errors.Error":
                    error_payload = data_part["payload"]
                    error_msg = error_payload.get("error_message", "Unknown error")
                    logger.error(
                        f"[MerchantIntegration] Payment processing error: {error_msg}"
                    )
                    raise ValueError(f"Merchant Agent/Payment Processor error: {error_msg}")
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[MerchantIntegration] HTTP error: {e}")
            raise ValueError(f"Failed to process payment via Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[MerchantIntegration] Error: {e}", exc_info=True)
            raise

    @staticmethod
    async def request_merchant_signature(
        http_client: httpx.AsyncClient,
        merchant_url: str,
        cart_mandate: Dict[str, Any],
        signature_manager,
        timeout: float = 10.0
    ) -> Dict[str, Any]:
        """
        MerchantにCartMandateの署名を依頼

        AP2仕様準拠：
        1. Shopping AgentがCartMandateを作成（未署名）
        2. MerchantがCartMandateに署名
        3. Shopping AgentがMerchant署名を検証

        Args:
            http_client: HTTPクライアント
            merchant_url: Merchant URL
            cart_mandate: CartMandate（未署名）
            signature_manager: 署名検証用マネージャー
            timeout: リクエストタイムアウト（秒）

        Returns:
            Dict[str, Any]: 署名済みCartMandate

        Raises:
            ValueError: 署名リクエスト失敗時
        """
        logger.info(
            f"[MerchantIntegration] Requesting Merchant signature for CartMandate: "
            f"{cart_mandate['id']}"
        )

        try:
            # MerchantにPOST /sign/cartで署名依頼
            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent → Merchant] 署名リクエスト送信\n"
                f"  URL: {merchant_url}/sign/cart\n"
                f"  CartMandate ID: {cart_mandate['id']}\n"
                f"{'='*80}"
            )

            response = await http_client.post(
                f"{merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=timeout
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"\n{'='*80}\n"
                f"[ShoppingAgent ← Merchant] 署名レスポンス受信\n"
                f"  Status: {response.status_code}\n"
                f"{'='*80}"
            )

            # 署名済みCartMandateを取得
            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                raise ValueError("Merchant did not return signed_cart_mandate")

            # Merchant Authorization JWT検証（AP2完全準拠）
            merchant_authorization = signed_cart_mandate.get("merchant_authorization")
            if not merchant_authorization:
                raise ValueError("CartMandate does not contain merchant_authorization JWT")

            cart_contents = signed_cart_mandate.get("contents")
            if not cart_contents:
                raise ValueError("CartMandate does not contain contents")

            # MerchantAuthorizationJWTを使用して検証
            from common.jwt_utils import MerchantAuthorizationJWT
            jwt_verifier = MerchantAuthorizationJWT(
                signature_manager=signature_manager,
                key_manager=key_manager
            )

            try:
                # AP2完全準拠: CartMandate全体を渡す
                payload = jwt_verifier.verify(
                    jwt=merchant_authorization,
                    expected_cart_mandate=cart_mandate
                )
                logger.info(
                    f"[MerchantIntegration] ✅ Merchant authorization JWT verified for CartMandate: "
                    f"{cart_mandate['id']}, merchant={payload.get('iss')}, "
                    f"cart_hash={payload.get('cart_hash')[:16]}..."
                )
            except Exception as e:
                logger.error(f"[MerchantIntegration] Merchant authorization JWT verification failed: {e}")
                raise ValueError(f"Merchant authorization JWT verification failed: {e}")
            return signed_cart_mandate

        except httpx.HTTPError as e:
            logger.error(f"[MerchantIntegration] HTTP error: {e}")
            raise ValueError(f"Failed to request Merchant signature: {e}")
        except Exception as e:
            logger.error(f"[MerchantIntegration] Error: {e}", exc_info=True)
            raise
