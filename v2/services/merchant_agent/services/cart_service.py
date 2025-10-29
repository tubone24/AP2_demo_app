"""
v2/services/merchant_agent/services/cart_service.py

CartMandate作成・管理サービス
"""

import uuid
import json
import asyncio
import httpx
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from datetime import datetime, timezone, timedelta

if TYPE_CHECKING:
    from v2.services.merchant_agent.agent import MerchantAgent

from v2.common.database import ProductCRUD
from v2.common.logger import get_logger

logger = get_logger(__name__, service_name='merchant_agent')


async def create_cart_mandate(agent: 'MerchantAgent', cart_request: Dict[str, Any]) -> Dict[str, Any]:
    """
    CartMandateを作成（未署名）

    demo_app_v2.mdの要件：
    - Merchant Agentは署名なしでCartMandateを作成
    - Merchantが署名を追加
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)

    # 商品情報を取得してCartItem作成
    cart_items = []
    subtotal_cents = 0

    async with agent.db_manager.get_session() as session:
        for item_req in cart_request["items"]:
            product = await ProductCRUD.get_by_id(session, item_req["product_id"])
            if not product:
                raise ValueError(f"Product not found: {item_req['product_id']}")

            quantity = item_req["quantity"]
            unit_price_cents = product.price
            total_price_cents = unit_price_cents * quantity

            metadata_dict = json.loads(product.product_metadata) if product.product_metadata else {}

            cart_items.append({
                "id": f"item_{uuid.uuid4().hex[:8]}",
                "name": product.name,
                "description": product.description,
                "quantity": quantity,
                "unit_price": {
                    "value": str(unit_price_cents / 100),  # centsをdollarsに
                    "currency": "JPY"
                },
                "total_price": {
                    "value": str(total_price_cents / 100),
                    "currency": "JPY"
                },
                "image_url": product.image_url,  # AP2準拠: Productモデルから直接取得
                "sku": product.sku,
                "category": metadata_dict.get("category"),
                "brand": metadata_dict.get("brand")
            })

            subtotal_cents += total_price_cents

    # 税金計算（10%）
    tax_cents = int(subtotal_cents * 0.1)

    # 送料計算（固定500円）
    shipping_cost_cents = 50000  # 500円

    # 合計
    total_cents = subtotal_cents + tax_cents + shipping_cost_cents

    # CartMandate作成
    cart_mandate = {
        "id": f"cart_{uuid.uuid4().hex[:8]}",
        "type": "CartMandate",
        "version": "0.2",
        "intent_mandate_id": cart_request["intent_mandate_id"],
        "items": cart_items,
        "subtotal": {
            "value": str(subtotal_cents / 100),
            "currency": "JPY"
        },
        "tax": {
            "value": str(tax_cents / 100),
            "currency": "JPY"
        },
        "shipping": {
            "address": cart_request["shipping_address"],
            "method": "standard",
            "cost": {
                "value": str(shipping_cost_cents / 100),
                "currency": "JPY"
            },
            "estimated_delivery": (now + timedelta(days=3)).isoformat().replace('+00:00', 'Z')
        },
        "total": {
            "value": str(total_cents / 100),
            "currency": "JPY"
        },
        "merchant_id": agent.merchant_id,
        "merchant_name": agent.merchant_name,
        "created_at": now.isoformat().replace('+00:00', 'Z'),
        "expires_at": expires_at.isoformat().replace('+00:00', 'Z'),
        # AP2仕様準拠：Merchant署名のみ（user_signatureは不要）
        "merchant_signature": None
    }

    logger.info(f"[MerchantAgent] Created CartMandate: {cart_mandate['id']}, total={cart_mandate['total']}")

    return cart_mandate


async def create_multiple_cart_candidates(
    agent: 'MerchantAgent',
    intent_mandate_id: str,
    intent_text: str,
    shipping_address: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    IntentMandateから複数のカート候補を生成

    AP2/A2A仕様準拠：
    - Merchant Agentは複数のカート候補を作成
    - 各カートはCartMandateとして構造化
    - Merchantに署名依頼してArtifactとしてラップ

    UX改善：すべてのカート候補を一気に作成し、署名依頼を並列化
    手動署名モードでは、3つの署名依頼が同時にMerchant Dashboardに表示される

    戦略：
    1. 人気順（検索結果上位3商品）
    2. 低価格順（最安値3商品）
    3. プレミアム（高価格帯3商品）
    """
    async with agent.db_manager.get_session() as session:
        # 商品検索
        products = await ProductCRUD.search(session, intent_text, limit=20)

        if not products:
            logger.warning(f"[create_multiple_cart_candidates] No products found for: {intent_text}")
            return []

        logger.info(f"[create_multiple_cart_candidates] Found {len(products)} products")

    # ステップ1: すべてのカート候補の定義を作成（署名依頼前）
    cart_definitions = []

    # 戦略1: 人気順（検索結果上位3商品、各1個ずつ）
    cart_definitions.append({
        "products": products[:3],
        "quantities": [1] * min(3, len(products)),
        "name": "人気商品セット",
        "description": "検索結果で人気の商品を組み合わせたカートです"
    })

    # 戦略2: 低価格順（最安値3商品、各1個ずつ）
    if len(products) >= 2:
        sorted_by_price = sorted(products, key=lambda p: p.price)
        cart_definitions.append({
            "products": sorted_by_price[:3],
            "quantities": [1] * min(3, len(sorted_by_price)),
            "name": "お得なセット",
            "description": "価格を抑えた組み合わせのカートです"
        })

    # 戦略3: プレミアム（高価格帯2商品、各1個ずつ）
    if len(products) >= 3:
        sorted_by_price_desc = sorted(products, key=lambda p: p.price, reverse=True)
        cart_definitions.append({
            "products": sorted_by_price_desc[:2],
            "quantities": [1] * min(2, len(sorted_by_price_desc)),
            "name": "プレミアムセット",
            "description": "高品質な商品を厳選したカートです"
        })

    logger.info(f"[create_multiple_cart_candidates] Creating {len(cart_definitions)} cart candidates")

    # ステップ2: すべてのカート候補を並列で作成・署名依頼
    # asyncio.gatherで並列実行してUX改善（一気に署名依頼が届く）
    cart_creation_tasks = [
        create_cart_from_products(
            agent=agent,
            intent_mandate_id=intent_mandate_id,
            products=cart_def["products"],
            quantities=cart_def["quantities"],
            shipping_address=shipping_address,
            cart_name=cart_def["name"],
            cart_description=cart_def["description"]
        )
        for cart_def in cart_definitions
    ]

    # 並列実行
    cart_results = await asyncio.gather(*cart_creation_tasks, return_exceptions=True)

    # 成功したカート候補のみを収集
    cart_candidates = []
    for i, result in enumerate(cart_results):
        if isinstance(result, Exception):
            logger.error(f"[create_multiple_cart_candidates] Failed to create cart {i+1}: {result}")
        elif result is not None:
            cart_candidates.append(result)

    logger.info(f"[create_multiple_cart_candidates] Created {len(cart_candidates)} cart candidates")
    return cart_candidates


async def create_cart_from_products(
    agent: 'MerchantAgent',
    intent_mandate_id: str,
    products: List[Any],
    quantities: List[int],
    shipping_address: Dict[str, Any],
    cart_name: str,
    cart_description: str
) -> Optional[Dict[str, Any]]:
    """
    商品リストからCartMandateを作成し、Merchantに署名依頼してArtifactとしてラップ

    Returns:
        Artifact形式のカートデータ（署名済みCartMandateを含む）
    """
    if not products:
        return None

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=30)

    # 1. CartItem作成と小計計算
    cart_items, subtotal_cents = agent.cart_helpers.build_cart_items_from_products(products, quantities)

    # 2. 税金、送料、合計計算
    costs = agent.cart_helpers.calculate_cart_costs(subtotal_cents)
    tax_cents = costs["tax_cents"]
    shipping_cost_cents = costs["shipping_cost_cents"]
    total_cents = costs["total_cents"]

    # CartMandate作成（未署名）
    # AP2準拠: CartContents + PaymentRequest構造
    # refs/AP2-main/src/ap2/types/mandate.py:107-135
    # refs/AP2-main/src/ap2/types/payment_request.py:184-202

    cart_id = f"cart_{uuid.uuid4().hex[:8]}"

    # PaymentItem形式でアイテムを変換
    display_items = []
    for item in cart_items:
        display_items.append({
            "label": item["name"],
            "amount": {
                "currency": "JPY",
                "value": float(item["total_price"]["value"])
            },
            "pending": False,
            "refund_period": 30
        })

    # 送料をdisplay_itemsに追加
    if shipping_cost_cents > 0:
        display_items.append({
            "label": "送料",
            "amount": {
                "currency": "JPY",
                "value": float(shipping_cost_cents / 100)
            },
            "pending": False,
            "refund_period": 0
        })

    # 税金をdisplay_itemsに追加
    if tax_cents > 0:
        display_items.append({
            "label": "消費税",
            "amount": {
                "currency": "JPY",
                "value": float(tax_cents / 100)
            },
            "pending": False,
            "refund_period": 0
        })

    # PaymentRequest.options
    payment_options = {
        "request_payer_name": False,
        "request_payer_email": False,
        "request_payer_phone": False,
        "request_shipping": shipping_address is not None,
        "shipping_type": "shipping" if shipping_address else None
    }

    # PaymentRequest.method_data (支払い方法)
    payment_method_data = [
        {
            "supported_methods": "basic-card",
            "data": {}
        }
    ]

    # PaymentRequest構造
    payment_request = {
        "method_data": payment_method_data,
        "details": {
            "id": cart_id,
            "display_items": display_items,
            "total": {
                "label": "合計",
                "amount": {
                    "currency": "JPY",
                    "value": float(total_cents / 100)
                },
                "pending": False,
                "refund_period": 30
            },
            "shipping_options": [
                {
                    "id": "standard",
                    "label": "通常配送（3日程度）",
                    "amount": {
                        "currency": "JPY",
                        "value": float(shipping_cost_cents / 100)
                    },
                    "selected": True
                }
            ] if shipping_address else None,
            "modifiers": None
        },
        "options": payment_options,
        "shipping_address": shipping_address  # AP2準拠: ContactAddress形式
    }

    # CartContents構造（AP2準拠）
    cart_contents = {
        "id": cart_id,
        "user_cart_confirmation_required": True,  # Human-Presentフロー
        "payment_request": payment_request,
        "cart_expiry": expires_at.isoformat().replace('+00:00', 'Z'),
        "merchant_name": agent.merchant_name
    }

    # CartMandate構造（AP2準拠）
    cart_mandate = {
        "contents": cart_contents,
        "merchant_authorization": None,  # Merchantが署名
        # 追加メタデータ（AP2仕様外だが、Shopping Agent UIで必要）
        "_metadata": {
            "intent_mandate_id": intent_mandate_id,
            "merchant_id": agent.merchant_id,
            "created_at": now.isoformat().replace('+00:00', 'Z'),
            "cart_name": cart_name,
            "cart_description": cart_description,
            "raw_items": cart_items  # 元のアイテム情報（互換性のため保持）
        }
    }

    # MerchantにCartMandateの署名を依頼
    try:
        response = await agent.http_client.post(
            f"{agent.merchant_url}/sign/cart",
            json={"cart_mandate": cart_mandate},
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()

        # AP2仕様準拠（specification.md:629-632, 675-678）：
        # CartMandateは必ずMerchant署名済みでなければならない
        # "The cart mandate is first signed by the merchant entity...
        #  This ensures that the user sees a cart which the merchant has confirmed to fulfill."

        # 手動署名モード：Merchantの承認を待機
        if result.get("status") == "pending_merchant_signature":
            cart_mandate_id = result.get("cart_mandate_id")
            logger.info(f"[create_cart_from_products] '{cart_name}' pending manual approval: {cart_mandate_id}")
            logger.info(f"[create_cart_from_products] Waiting for merchant signature for '{cart_name}' (max 300s)...")

            # Merchantの承認を待機（ポーリング）
            signed_cart_mandate = await wait_for_merchant_signature(
                agent=agent,
                cart_mandate_id=cart_mandate_id,
                cart_name=cart_name,  # ログ改善のためカート名を渡す
                timeout=300
            )

            if not signed_cart_mandate:
                logger.error(f"[create_cart_from_products] Failed to get merchant signature for cart: {cart_mandate_id}")
                return None

            logger.info(f"[create_cart_from_products] Merchant signature completed: {cart_mandate_id}")

            # Artifact形式でラップ（署名済み）
            artifact = {
                "artifactId": f"artifact_{uuid.uuid4().hex[:8]}",
                "name": cart_name,
                "parts": [
                    {
                        "kind": "data",
                        "data": {
                            "ap2.mandates.CartMandate": signed_cart_mandate
                        }
                    }
                ]
            }
            return artifact

        # 自動署名モード：signed_cart_mandateが即座に返される
        signed_cart_mandate = result.get("signed_cart_mandate")
        if not signed_cart_mandate:
            logger.error(f"[create_cart_from_products] Unexpected response from Merchant: {result}")
            return None

        # AP2準拠：cart_idをcontents.idから取得
        cart_id = signed_cart_mandate.get("contents", {}).get("id", "unknown")
        logger.info(f"[create_cart_from_products] CartMandate signed: {cart_id}")

        # Artifact形式でラップ
        # AP2/A2A仕様準拠：a2a-extension.md:144-229
        artifact = {
            "artifactId": f"artifact_{uuid.uuid4().hex[:8]}",
            "name": cart_name,
            "parts": [
                {
                    "kind": "data",
                    "data": {
                        "ap2.mandates.CartMandate": signed_cart_mandate
                    }
                }
            ]
        }

        return artifact

    except httpx.HTTPError as e:
        logger.error(f"[create_cart_from_products] Failed to get Merchant signature: {e}")
        return None


async def wait_for_merchant_signature(
    agent: 'MerchantAgent',
    cart_mandate_id: str,
    cart_name: str = "",
    timeout: int = 300,
    poll_interval: float = 2.0
) -> Optional[Dict[str, Any]]:
    """
    Merchantの署名を待機（ポーリング）

    AP2仕様準拠（specification.md:675-678）：
    CartMandateは必ずMerchant署名済みでなければならない

    Args:
        cart_mandate_id: CartMandate ID
        cart_name: カート名（ログ表示用）
        timeout: タイムアウト（秒）
        poll_interval: ポーリング間隔（秒）

    Returns:
        署名済みCartMandate、または失敗時にNone
    """
    cart_label = f"'{cart_name}' ({cart_mandate_id})" if cart_name else cart_mandate_id
    logger.info(f"[MerchantAgent] Waiting for merchant signature for {cart_label}, timeout={timeout}s")

    start_time = asyncio.get_event_loop().time()
    elapsed_time = 0

    while elapsed_time < timeout:
        try:
            # MerchantからCartMandateのステータスを取得
            response = await agent.http_client.get(
                f"{agent.merchant_url}/cart-mandates/{cart_mandate_id}",
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            status = result.get("status")
            payload = result.get("payload")

            logger.debug(f"[MerchantAgent] {cart_label} status: {status}")

            # 署名完了
            if status == "signed":
                logger.info(f"[MerchantAgent] {cart_label} has been signed by merchant")
                return payload

            # 拒否された
            elif status == "rejected":
                logger.warning(f"[MerchantAgent] {cart_label} has been rejected by merchant")
                return None

            # まだpending - 待機
            elif status == "pending_merchant_signature":
                logger.debug(f"[MerchantAgent] {cart_label} is still pending, waiting...")
                await asyncio.sleep(poll_interval)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                continue

            # 予期しないステータス
            else:
                logger.warning(f"[MerchantAgent] Unexpected status for {cart_label}: {status}")
                await asyncio.sleep(poll_interval)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                continue

        except httpx.HTTPError as e:
            logger.error(f"[wait_for_merchant_signature] HTTP error while checking status: {e}")
            await asyncio.sleep(poll_interval)
            elapsed_time = asyncio.get_event_loop().time() - start_time
            continue

        except Exception as e:
            logger.error(f"[wait_for_merchant_signature] Error while checking status: {e}")
            return None

    # タイムアウト
    logger.error(f"[MerchantAgent] Timeout waiting for merchant signature for {cart_label}")
    return None
