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
from common.base_agent import BaseAgent, AgentPassphraseManager
from common.models import A2AMessage
from common.database import DatabaseManager, ProductCRUD
from common.seed_data import seed_products, seed_users
from common.search_engine import MeilisearchClient
from common.logger import get_logger, log_http_request, log_http_response, log_a2a_message, LoggingAsyncClient

# LangGraphエンジンのインポート
from services.merchant_agent.langgraph_merchant import MerchantLangGraphAgent

# Merchant Agent ユーティリティモジュール
from services.merchant_agent.utils import CartHelpers, ProductHelpers

# A2Aハンドラーモジュール
from services.merchant_agent.handlers import (
    handle_intent_mandate,
    handle_product_search_request,
    handle_cart_selection,
    handle_cart_request,
    handle_payment_request
)

# CartMandateサービスモジュール
from services.merchant_agent.services import (
    create_cart_mandate,
    create_multiple_cart_candidates,
    create_cart_from_products,
    wait_for_merchant_signature
)

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
        # AP2完全準拠: LoggingAsyncClientで全HTTP通信をログ記録
        self.http_client = LoggingAsyncClient(
            logger=logger,
            timeout=30.0
        )

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
                    from services.merchant_agent.langgraph_merchant import langfuse_client, LANGFUSE_ENABLED
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
        self.a2a_handler.register_handler("ap2.mandates.IntentMandate", lambda msg: handle_intent_mandate(self, msg))
        self.a2a_handler.register_handler("ap2.requests.ProductSearch", lambda msg: handle_product_search_request(self, msg))
        self.a2a_handler.register_handler("ap2.requests.CartRequest", lambda msg: handle_cart_request(self, msg))
        self.a2a_handler.register_handler("ap2.requests.CartSelection", lambda msg: handle_cart_selection(self, msg))  # AI化で追加
        self.a2a_handler.register_handler("ap2.mandates.PaymentMandate", lambda msg: handle_payment_request(self, msg))  # AP2仕様準拠

    def register_endpoints(self):
        """
        Merchant Agent固有エンドポイントの登録
        """

        # ========================================
        # W3C DID仕様準拠: DIDドキュメント公開エンドポイント
        # ========================================

        @self.app.get("/.well-known/did.json")
        async def get_did_document():
            """
            GET /.well-known/did.json - DIDドキュメント取得

            W3C DID仕様準拠:
            - DIDドキュメントをHTTP経由で公開
            - リモート解決を可能にする（Docker内部DNS対応）
            - 公開鍵の検証に使用

            AP2プロトコル要件:
            - 各エージェントのDIDを公開し、相互運用性を向上
            - did:ap2:agent:merchant_agent → http://merchant_agent:8001/.well-known/did.json
            """
            import json
            from pathlib import Path

            # DIDドキュメントファイルパスを解決
            did_docs_dir = Path("/app/v2/data/did_documents")
            did_doc_file = did_docs_dir / "merchant_agent_did.json"

            if not did_doc_file.exists():
                logger.error(f"[get_did_document] DID document not found: {did_doc_file}")
                raise HTTPException(
                    status_code=404,
                    detail="DID document not found"
                )

            # DIDドキュメントを読み込んで返却
            try:
                did_doc = json.loads(did_doc_file.read_text())
                logger.debug(f"[get_did_document] Returning DID document: {did_doc.get('id')}")
                return did_doc
            except Exception as e:
                logger.error(f"[get_did_document] Failed to read DID document: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to read DID document"
                )

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
    # ヘルパーメソッド（CartMandate作成）
    # ========================================

    async def _create_cart_mandate(self, cart_request: Dict[str, Any]) -> Dict[str, Any]:
        """CartMandateを作成（未署名）- services/cart_service.pyに委譲"""
        return await create_cart_mandate(self, cart_request)

    async def _create_multiple_cart_candidates(
        self,
        intent_mandate_id: str,
        intent_text: str,
        shipping_address: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """複数のカート候補を生成 - services/cart_service.pyに委譲"""
        return await create_multiple_cart_candidates(self, intent_mandate_id, intent_text, shipping_address)

    async def _create_cart_from_products(
        self,
        intent_mandate_id: str,
        products: List[Any],
        quantities: List[int],
        shipping_address: Dict[str, Any],
        cart_name: str,
        cart_description: str
    ) -> Optional[Dict[str, Any]]:
        """商品リストからCartMandateを作成 - services/cart_service.pyに委譲"""
        return await create_cart_from_products(
            self, intent_mandate_id, products, quantities,
            shipping_address, cart_name, cart_description
        )

    async def _wait_for_merchant_signature(
        self,
        cart_mandate_id: str,
        cart_name: str = "",
        timeout: int = 300,
        poll_interval: float = 2.0
    ) -> Optional[Dict[str, Any]]:
        """Merchantの署名を待機 - services/cart_service.pyに委譲"""
        return await wait_for_merchant_signature(self, cart_mandate_id, cart_name, timeout, poll_interval)

    # ========================================
    # 削除された旧A2Aメッセージハンドラー
    # ========================================
    # handle_intent_mandate -> handlers/intent_handler.py
    # handle_product_search_request -> handlers/product_handler.py
    # handle_cart_selection -> handlers/cart_handler.py
    # handle_cart_request -> handlers/cart_handler.py
    # handle_payment_request -> handlers/payment_handler.py

    # ========================================
    # 削除された旧CartMandateメソッド
    # ========================================
    # _create_cart_mandate -> services/cart_service.py
    # _create_multiple_cart_candidates -> services/cart_service.py
    # _create_cart_from_products -> services/cart_service.py
    # _wait_for_merchant_signature -> services/cart_service.py

    # ========================================
    # その他ヘルパーメソッド
    # ========================================
    async def _sync_products_to_meilisearch(self, search_client: MeilisearchClient):
        """Meilisearch同期（ヘルパーメソッドに委譲）"""
        await self.product_helpers.sync_products_to_meilisearch(search_client)
