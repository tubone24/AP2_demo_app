"""
v2/services/merchant_agent/agent.py

Merchant Agent実装
- 商品検索（データベースから）
- CartMandate作成（未署名）
- Merchantへの署名依頼（A2A経由）
"""

import sys
import uuid
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
import logging

import httpx
from fastapi import HTTPException

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage
from v2.common.database import DatabaseManager, ProductCRUD
from v2.common.seed_data import seed_products, seed_users

logger = logging.getLogger(__name__)


class MerchantAgent(BaseAgent):
    """
    Merchant Agent

    商店の代理エージェント
    - 商品検索
    - CartMandate作成（未署名）
    - Merchantへの署名依頼
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:agent:merchant_agent",
            agent_name="Merchant Agent",
            passphrase=AgentPassphraseManager.get_passphrase("merchant_agent"),
            keys_directory="./keys"
        )

        # データベースマネージャー（環境変数から読み込み、絶対パスを使用）
        import os
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/merchant_agent.db")
        self.db_manager = DatabaseManager(database_url=database_url)

        # HTTPクライアント（Merchantとの通信用）
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Merchantエンドポイント（Docker Compose環境想定）
        self.merchant_url = "http://merchant:8002"

        # このMerchantの情報（固定）
        self.merchant_id = "did:ap2:merchant:demo_merchant"
        self.merchant_name = "AP2デモストア"

        # 起動イベントハンドラー登録
        @self.app.on_event("startup")
        async def startup_event():
            """起動時の初期化処理"""
            logger.info(f"[{self.agent_name}] Running startup tasks...")

            # データベース初期化
            await self.db_manager.init_db()
            logger.info(f"[{self.agent_name}] Database initialized")

            # サンプルデータシード
            try:
                await seed_products(self.db_manager)
                await seed_users(self.db_manager)
                logger.info(f"[{self.agent_name}] Sample data seeded successfully")
            except Exception as e:
                logger.warning(f"[{self.agent_name}] Sample data seeding warning: {e}")

        logger.info(f"[{self.agent_name}] Initialized")

    def get_ap2_roles(self) -> list[str]:
        """AP2でのロールを返す"""
        return ["merchant"]

    def get_agent_description(self) -> str:
        """エージェントの説明を返す"""
        return "Merchant Agent for AP2 Protocol - handles product catalog, cart creation, and merchant signature requests"

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Merchant Agentが受信するA2Aメッセージ：
        - ap2/IntentMandate: Shopping Agentからの購入意図
        - ap2/ProductSearchRequest: 商品検索依頼
        - ap2/CartRequest: Shopping Agentからのカート作成・署名依頼
        """
        self.a2a_handler.register_handler("ap2.mandates.IntentMandate", self.handle_intent_mandate)
        self.a2a_handler.register_handler("ap2.requests.ProductSearch", self.handle_product_search_request)
        self.a2a_handler.register_handler("ap2.requests.CartRequest", self.handle_cart_request)

    def register_endpoints(self):
        """
        Merchant Agent固有エンドポイントの登録
        """

        @self.app.get("/search")
        async def search_products(query: str = "", category: Optional[str] = None, limit: int = 10):
            """
            GET /search - 商品検索

            パラメータ:
            - query: 検索クエリ（名前または説明で部分一致）
            - category: カテゴリーフィルター
            - limit: 結果数上限
            """
            try:
                async with self.db_manager.get_session() as session:
                    if query:
                        products = await ProductCRUD.search(session, query, limit)
                    else:
                        products = await ProductCRUD.list_all(session, limit)

                    # カテゴリーフィルター
                    if category:
                        products = [
                            p for p in products
                            if p.product_metadata and json.loads(p.product_metadata).get("category") == category
                        ]

                    return {
                        "products": [p.to_dict() for p in products],
                        "total": len(products)
                    }

            except Exception as e:
                logger.error(f"[search_products] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/create-cart")
        async def create_cart(cart_request: Dict[str, Any]):
            """
            POST /create-cart - CartMandate作成（未署名）

            リクエスト:
            {
              "intent_mandate_id": "intent_123",
              "items": [
                {"product_id": "prod_001", "quantity": 2}
              ],
              "shipping_address": { ... }
            }

            レスポンス:
            {
              "cart_mandate": { ... },  // 未署名
              "needs_merchant_signature": true
            }
            """
            try:
                cart_mandate = await self._create_cart_mandate(cart_request)

                return {
                    "cart_mandate": cart_mandate,
                    "needs_merchant_signature": True,
                    "merchant_sign_url": f"{self.merchant_url}/sign/cart"
                }

            except Exception as e:
                logger.error(f"[create_cart] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/inventory")
        async def get_inventory():
            """
            GET /inventory - 在庫一覧取得
            """
            try:
                async with self.db_manager.get_session() as session:
                    products = await ProductCRUD.list_all(session, limit=100)
                    return {
                        "products": [
                            {
                                "id": p.id,
                                "sku": p.sku,
                                "name": p.name,
                                "inventory_count": p.inventory_count,
                                "price": p.price
                            }
                            for p in products
                        ]
                    }

            except Exception as e:
                logger.error(f"[get_inventory] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/inventory/update")
        async def update_inventory(update_request: Dict[str, Any]):
            """
            POST /inventory/update - 在庫更新

            リクエスト:
            {
              "product_id": "prod_001",
              "quantity_delta": -2  // 負の値で減少
            }
            """
            try:
                product_id = update_request["product_id"]
                delta = update_request["quantity_delta"]

                async with self.db_manager.get_session() as session:
                    product = await ProductCRUD.update_inventory(session, product_id, delta)

                    if not product:
                        raise HTTPException(status_code=404, detail="Product not found")

                    return {
                        "product_id": product.id,
                        "new_inventory_count": product.inventory_count
                    }

            except Exception as e:
                logger.error(f"[update_inventory] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_intent_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """
        IntentMandateを受信（Shopping Agentから）

        AP2/A2A仕様準拠：
        - IntentMandateから複数のカート候補を生成
        - 各カートをArtifactとして返却
        - a2a-extension.md:144-229
        """
        logger.info("[MerchantAgent] Received IntentMandate")
        intent_mandate = message.dataPart.payload

        # Intent内容から商品を検索
        intent_text = intent_mandate.get("intent", "")
        logger.info(f"[MerchantAgent] Searching products with intent: '{intent_text}'")

        try:
            # デフォルト配送先住所（デモ用）
            default_shipping_address = intent_mandate.get("shipping_address", {
                "recipient": "デモユーザー",
                "address_line1": "東京都渋谷区渋谷1-1-1",
                "address_line2": "",
                "city": "渋谷区",
                "state": "東京都",
                "postal_code": "150-0001",
                "country": "JP"
            })

            # 複数のカート候補を生成
            cart_candidates = await self._create_multiple_cart_candidates(
                intent_mandate_id=intent_mandate["id"],
                intent_text=intent_text,
                shipping_address=default_shipping_address
            )

            if not cart_candidates:
                logger.warning("[MerchantAgent] No cart candidates generated")
                return {
                    "type": "ap2.errors.Error",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "error_code": "no_products_found",
                        "error_message": f"No products found matching intent: {intent_text}"
                    }
                }

            logger.info(f"[MerchantAgent] Generated {len(cart_candidates)} cart candidates")

            # 各カート候補をArtifactとして返却
            # A2AハンドラーはこのリストをArtifactsとして処理する
            return {
                "type": "ap2.responses.CartCandidates",
                "id": str(uuid.uuid4()),
                "payload": {
                    "intent_mandate_id": intent_mandate["id"],
                    "cart_candidates": cart_candidates,
                    "merchant_id": self.merchant_id,
                    "merchant_name": self.merchant_name
                }
            }

        except Exception as e:
            logger.error(f"[handle_intent_mandate] Error: {e}", exc_info=True)
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "intent_processing_failed",
                    "error_message": str(e)
                }
            }

    async def handle_product_search_request(self, message: A2AMessage) -> Dict[str, Any]:
        """商品検索リクエストを受信"""
        logger.info("[MerchantAgent] Received ProductSearchRequest")
        search_params = message.dataPart.payload

        query = search_params.get("query", "")
        limit = search_params.get("max_results", 10)

        async with self.db_manager.get_session() as session:
            products = await ProductCRUD.search(session, query, limit)

        return {
            "type": "ap2.responses.ProductList",
            "id": str(uuid.uuid4()),
            "payload": {
                "products": [p.to_dict() for p in products],
                "total": len(products)
            }
        }

    async def handle_cart_request(self, message: A2AMessage) -> Dict[str, Any]:
        """
        CartRequestを受信（Shopping Agentから）

        AP2仕様準拠（Steps 10-12）：
        1. Merchant Agentが商品選択情報を受信
        2. Merchant AgentがCartMandateを作成（未署名）
        3. Merchant AgentがMerchantに署名依頼（HTTP）
        4. Merchant Agentが署名済みCartMandateを返却
        """
        logger.info("[MerchantAgent] Received CartRequest")
        cart_request = message.dataPart.payload

        try:
            # CartMandateを作成（未署名）
            cart_mandate = await self._create_cart_mandate(cart_request)

            logger.info(f"[MerchantAgent] Created CartMandate: {cart_mandate['id']}")

            # MerchantにCartMandateの署名を依頼（HTTP）
            try:
                response = await self.http_client.post(
                    f"{self.merchant_url}/sign/cart",
                    json={"cart_mandate": cart_mandate},
                    timeout=10.0
                )
                response.raise_for_status()
                result = response.json()

                # 自動署名モードの場合
                signed_cart_mandate = result.get("signed_cart_mandate")
                if signed_cart_mandate:
                    logger.info(f"[MerchantAgent] CartMandate signed by Merchant: {cart_mandate['id']}")

                    # 署名済みCartMandateをArtifactとして返却
                    # AP2/A2A仕様準拠：a2a-extension.md:144-229
                    return {
                        "is_artifact": True,
                        "artifact_name": "CartMandate",
                        "artifact_data": signed_cart_mandate,
                        "data_type_key": "CartMandate"
                    }

                # 手動署名モードの場合（pending_merchant_signature）
                if result.get("status") == "pending_merchant_signature":
                    logger.info(f"[MerchantAgent] CartMandate pending manual approval: {cart_mandate['id']}")
                    return {
                        "type": "ap2.responses.CartMandatePending",
                        "id": cart_mandate["id"],
                        "payload": {
                            "cart_mandate_id": result.get("cart_mandate_id"),
                            "status": "pending_merchant_signature",
                            "message": result.get("message", "Manual merchant approval required"),
                            "cart_mandate": cart_mandate  # 未署名のCartMandateも含める
                        }
                    }

                # 予期しないレスポンス
                raise ValueError(f"Unexpected response from Merchant: {result}")

            except httpx.HTTPError as e:
                logger.error(f"[handle_cart_request] Failed to get Merchant signature: {e}")
                return {
                    "type": "ap2.errors.Error",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "error_code": "merchant_signature_failed",
                        "error_message": f"Failed to get Merchant signature: {str(e)}"
                    }
                }

        except Exception as e:
            logger.error(f"[handle_cart_request] Error: {e}", exc_info=True)
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "cart_creation_failed",
                    "error_message": str(e)
                }
            }

    # ========================================
    # CartMandate作成
    # ========================================

    async def _create_cart_mandate(self, cart_request: Dict[str, Any]) -> Dict[str, Any]:
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

        async with self.db_manager.get_session() as session:
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
                    "image_url": metadata_dict.get("image_url"),
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
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "created_at": now.isoformat().replace('+00:00', 'Z'),
            "expires_at": expires_at.isoformat().replace('+00:00', 'Z'),
            # AP2仕様準拠：Merchant署名のみ（user_signatureは不要）
            "merchant_signature": None
        }

        logger.info(f"[MerchantAgent] Created CartMandate: {cart_mandate['id']}, total={cart_mandate['total']}")

        return cart_mandate

    async def _create_multiple_cart_candidates(
        self,
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

        戦略：
        1. 人気順（検索結果上位3商品）
        2. 低価格順（最安値3商品）
        3. プレミアム（高価格帯3商品）
        """
        cart_candidates = []

        async with self.db_manager.get_session() as session:
            # 商品検索
            products = await ProductCRUD.search(session, intent_text, limit=20)

            if not products:
                logger.warning(f"[_create_multiple_cart_candidates] No products found for: {intent_text}")
                return []

            logger.info(f"[_create_multiple_cart_candidates] Found {len(products)} products")

            # 戦略1: 人気順（検索結果上位3商品、各1個ずつ）
            popular_cart = await self._create_cart_from_products(
                intent_mandate_id=intent_mandate_id,
                products=products[:3],
                quantities=[1] * min(3, len(products)),
                shipping_address=shipping_address,
                cart_name="人気商品セット",
                cart_description="検索結果で人気の商品を組み合わせたカートです"
            )
            if popular_cart:
                cart_candidates.append(popular_cart)

            # 戦略2: 低価格順（最安値3商品、各1個ずつ）
            if len(products) >= 2:
                sorted_by_price = sorted(products, key=lambda p: p.price)
                budget_cart = await self._create_cart_from_products(
                    intent_mandate_id=intent_mandate_id,
                    products=sorted_by_price[:3],
                    quantities=[1] * min(3, len(sorted_by_price)),
                    shipping_address=shipping_address,
                    cart_name="お得なセット",
                    cart_description="価格を抑えた組み合わせのカートです"
                )
                if budget_cart:
                    cart_candidates.append(budget_cart)

            # 戦略3: プレミアム（高価格帯2商品、各1個ずつ）
            if len(products) >= 3:
                sorted_by_price_desc = sorted(products, key=lambda p: p.price, reverse=True)
                premium_cart = await self._create_cart_from_products(
                    intent_mandate_id=intent_mandate_id,
                    products=sorted_by_price_desc[:2],
                    quantities=[1] * min(2, len(sorted_by_price_desc)),
                    shipping_address=shipping_address,
                    cart_name="プレミアムセット",
                    cart_description="高品質な商品を厳選したカートです"
                )
                if premium_cart:
                    cart_candidates.append(premium_cart)

        logger.info(f"[_create_multiple_cart_candidates] Created {len(cart_candidates)} cart candidates")
        return cart_candidates

    async def _create_cart_from_products(
        self,
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

        # CartItem作成
        cart_items = []
        subtotal_cents = 0

        for product, quantity in zip(products, quantities):
            unit_price_cents = product.price
            total_price_cents = unit_price_cents * quantity

            metadata_dict = json.loads(product.product_metadata) if product.product_metadata else {}

            cart_items.append({
                "id": f"item_{uuid.uuid4().hex[:8]}",
                "name": product.name,
                "description": product.description,
                "quantity": quantity,
                "unit_price": {
                    "value": str(unit_price_cents / 100),
                    "currency": "JPY"
                },
                "total_price": {
                    "value": str(total_price_cents / 100),
                    "currency": "JPY"
                },
                "image_url": metadata_dict.get("image_url"),
                "sku": product.sku,
                "category": metadata_dict.get("category"),
                "brand": metadata_dict.get("brand")
            })

            subtotal_cents += total_price_cents

        # 税金計算（10%）
        tax_cents = int(subtotal_cents * 0.1)

        # 送料計算（固定500円）
        shipping_cost_cents = 50000

        # 合計
        total_cents = subtotal_cents + tax_cents + shipping_cost_cents

        # CartMandate作成（未署名）
        cart_mandate = {
            "id": f"cart_{uuid.uuid4().hex[:8]}",
            "type": "CartMandate",
            "version": "0.2",
            "intent_mandate_id": intent_mandate_id,
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
                "address": shipping_address,
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
            "merchant_id": self.merchant_id,
            "merchant_name": self.merchant_name,
            "created_at": now.isoformat().replace('+00:00', 'Z'),
            "expires_at": expires_at.isoformat().replace('+00:00', 'Z'),
            "merchant_signature": None,
            # カート候補メタデータ
            "cart_metadata": {
                "name": cart_name,
                "description": cart_description
            }
        }

        # MerchantにCartMandateの署名を依頼
        try:
            response = await self.http_client.post(
                f"{self.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                logger.error(f"[_create_cart_from_products] Merchant signature failed for cart: {cart_mandate['id']}")
                return None

            logger.info(f"[_create_cart_from_products] CartMandate signed: {cart_mandate['id']}")

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
            logger.error(f"[_create_cart_from_products] Failed to get Merchant signature: {e}")
            return None
