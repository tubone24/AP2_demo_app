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
from v2.common.search_engine import MeilisearchClient
from v2.common.logger import get_logger, log_http_request, log_http_response, log_a2a_message

# LangGraphエンジンのインポート
from langgraph_merchant import MerchantLangGraphAgent

# Merchant Agent ユーティリティモジュール
from services.merchant_agent.utils import CartHelpers, ProductHelpers

logger = get_logger(__name__, service_name='merchant_agent')


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

        # Payment Processorエンドポイント（Docker Compose環境想定）
        self.payment_processor_url = "http://payment_processor:8004"

        # このMerchantの情報（固定）
        self.merchant_id = "did:ap2:merchant:mugibo_merchant"
        self.merchant_name = "むぎぼーショップ"

        # ヘルパークラスの初期化
        self.cart_helpers = CartHelpers()
        self.product_helpers = ProductHelpers(db_manager=self.db_manager)

        # LangGraphエンジンの初期化（AI化）
        self.langgraph_agent = None  # startup時に初期化

        # AI化モードフラグ（環境変数で制御）
        self.ai_mode_enabled = os.getenv("MERCHANT_AI_MODE", "true").lower() == "true"

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

            # Meilisearch同期（AP2準拠）
            try:
                search_client = MeilisearchClient()
                await self._sync_products_to_meilisearch(search_client)
                logger.info(f"[{self.agent_name}] Meilisearch synchronized")
            except Exception as e:
                logger.warning(f"[{self.agent_name}] Meilisearch sync warning: {e}")

            # LangGraphエンジン初期化（AI化）
            if self.ai_mode_enabled:
                try:
                    self.langgraph_agent = MerchantLangGraphAgent(
                        db_manager=self.db_manager,
                        merchant_id=self.merchant_id,
                        merchant_name=self.merchant_name,
                        merchant_url=self.merchant_url,
                        http_client=self.http_client
                    )
                    logger.info(f"[{self.agent_name}] LangGraph AI engine initialized")
                except Exception as e:
                    logger.error(f"[{self.agent_name}] Failed to initialize LangGraph: {e}")
                    self.ai_mode_enabled = False

        @self.app.on_event("shutdown")
        async def shutdown_event():
            """シャットダウン時の処理"""
            logger.info(f"[{self.agent_name}] Running shutdown tasks...")

            # Langfuse flush
            if self.ai_mode_enabled and self.langgraph_agent:
                try:
                    from langgraph_merchant import langfuse_client, LANGFUSE_ENABLED
                    if LANGFUSE_ENABLED and langfuse_client:
                        langfuse_client.flush()
                        logger.info(f"[{self.agent_name}] Langfuse traces flushed")
                except Exception as e:
                    logger.warning(f"[{self.agent_name}] Failed to flush Langfuse: {e}")

        logger.info(f"[{self.agent_name}] Initialized (AI Mode: {self.ai_mode_enabled})")

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
        - ap2.mandates.IntentMandate: Shopping Agentからの購入意図
        - ap2.requests.ProductSearch: 商品検索依頼（AI化対応）
        - ap2.requests.CartRequest: Shopping Agentからのカート作成・署名依頼
        - ap2.requests.CartSelection: カート選択通知（AI化で追加）

        Merchant Agentが送信するA2Aメッセージ：
        - ap2.responses.CartCandidates: 複数カート候補（AI化で追加）
        - ap2.responses.ProductList: 商品リスト（従来）
        """
        self.a2a_handler.register_handler("ap2.mandates.IntentMandate", self.handle_intent_mandate)
        self.a2a_handler.register_handler("ap2.requests.ProductSearch", self.handle_product_search_request)
        self.a2a_handler.register_handler("ap2.requests.CartRequest", self.handle_cart_request)
        self.a2a_handler.register_handler("ap2.requests.CartSelection", self.handle_cart_selection)  # AI化で追加
        self.a2a_handler.register_handler("ap2.mandates.PaymentMandate", self.handle_payment_request)  # AP2仕様準拠

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

        AP2仕様準拠（v0.1）：
        - ペイロードにはintent_mandateとshipping_addressが含まれる
        - 配送先はCartMandate作成前に確定している必要がある
        """
        logger.info("[MerchantAgent] Received IntentMandate")
        payload = message.dataPart.payload

        # AP2仕様準拠：ペイロードからintent_mandateとshipping_addressを抽出
        if isinstance(payload, dict) and "intent_mandate" in payload:
            # 新しい形式：{intent_mandate: {...}, shipping_address: {...}}
            intent_mandate = payload["intent_mandate"]
            shipping_address = payload.get("shipping_address")
            logger.info("[MerchantAgent] Received IntentMandate with shipping_address (AP2 v0.1 compliant)")
        else:
            # 旧形式（後方互換性のため）：payload自体がintent_mandate
            intent_mandate = payload
            shipping_address = None
            logger.info("[MerchantAgent] Received IntentMandate without shipping_address (legacy format)")

        # AP2準拠：natural_language_descriptionフィールドを使用
        intent_text = intent_mandate.get("natural_language_description", intent_mandate.get("intent", ""))
        logger.info(f"[MerchantAgent] Searching products with intent: '{intent_text}'")

        try:
            # 配送先住所の決定（AP2仕様準拠）
            if shipping_address:
                # Shopping Agentから提供された配送先を使用
                logger.info(f"[MerchantAgent] Using provided shipping address: {shipping_address.get('recipient', 'N/A')}")
            else:
                # デフォルト配送先住所（デモ用・後方互換性）
                shipping_address = {
                    "recipient": "デモユーザー",
                    "address_line1": "東京都渋谷区渋谷1-1-1",
                    "address_line2": "",
                    "city": "渋谷区",
                    "state": "東京都",
                    "postal_code": "150-0001",
                    "country": "JP"
                }
                logger.info("[MerchantAgent] Using default shipping address")

            # 複数のカート候補を生成
            # AI Mode: LangGraphエンジンを使用
            if self.ai_mode_enabled and self.langgraph_agent:
                logger.info("[MerchantAgent] Using LangGraph AI engine for cart generation")
                cart_candidates = await self.langgraph_agent.create_cart_candidates(
                    intent_mandate=intent_mandate,
                    user_id=intent_mandate.get("user_id", "unknown"),
                    session_id=str(uuid.uuid4())
                )
            else:
                # 従来Mode: 固定ロジック
                logger.info("[MerchantAgent] Using legacy cart generation")
                cart_candidates = await self._create_multiple_cart_candidates(
                    intent_mandate_id=intent_mandate["id"],
                    intent_text=intent_text,
                    shipping_address=shipping_address
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
        """
        商品検索リクエストを受信（AI化対応）

        AI Modeの場合:
        - IntentMandateを含むリクエストからLangGraphで複数カート候補を生成
        - ap2.responses.CartCandidates として返却（Shopping Agent対応済み）

        従来Mode:
        - 単純な商品リストを返却（ap2.responses.ProductList）
        """
        logger.info(f"[MerchantAgent] Received ProductSearchRequest (AI Mode: {self.ai_mode_enabled})")
        search_params = message.dataPart.payload

        # AI Mode: IntentMandateが含まれている場合、複数カート候補を生成
        if self.ai_mode_enabled and "intent_mandate" in search_params:
            logger.info("[MerchantAgent] AI Mode: Generating cart candidates with LangGraph")

            intent_mandate = search_params["intent_mandate"]
            user_id = search_params.get("user_id", "unknown")
            session_id = search_params.get("session_id", str(uuid.uuid4()))

            try:
                # LangGraphで複数カート候補を生成
                cart_candidates = await self.langgraph_agent.create_cart_candidates(
                    intent_mandate=intent_mandate,
                    user_id=user_id,
                    session_id=session_id
                )

                logger.info(f"[MerchantAgent] Generated {len(cart_candidates)} cart candidates")

                # ap2.responses.CartCandidates として返却（Shopping Agent対応済み）
                return {
                    "type": "ap2.responses.CartCandidates",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "cart_candidates": cart_candidates,
                        "intent_mandate_id": intent_mandate.get("id"),
                        "merchant_id": self.merchant_id,
                        "merchant_name": self.merchant_name
                    }
                }

            except Exception as e:
                logger.error(f"[handle_product_search_request] LangGraph error: {e}", exc_info=True)
                # フォールバック: 従来の商品リスト返却
                pass

        # 従来Mode: 単純な商品検索
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

    async def handle_cart_selection(self, message: A2AMessage) -> Dict[str, Any]:
        """
        カート選択通知を受信（Shopping Agentから） - AI化で追加

        ユーザーが複数のカート候補から1つを選択したことを通知。
        選択されたカートをMerchantに署名依頼して返却。

        Args:
            message: A2AMessage
                - payload.selected_cart_id: 選択されたカートID
                - payload.cart_mandate: 選択されたCartMandate（未署名）
                - payload.user_id: ユーザーID

        Returns:
            署名済みCartMandateまたはエラー
        """
        logger.info("[MerchantAgent] Received CartSelectionRequest")
        payload = message.dataPart.payload

        selected_cart_id = payload.get("selected_cart_id")
        cart_mandate = payload.get("cart_mandate")
        user_id = payload.get("user_id")

        if not cart_mandate:
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "invalid_cart_selection",
                    "error_message": "cart_mandate is required"
                }
            }

        logger.info(f"[MerchantAgent] User {user_id} selected cart: {selected_cart_id}")

        try:
            # MerchantにCartMandateの署名を依頼（HTTP）
            response = await self.http_client.post(
                f"{self.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 署名済みCartMandateを取得
            signed_cart_mandate = result.get("signed_cart_mandate")
            if signed_cart_mandate:
                logger.info(f"[MerchantAgent] CartMandate signed: {selected_cart_id}")

                # 署名済みCartMandateを返却
                return {
                    "type": "ap2.responses.SignedCartMandate",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "cart_mandate": signed_cart_mandate,
                        "cart_id": selected_cart_id
                    }
                }

            # 手動署名待ち
            if result.get("status") == "pending_merchant_signature":
                logger.info(f"[MerchantAgent] CartMandate pending manual approval: {selected_cart_id}")
                return {
                    "type": "ap2.responses.CartMandatePending",
                    "id": str(uuid.uuid4()),
                    "payload": {
                        "cart_mandate_id": result.get("cart_mandate_id"),
                        "status": "pending_merchant_signature",
                        "message": result.get("message", "Manual merchant approval required")
                    }
                }

            raise ValueError(f"Unexpected response from Merchant: {result}")

        except Exception as e:
            logger.error(f"[handle_cart_selection] Error: {e}", exc_info=True)
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "cart_signature_failed",
                    "error_message": str(e)
                }
            }

    async def handle_cart_request(self, message: A2AMessage) -> Dict[str, Any]:
        """
        CartRequestを受信（Shopping Agentから）- 従来フロー

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

    async def handle_payment_request(self, message: A2AMessage) -> Dict[str, Any]:
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
            forward_message = self.a2a_handler.create_response_message(
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
            import json as json_lib
            logger.info(
                f"\n{'='*80}\n"
                f"[MerchantAgent → PaymentProcessor] A2Aメッセージ転送\n"
                f"  URL: {self.payment_processor_url}/a2a/message\n"
                f"  メッセージID: {forward_message.header.message_id}\n"
                f"  タイプ: {forward_message.dataPart.type}\n"
                f"{'='*80}"
            )

            response = await self.http_client.post(
                f"{self.payment_processor_url}/a2a/message",
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

        UX改善：すべてのカート候補を一気に作成し、署名依頼を並列化
        手動署名モードでは、3つの署名依頼が同時にMerchant Dashboardに表示される

        戦略：
        1. 人気順（検索結果上位3商品）
        2. 低価格順（最安値3商品）
        3. プレミアム（高価格帯3商品）
        """
        async with self.db_manager.get_session() as session:
            # 商品検索
            products = await ProductCRUD.search(session, intent_text, limit=20)

            if not products:
                logger.warning(f"[_create_multiple_cart_candidates] No products found for: {intent_text}")
                return []

            logger.info(f"[_create_multiple_cart_candidates] Found {len(products)} products")

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

        logger.info(f"[_create_multiple_cart_candidates] Creating {len(cart_definitions)} cart candidates")

        # ステップ2: すべてのカート候補を並列で作成・署名依頼
        # asyncio.gatherで並列実行してUX改善（一気に署名依頼が届く）
        import asyncio
        cart_creation_tasks = [
            self._create_cart_from_products(
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
                logger.error(f"[_create_multiple_cart_candidates] Failed to create cart {i+1}: {result}")
            elif result is not None:
                cart_candidates.append(result)

        logger.info(f"[_create_multiple_cart_candidates] Created {len(cart_candidates)} cart candidates")
        return cart_candidates

    def _build_cart_items_from_products(
        self,
        products: List[Any],
        quantities: List[int]
    ) -> tuple[List[Dict[str, Any]], int]:
        """CartItem作成（ヘルパーメソッドに委譲）"""
        return self.cart_helpers.build_cart_items_from_products(products, quantities)

    def _calculate_cart_costs(self, subtotal_cents: int) -> Dict[str, int]:
        """カートコスト計算（ヘルパーメソッドに委譲）"""
        return self.cart_helpers.calculate_cart_costs(subtotal_cents)

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

        # 1. CartItem作成と小計計算
        cart_items, subtotal_cents = self._build_cart_items_from_products(products, quantities)

        # 2. 税金、送料、合計計算
        costs = self._calculate_cart_costs(subtotal_cents)
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
            "merchant_name": self.merchant_name
        }

        # CartMandate構造（AP2準拠）
        cart_mandate = {
            "contents": cart_contents,
            "merchant_authorization": None,  # Merchantが署名
            # 追加メタデータ（AP2仕様外だが、Shopping Agent UIで必要）
            "_metadata": {
                "intent_mandate_id": intent_mandate_id,
                "merchant_id": self.merchant_id,
                "created_at": now.isoformat().replace('+00:00', 'Z'),
                "cart_name": cart_name,
                "cart_description": cart_description,
                "raw_items": cart_items  # 元のアイテム情報（互換性のため保持）
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

            # AP2仕様準拠（specification.md:629-632, 675-678）：
            # CartMandateは必ずMerchant署名済みでなければならない
            # "The cart mandate is first signed by the merchant entity...
            #  This ensures that the user sees a cart which the merchant has confirmed to fulfill."

            # 手動署名モード：Merchantの承認を待機
            if result.get("status") == "pending_merchant_signature":
                cart_mandate_id = result.get("cart_mandate_id")
                logger.info(f"[_create_cart_from_products] '{cart_name}' pending manual approval: {cart_mandate_id}")
                logger.info(f"[_create_cart_from_products] Waiting for merchant signature for '{cart_name}' (max 300s)...")

                # Merchantの承認を待機（ポーリング）
                signed_cart_mandate = await self._wait_for_merchant_signature(
                    cart_mandate_id,
                    cart_name=cart_name,  # ログ改善のためカート名を渡す
                    timeout=300
                )

                if not signed_cart_mandate:
                    logger.error(f"[_create_cart_from_products] Failed to get merchant signature for cart: {cart_mandate_id}")
                    return None

                logger.info(f"[_create_cart_from_products] Merchant signature completed: {cart_mandate_id}")

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
                logger.error(f"[_create_cart_from_products] Unexpected response from Merchant: {result}")
                return None

            # AP2準拠：cart_idをcontents.idから取得
            cart_id = signed_cart_mandate.get("contents", {}).get("id", "unknown")
            logger.info(f"[_create_cart_from_products] CartMandate signed: {cart_id}")

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

    async def _wait_for_merchant_signature(
        self,
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

        import asyncio
        start_time = asyncio.get_event_loop().time()
        elapsed_time = 0

        while elapsed_time < timeout:
            try:
                # MerchantからCartMandateのステータスを取得
                response = await self.http_client.get(
                    f"{self.merchant_url}/cart-mandates/{cart_mandate_id}",
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
                logger.error(f"[_wait_for_merchant_signature] HTTP error while checking status: {e}")
                await asyncio.sleep(poll_interval)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                continue

            except Exception as e:
                logger.error(f"[_wait_for_merchant_signature] Error while checking status: {e}")
                return None

        # タイムアウト
        logger.error(f"[MerchantAgent] Timeout waiting for merchant signature for {cart_label}")
        return None

    async def _sync_products_to_meilisearch(self, search_client: MeilisearchClient):
        """Meilisearch同期（ヘルパーメソッドに委譲）"""
        await self.product_helpers.sync_products_to_meilisearch(search_client)
