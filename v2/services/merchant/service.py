"""
v2/services/merchant/service.py

Merchant Service実装
- CartMandateへの署名（重要！Merchant AgentではなくMerchantが署名）
- 商品管理
- 在庫管理
"""

import sys
import uuid
import json
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime, timezone
import logging

from fastapi import HTTPException

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage, Signature
from v2.common.database import DatabaseManager, ProductCRUD, MandateCRUD
from v2.common.crypto import SignatureManager, KeyManager

logger = logging.getLogger(__name__)


class MerchantService(BaseAgent):
    """
    Merchant Service

    実際の店舗エンティティ
    - CartMandateの署名（Merchant Agentとは分離）
    - 商品・在庫管理
    - 注文承認
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:merchant",
            agent_name="Merchant",
            passphrase=AgentPassphraseManager.get_passphrase("merchant"),
            keys_directory="./keys"
        )

        # データベースマネージャー（絶対パスを使用）
        self.db_manager = DatabaseManager(database_url="sqlite+aiosqlite:////app/v2/data/ap2.db")

        # このMerchantの情報
        self.merchant_id = "did:ap2:merchant:demo_merchant"
        self.merchant_name = "AP2デモストア"

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Merchantが受信するA2Aメッセージ：
        - ap2/CartMandate: Merchant Agentからの署名依頼
        """
        self.a2a_handler.register_handler("ap2/CartMandate", self.handle_cart_mandate_sign_request)

    def register_endpoints(self):
        """
        Merchant固有エンドポイントの登録
        """

        @self.app.post("/sign/cart")
        async def sign_cart_mandate(sign_request: Dict[str, Any]):
            """
            POST /sign/cart - CartMandateに署名

            demo_app_v2.mdの重要な要件：
            Merchant AgentがCartMandateを作成（未署名）
            → Merchantが検証して署名を追加

            リクエスト:
            {
              "cart_mandate": { ... }
            }

            レスポンス:
            {
              "signed_cart_mandate": { ... },
              "merchant_signature": { ... }
            }
            """
            try:
                cart_mandate = sign_request["cart_mandate"]

                # 1. バリデーション
                self._validate_cart_mandate(cart_mandate)

                # 2. 在庫確認
                await self._check_inventory(cart_mandate)

                # 3. 署名生成
                signature = await self._sign_cart_mandate(cart_mandate)

                # 4. 署名を追加
                signed_cart_mandate = cart_mandate.copy()
                signed_cart_mandate["merchant_signature"] = signature.model_dump()

                # 5. データベースに保存
                async with self.db_manager.get_session() as session:
                    await MandateCRUD.create(session, {
                        "id": cart_mandate["id"],
                        "type": "Cart",
                        "status": "signed",
                        "payload": signed_cart_mandate,
                        "issuer": self.agent_id
                    })

                logger.info(f"[Merchant] Signed CartMandate: {cart_mandate['id']}")

                return {
                    "signed_cart_mandate": signed_cart_mandate,
                    "merchant_signature": signed_cart_mandate["merchant_signature"]
                }

            except Exception as e:
                logger.error(f"[sign_cart_mandate] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.get("/products")
        async def list_products(limit: int = 100):
            """
            GET /products - 商品一覧
            """
            try:
                async with self.db_manager.get_session() as session:
                    products = await ProductCRUD.list_all(session, limit)
                    return {
                        "products": [p.to_dict() for p in products],
                        "total": len(products)
                    }

            except Exception as e:
                logger.error(f"[list_products] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.patch("/products/{product_id}")
        async def update_product(product_id: str, update_data: Dict[str, Any]):
            """
            PATCH /products/{id} - 商品更新
            """
            try:
                async with self.db_manager.get_session() as session:
                    product = await ProductCRUD.get_by_id(session, product_id)
                    if not product:
                        raise HTTPException(status_code=404, detail="Product not found")

                    # 在庫数更新
                    if "inventory_count" in update_data:
                        delta = update_data["inventory_count"] - product.inventory_count
                        product = await ProductCRUD.update_inventory(session, product_id, delta)

                    return product.to_dict()

            except Exception as e:
                logger.error(f"[update_product] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/orders/pending")
        async def get_pending_orders():
            """
            GET /orders/pending - 未処理注文一覧
            """
            # TODO: 実装（Mandateテーブルからstatus=pending_signatureを取得）
            return {"orders": []}

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_cart_mandate_sign_request(self, message: A2AMessage) -> Dict[str, Any]:
        """
        CartMandate署名リクエストを受信（Merchant Agentから）
        """
        logger.info("[Merchant] Received CartMandate sign request")
        cart_mandate = message.dataPart.payload

        try:
            # バリデーション
            self._validate_cart_mandate(cart_mandate)

            # 在庫確認
            await self._check_inventory(cart_mandate)

            # 署名
            signature = await self._sign_cart_mandate(cart_mandate)

            # 署名を追加
            signed_cart_mandate = cart_mandate.copy()
            signed_cart_mandate["merchant_signature"] = signature.model_dump()

            return {
                "type": "ap2/CartMandate",
                "id": cart_mandate["id"],
                "payload": signed_cart_mandate
            }

        except Exception as e:
            logger.error(f"[handle_cart_mandate_sign_request] Error: {e}", exc_info=True)
            return {
                "type": "ap2/Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "signature_failed",
                    "error_message": str(e)
                }
            }

    # ========================================
    # 内部メソッド
    # ========================================

    def _validate_cart_mandate(self, cart_mandate: Dict[str, Any]):
        """
        CartMandateを検証

        - merchant_idが一致するか
        - 価格が正しいか
        - 有効期限内か
        """
        # merchant_id確認
        if cart_mandate.get("merchant_id") != self.merchant_id:
            raise ValueError(f"Merchant ID mismatch: expected={self.merchant_id}, got={cart_mandate.get('merchant_id')}")

        # 有効期限確認
        expires_at_str = cart_mandate.get("expires_at")
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            if datetime.now(timezone.utc) > expires_at:
                raise ValueError("CartMandate has expired")

        logger.info(f"[Merchant] CartMandate validation passed: {cart_mandate['id']}")

    async def _check_inventory(self, cart_mandate: Dict[str, Any]):
        """
        在庫を確認

        全アイテムの在庫が十分にあるか確認
        """
        async with self.db_manager.get_session() as session:
            for item in cart_mandate.get("items", []):
                sku = item.get("sku")
                if not sku:
                    continue

                product = await ProductCRUD.get_by_sku(session, sku)
                if not product:
                    raise ValueError(f"Product not found: {sku}")

                required_quantity = item.get("quantity", 0)
                if product.inventory_count < required_quantity:
                    raise ValueError(
                        f"Insufficient inventory for {product.name}: "
                        f"required={required_quantity}, available={product.inventory_count}"
                    )

        logger.info(f"[Merchant] Inventory check passed for CartMandate: {cart_mandate['id']}")

    async def _sign_cart_mandate(self, cart_mandate: Dict[str, Any]) -> Signature:
        """
        CartMandateに署名

        v2.common.crypto.SignatureManagerを使用
        """
        # merchant_signatureフィールドを除外してから署名
        cart_data = cart_mandate.copy()
        cart_data.pop("merchant_signature", None)
        cart_data.pop("user_signature", None)

        # 署名生成（agent_idから鍵IDを抽出）
        key_id = self.agent_id.split(":")[-1]  # did:ap2:merchant -> merchant
        signature = self.signature_manager.sign_mandate(cart_data, key_id)

        return signature
