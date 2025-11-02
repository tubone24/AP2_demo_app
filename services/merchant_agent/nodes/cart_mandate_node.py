"""
v2/services/merchant_agent/nodes/cart_mandate_node.py

CartMandate構築ノード（MCP経由でベース作成、Merchant署名は別途）
"""

import os
import uuid
import asyncio
from typing import TYPE_CHECKING

from common.logger import get_logger
from common.telemetry import create_http_span, get_tracer

if TYPE_CHECKING:
    from services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent, MerchantAgentState

logger = get_logger(__name__, service_name='langgraph_merchant')
tracer = get_tracer(__name__)

# CartMandate承認待機設定
MAX_CART_APPROVAL_WAIT_TIME = 270  # 秒（4.5分 - Shopping Agentの300秒タイムアウトより短く設定）
CART_APPROVAL_POLL_INTERVAL = 5    # 秒（ポーリング間隔）

# AP2ステータス定数
STATUS_PENDING_MERCHANT_SIGNATURE = "pending_merchant_signature"
STATUS_SIGNED = "signed"
STATUS_REJECTED = "rejected"

# Langfuseトレーシング設定
LANGFUSE_ENABLED = os.getenv("LANGFUSE_ENABLED", "false").lower() == "true"
langfuse_client = None

if LANGFUSE_ENABLED:
    try:
        from langfuse import Langfuse

        langfuse_client = Langfuse(
            public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
            secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
            host=os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        )
    except Exception as e:
        logger.warning(f"[Langfuse] Failed to initialize in cart_mandate_node: {e}")
        LANGFUSE_ENABLED = False


async def build_cart_mandates(agent: 'MerchantLangGraphAgent', state: 'MerchantAgentState') -> 'MerchantAgentState':
    """AP2準拠のCartMandateを構築（MCP経由でベース作成、Merchant署名は別途）"""
    cart_plans = state["cart_plans"]
    products = state["available_products"]
    shipping_address = state.get("shipping_address")  # AP2準拠: 配送先住所を取得
    intent_mandate_id = state.get("intent_mandate", {}).get("id")  # AP2準拠: IntentMandate IDを取得

    # Langfuseトレーシング（MCPツール呼び出し）
    trace_id = state.get("session_id", "unknown")

    cart_candidates = []
    pending_approval_count = 0  # 承認待ちカウント
    timeout_count = 0  # タイムアウトカウント

    # AP2完全準拠 & UX改善:
    # すべてのCartMandateを先に作成してから、一度にMerchantに署名依頼
    # これにより、手動署名モードで複数のCartMandateが同時にフロントエンドに表示される
    unsigned_cart_mandates = []  # 未署名CartMandateのリスト

    # ステップ1: すべてのCartMandateを作成（未署名）
    logger.info(f"[build_cart_mandates] Creating {len(cart_plans)} unsigned CartMandates...")

    for plan in cart_plans:
        langfuse_span = None
        try:
            # Langfuseスパン開始（可観測性向上）
            if LANGFUSE_ENABLED and langfuse_client:
                langfuse_span = langfuse_client.start_span(
                    name="mcp_build_cart_mandates",
                    input={"cart_plan": plan, "products_count": len(products)},
                    metadata={"tool": "build_cart_mandates", "mcp_server": "merchant_agent_mcp", "plan_name": plan.get("name"), "session_id": trace_id}
                )

            # MCP経由でCartMandate構築（未署名）
            result = await agent.mcp_client.call_tool("build_cart_mandates", {
                "cart_plan": plan,
                "products": products,
                "shipping_address": shipping_address,  # AP2準拠: 配送先住所を渡す
                "intent_mandate_id": intent_mandate_id  # AP2準拠: IntentMandate IDを渡す
            })

            cart_mandate = result.get("cart_mandate")

            if cart_mandate:
                unsigned_cart_mandates.append({
                    "plan": plan,
                    "cart_mandate": cart_mandate,
                    "langfuse_span": langfuse_span
                })
                logger.info(
                    f"[build_cart_mandates] Created unsigned CartMandate: "
                    f"{cart_mandate.get('contents', {}).get('id')}, plan={plan.get('name')}"
                )
            else:
                logger.warning(f"[build_cart_mandates] Failed to create CartMandate for plan: {plan.get('name')}")
                if langfuse_span:
                    langfuse_span.update(
                        output={"status": "error", "reason": "MCP returned no cart_mandate"},
                        metadata={"plan": plan}
                    )
                    langfuse_span.end()

        except Exception as e:
            logger.error(f"[build_cart_mandates] Error creating CartMandate for plan {plan.get('name')}: {e}")
            if langfuse_span:
                langfuse_span.update(
                    output={"status": "error", "reason": str(e)},
                    metadata={"plan": plan}
                )
                langfuse_span.end()

    logger.info(
        f"[build_cart_mandates] Created {len(unsigned_cart_mandates)} unsigned CartMandates, "
        f"sending to Merchant for signature..."
    )

    # ステップ2: すべてのCartMandateを **同時に** Merchantに送信（バッチ署名依頼）
    # AP2完全準拠: 手動署名モードの場合、すべてのCartMandateが同時にフロントエンドに表示される
    # asyncio.gatherを使用してすべてのHTTPリクエストを並列実行

    async def process_single_cart_mandate(item):
        """
        単一のCartMandateを処理（署名依頼 + ポーリング）

        Returns:
            tuple: (artifact_or_none, status_dict)
                - artifact_or_none: 成功時はartifact、失敗時はNone
                - status_dict: {"pending": bool, "timeout": bool, "rejected": bool}
        """
        plan = item["plan"]
        cart_mandate = item["cart_mandate"]
        langfuse_span = item["langfuse_span"]

        status_dict = {"pending": False, "timeout": False, "rejected": False}

        try:
            # Merchant署名依頼（HTTPリクエスト）
            # OpenTelemetry 手動トレーシング: Merchant通信
            with create_http_span(
                tracer,
                "POST",
                f"{agent.merchant_url}/sign/cart",
                **{
                    "merchant.cart_mandate_id": cart_mandate.get("contents", {}).get("id"),
                    "merchant.operation": "sign_cart"
                }
            ) as otel_span:
                response = await agent.http_client.post(
                    f"{agent.merchant_url}/sign/cart",
                    json={"cart_mandate": cart_mandate},
                    timeout=30.0
                )
                response.raise_for_status()
                otel_span.set_attribute("http.status_code", response.status_code)
                signed_cart_response = response.json()

            # AP2準拠：Merchantからのレスポンスを処理
            # 自動署名: signed_cart_mandate が即座に返る
            # 手動署名: status=STATUS_PENDING_MERCHANT_SIGNATURE でポーリング必要
            status = signed_cart_response.get("status")
            signed_cart_mandate = signed_cart_response.get("signed_cart_mandate")
            cart_mandate_id = signed_cart_response.get("cart_mandate_id")

            # AP2完全準拠 & LangGraphベストプラクティス:
            # 自動署名の場合はsigned_cart_mandateが即座に返されるため、ポーリング不要
            # 手動署名の場合のみポーリングループに入る
            if signed_cart_mandate:
                # 自動署名モード: 署名済みCartMandateが即座に返された
                logger.info(
                    f"[build_cart_mandates] CartMandate auto-signed: "
                    f"{cart_mandate.get('contents', {}).get('id')}, plan={plan.get('name')}"
                )
                # 後続の処理（706行目以降）で署名済みCartMandateを使用

            elif status == STATUS_PENDING_MERCHANT_SIGNATURE:
                # 手動署名モード: 承認待ちの場合、ポーリングして承認完了まで待機
                # 理由: AP2仕様では「Merchant Entity(エージェントではなく)によって署名される」必要がある
                # Merchant Agentが承認待ちをハンドリングすることで、Shopping Agentは常に署名済みCartMandateだけを受け取る
                status_dict["pending"] = True
                logger.info(
                    f"[build_cart_mandates] CartMandate pending merchant approval: "
                    f"{cart_mandate_id}, plan={plan.get('name')} - Starting polling..."
                )

                # ===== ポーリング処理: Merchant承認完了まで待機 =====
                # AP2完全準拠 & LangGraphベストプラクティス:
                # Shopping Agentのタイムアウト（300秒）より短く設定し、
                # 必ずShopping Agentにレスポンスを返せるようにする
                elapsed_time = 0

                while elapsed_time < MAX_CART_APPROVAL_WAIT_TIME:
                    await asyncio.sleep(CART_APPROVAL_POLL_INTERVAL)
                    elapsed_time += CART_APPROVAL_POLL_INTERVAL

                    logger.info(
                        f"[build_cart_mandates] Polling Merchant for approval: "
                        f"{cart_mandate_id} (elapsed: {elapsed_time}s)"
                    )

                    # AP2完全準拠: 専用ポーリングエンドポイント /poll/cart を使用
                    # cart_mandate_idのみを送信し、ステータスを取得
                    try:
                        poll_response = await agent.http_client.post(
                            f"{agent.merchant_url}/poll/cart",
                            json={"cart_mandate_id": cart_mandate_id},
                            timeout=10.0
                        )
                        poll_response.raise_for_status()
                        poll_result = poll_response.json()

                        poll_status = poll_result.get("status")
                        if poll_status == STATUS_SIGNED:
                            # 承認完了！署名済みCartMandateを取得
                            signed_cart_mandate = poll_result.get("signed_cart_mandate")
                            logger.info(
                                f"[build_cart_mandates] CartMandate approved and signed: "
                                f"{cart_mandate_id} after {elapsed_time}s"
                            )
                            break
                        elif poll_status == STATUS_PENDING_MERCHANT_SIGNATURE:
                            # まだ承認待ち、ポーリング継続
                            logger.debug(f"[build_cart_mandates] Still pending: {cart_mandate_id}")
                            continue
                        elif poll_status == STATUS_REJECTED:
                            # 拒否された
                            reason = poll_result.get("reason", "Unknown reason")
                            logger.warning(
                                f"[build_cart_mandates] CartMandate rejected: "
                                f"{cart_mandate_id}, reason={reason}"
                            )
                            status_dict["rejected"] = True
                            return (None, status_dict)
                        elif poll_status == "not_found":
                            # 未登録（想定外）
                            logger.error(f"[build_cart_mandates] CartMandate not found: {cart_mandate_id}")
                            return (None, status_dict)
                        else:
                            # 想定外のステータス
                            logger.error(f"[build_cart_mandates] Unexpected status: {poll_status}")
                            raise ValueError(f"Unexpected Merchant response status: {poll_status}")
                    except Exception as poll_error:
                        logger.warning(f"[build_cart_mandates] Polling error: {poll_error}")
                        # ポーリングエラーは無視して継続

                # タイムアウトチェック
                if elapsed_time >= MAX_CART_APPROVAL_WAIT_TIME:
                    status_dict["timeout"] = True
                    logger.warning(
                        f"[build_cart_mandates] Timeout waiting for approval ({elapsed_time}s): "
                        f"{cart_mandate_id}, plan={plan.get('name')}"
                    )
                    # タイムアウトの場合はスキップ
                    if langfuse_span:
                        langfuse_span.update(
                            output={"status": "timeout", "cart_mandate_id": cart_mandate_id},
                            metadata={"elapsed_time": elapsed_time, "reason": "Manual approval timeout", "max_wait_time": MAX_CART_APPROVAL_WAIT_TIME}
                        )
                        langfuse_span.end()
                    return (None, status_dict)

                # 承認完了、signed_cart_mandateが設定されている
                # 次のif節で処理される

            else:
                # 想定外: signed_cart_mandateもstatusもない
                logger.error(
                    f"[build_cart_mandates] Unexpected Merchant response: "
                    f"status={status}, has_signed_cart={bool(signed_cart_mandate)}"
                )
                # このCartMandateはスキップ
                if langfuse_span:
                    langfuse_span.update(
                        output={"status": "error", "reason": "Unexpected Merchant response"},
                        metadata={"response": signed_cart_response}
                    )
                    langfuse_span.end()
                return (None, status_dict)

            # AP2完全準拠: 署名済みCartMandateを処理
            # （自動署名で即座に返された、または手動署名でポーリング後に取得）
            if signed_cart_mandate:
                cart_mandate_to_use = signed_cart_mandate

            else:
                # ここに到達するのは想定外（上記のelse節でcontinueされるはず）
                raise ValueError(f"Merchant response missing 'signed_cart_mandate': {signed_cart_response}")

            # Artifact形式でラップ（A2A仕様準拠）
            artifact = {
                "artifactId": f"artifact_{uuid.uuid4().hex[:8]}",
                "name": plan.get("name", "カート"),
                "parts": [
                    {
                        "kind": "data",
                        "data": {
                            "ap2.mandates.CartMandate": cart_mandate_to_use
                        }
                    }
                ]
            }

            logger.info(f"[build_cart_mandates] Built signed CartMandate for plan: {plan.get('name')}")

            # Langfuseスパン終了（成功時）
            if langfuse_span:
                langfuse_span.update(output={"artifact_id": artifact["artifactId"], "plan_name": plan.get("name")})
                langfuse_span.end()

            return (artifact, status_dict)

        except Exception as e:
            logger.error(
                f"[build_cart_mandates] Failed to process CartMandate for plan {plan.get('name')}: {e}",
                exc_info=True
            )

            # Langfuseスパン終了（エラー時）
            if langfuse_span:
                langfuse_span.update(level="ERROR", status_message=str(e))
                langfuse_span.end()

            return (None, status_dict)

    # asyncio.gatherですべてのCartMandateを並列処理
    # AP2完全準拠: すべてのCartMandateが同時にMerchantに送信される
    logger.info(f"[build_cart_mandates] Processing {len(unsigned_cart_mandates)} CartMandates in parallel...")
    results = await asyncio.gather(
        *[process_single_cart_mandate(item) for item in unsigned_cart_mandates],
        return_exceptions=True  # 例外が発生してもすべての結果を取得
    )

    # 結果を集計
    rejected_count = 0
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"[build_cart_mandates] Exception in parallel processing: {result}")
            continue

        artifact, status = result
        if artifact:
            cart_candidates.append(artifact)
        if status.get("pending"):
            pending_approval_count += 1
        if status.get("timeout"):
            timeout_count += 1
        if status.get("rejected"):
            rejected_count += 1

    logger.info(
        f"[build_cart_mandates] Parallel processing complete: "
        f"{len(cart_candidates)} signed, {pending_approval_count} pending, "
        f"{timeout_count} timeout, {rejected_count} rejected"
    )

    # AP2完全準拠: すべてのCartMandateがタイムアウトまたはpending状態の場合の処理
    if len(cart_candidates) == 0:
        if timeout_count > 0:
            logger.warning(
                f"[build_cart_mandates] All {timeout_count} CartMandates timed out waiting for approval. "
                f"No cart candidates available."
            )
        elif pending_approval_count > 0:
            logger.warning(
                f"[build_cart_mandates] All {pending_approval_count} CartMandates are still pending approval. "
                f"No cart candidates available."
            )

    state["cart_candidates"] = cart_candidates
    logger.info(
        f"[build_cart_mandates] Built {len(cart_candidates)} signed CartMandates "
        f"(pending: {pending_approval_count}, timeout: {timeout_count})"
    )

    return state
