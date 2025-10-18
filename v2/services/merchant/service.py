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

        # データベースマネージャー（環境変数から読み込み、絶対パスを使用）
        import os
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/merchant.db")
        self.db_manager = DatabaseManager(database_url=database_url)

        # このMerchantの情報
        self.merchant_id = "did:ap2:merchant:demo_merchant"
        self.merchant_name = "AP2デモストア"

        # 署名モード設定（メモリ内管理、本番環境ではDBに保存）
        self.auto_sign_mode = True  # デフォルトは自動署名

        # 起動イベントハンドラー登録
        @self.app.on_event("startup")
        async def startup_event():
            """起動時の初期化処理"""
            logger.info(f"[{self.agent_name}] Running startup tasks...")

            # データベース初期化
            await self.db_manager.init_db()
            logger.info(f"[{self.agent_name}] Database initialized")

            # サンプルデータシード（商品・ユーザー）
            # Merchantは在庫確認のために商品データが必要
            try:
                from v2.common.seed_data import seed_products, seed_users
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
        return "Merchant Service for AP2 Protocol - handles cart mandate signing, product management, and order approval"

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Merchantが受信するA2Aメッセージ：
        - ap2/CartMandate: Merchant Agentからの署名依頼
        """
        self.a2a_handler.register_handler("ap2.mandates.CartMandate", self.handle_cart_mandate_sign_request)

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

            自動署名モード：即座に署名
            手動署名モード：pending_merchant_signatureステータスで保存し、要承認

            リクエスト:
            {
              "cart_mandate": { ... }
            }

            レスポンス（自動モード）:
            {
              "signed_cart_mandate": { ... },
              "merchant_signature": { ... }
            }

            レスポンス（手動モード）:
            {
              "status": "pending_merchant_signature",
              "cart_mandate_id": "...",
              "message": "Manual approval required"
            }
            """
            try:
                cart_mandate = sign_request["cart_mandate"]

                # 1. バリデーション
                self._validate_cart_mandate(cart_mandate)

                # 2. 在庫確認
                await self._check_inventory(cart_mandate)

                # 3. 署名モードによる分岐
                if self.auto_sign_mode:
                    # 自動署名モード
                    signature = await self._sign_cart_mandate(cart_mandate)
                    signed_cart_mandate = cart_mandate.copy()
                    signed_cart_mandate["merchant_signature"] = signature.model_dump()

                    # AP2仕様準拠：merchant_authorization JWT追加
                    merchant_authorization_jwt = self._generate_merchant_authorization_jwt(
                        cart_mandate,
                        self.merchant_id
                    )
                    signed_cart_mandate["merchant_authorization"] = merchant_authorization_jwt

                    # データベースに保存
                    async with self.db_manager.get_session() as session:
                        await MandateCRUD.create(session, {
                            "id": cart_mandate["id"],
                            "type": "Cart",
                            "status": "signed",
                            "payload": signed_cart_mandate,
                            "issuer": self.agent_id
                        })

                    logger.info(
                        f"[Merchant] Auto-signed CartMandate: {cart_mandate['id']} "
                        f"(with merchant_authorization JWT)"
                    )

                    return {
                        "signed_cart_mandate": signed_cart_mandate,
                        "merchant_signature": signed_cart_mandate["merchant_signature"],
                        "merchant_authorization": merchant_authorization_jwt
                    }
                else:
                    # 手動署名モード：承認待ちとして保存
                    async with self.db_manager.get_session() as session:
                        await MandateCRUD.create(session, {
                            "id": cart_mandate["id"],
                            "type": "Cart",
                            "status": "pending_merchant_signature",
                            "payload": cart_mandate,
                            "issuer": self.agent_id
                        })

                    logger.info(f"[Merchant] CartMandate pending manual approval: {cart_mandate['id']}")

                    return {
                        "status": "pending_merchant_signature",
                        "cart_mandate_id": cart_mandate["id"],
                        "message": "Manual approval required by merchant"
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

            AP2仕様準拠：
            pending_merchant_signatureステータスのCartMandateを取得
            """
            try:
                async with self.db_manager.get_session() as session:
                    # 署名待ちのCartMandateを取得
                    mandates = await MandateCRUD.get_by_status(session, "pending_merchant_signature")

                    return {
                        "orders": [
                            {
                                "id": m.id,
                                "type": "CartMandate",
                                "status": m.status,
                                "payload": json.loads(m.payload) if isinstance(m.payload, str) else m.payload,
                                "created_at": m.issued_at.isoformat() if m.issued_at else None
                            }
                            for m in mandates
                        ],
                        "total": len(mandates)
                    }

            except Exception as e:
                logger.error(f"[get_pending_orders] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/settings/signature-mode")
        async def get_signature_mode():
            """
            GET /settings/signature-mode - 署名モード取得
            """
            return {
                "auto_sign_mode": self.auto_sign_mode,
                "mode": "auto" if self.auto_sign_mode else "manual"
            }

        @self.app.post("/settings/signature-mode")
        async def set_signature_mode(request: Dict[str, Any]):
            """
            POST /settings/signature-mode - 署名モード設定

            リクエスト:
            {
              "auto_sign_mode": true/false
            }
            """
            auto_sign = request.get("auto_sign_mode", True)
            self.auto_sign_mode = auto_sign
            logger.info(f"[Merchant] Signature mode changed to: {'auto' if auto_sign else 'manual'}")

            return {
                "auto_sign_mode": self.auto_sign_mode,
                "mode": "auto" if self.auto_sign_mode else "manual",
                "message": f"Signature mode set to {'automatic' if auto_sign else 'manual'}"
            }

        @self.app.get("/cart-mandates/pending")
        async def get_pending_cart_mandates():
            """
            GET /cart-mandates/pending - 署名待ちCartMandate一覧

            IMPORTANT: This route must be defined BEFORE /cart-mandates/{cart_mandate_id}
            to avoid FastAPI matching 'pending' as a path parameter
            """
            try:
                async with self.db_manager.get_session() as session:
                    mandates = await MandateCRUD.get_by_status(session, "pending_merchant_signature")

                    return {
                        "pending_cart_mandates": [
                            {
                                "id": m.id,
                                "payload": json.loads(m.payload) if isinstance(m.payload, str) else m.payload,
                                "created_at": m.issued_at.isoformat() if m.issued_at else None
                            }
                            for m in mandates
                        ],
                        "total": len(mandates)
                    }

            except Exception as e:
                logger.error(f"[get_pending_cart_mandates] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/cart-mandates/{cart_mandate_id}")
        async def get_cart_mandate(cart_mandate_id: str):
            """
            GET /cart-mandates/{id} - CartMandateを取得

            ステータス確認とpayload取得に使用
            """
            try:
                async with self.db_manager.get_session() as session:
                    mandate = await MandateCRUD.get_by_id(session, cart_mandate_id)

                    if not mandate:
                        raise HTTPException(status_code=404, detail="CartMandate not found")

                    # payloadをパース
                    payload = json.loads(mandate.payload) if isinstance(mandate.payload, str) else mandate.payload

                    return {
                        "id": mandate.id,
                        "status": mandate.status,
                        "payload": payload,
                        "created_at": mandate.issued_at.isoformat() if mandate.issued_at else None,
                        "updated_at": mandate.updated_at.isoformat() if mandate.updated_at else None
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[get_cart_mandate] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/cart-mandates/{cart_mandate_id}/approve")
        async def approve_cart_mandate(cart_mandate_id: str):
            """
            POST /cart-mandates/{id}/approve - CartMandate承認・署名
            """
            try:
                async with self.db_manager.get_session() as session:
                    mandate = await MandateCRUD.get_by_id(session, cart_mandate_id)

                    if not mandate:
                        raise HTTPException(status_code=404, detail="CartMandate not found")

                    if mandate.status != "pending_merchant_signature":
                        raise HTTPException(
                            status_code=400,
                            detail=f"CartMandate is not pending approval (status: {mandate.status})"
                        )

                    # mandate.payloadはJSON文字列なのでパース
                    cart_mandate = json.loads(mandate.payload) if isinstance(mandate.payload, str) else mandate.payload

                    # 署名生成
                    signature = await self._sign_cart_mandate(cart_mandate)
                    signed_cart_mandate = cart_mandate.copy()
                    signed_cart_mandate["merchant_signature"] = signature.model_dump()

                    # AP2仕様準拠：merchant_authorization JWT追加
                    merchant_authorization_jwt = self._generate_merchant_authorization_jwt(
                        cart_mandate,
                        self.merchant_id
                    )
                    signed_cart_mandate["merchant_authorization"] = merchant_authorization_jwt

                    # ステータス更新
                    await MandateCRUD.update_status(session, cart_mandate_id, "signed", signed_cart_mandate)

                    logger.info(
                        f"[Merchant] Manually approved and signed CartMandate: {cart_mandate_id} "
                        f"(with merchant_authorization JWT)"
                    )

                    return {
                        "status": "approved",
                        "signed_cart_mandate": signed_cart_mandate,
                        "merchant_signature": signed_cart_mandate["merchant_signature"],
                        "merchant_authorization": merchant_authorization_jwt
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[approve_cart_mandate] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/cart-mandates/{cart_mandate_id}/reject")
        async def reject_cart_mandate(cart_mandate_id: str, reason: Dict[str, Any] = None):
            """
            POST /cart-mandates/{id}/reject - CartMandate却下

            リクエスト:
            {
              "reason": "在庫不足" (optional)
            }
            """
            try:
                async with self.db_manager.get_session() as session:
                    mandate = await MandateCRUD.get_by_id(session, cart_mandate_id)

                    if not mandate:
                        raise HTTPException(status_code=404, detail="CartMandate not found")

                    if mandate.status != "pending_merchant_signature":
                        raise HTTPException(
                            status_code=400,
                            detail=f"CartMandate is not pending approval (status: {mandate.status})"
                        )

                    # ステータス更新
                    await MandateCRUD.update_status(session, cart_mandate_id, "rejected", mandate.payload)

                    rejection_reason = reason.get("reason", "No reason provided") if reason else "No reason provided"
                    logger.info(f"[Merchant] Rejected CartMandate: {cart_mandate_id}, reason: {rejection_reason}")

                    return {
                        "status": "rejected",
                        "cart_mandate_id": cart_mandate_id,
                        "reason": rejection_reason
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[reject_cart_mandate] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.get("/transactions")
        async def get_transactions(status: str = None, limit: int = 100):
            """
            GET /transactions - トランザクション履歴

            クエリパラメータ:
            - status: ステータスフィルター（captured, failed, refunded等）
            - limit: 結果数上限
            """
            try:
                async with self.db_manager.get_session() as session:
                    from v2.common.database import TransactionCRUD

                    if status:
                        transactions = await TransactionCRUD.get_by_status(session, status, limit)
                    else:
                        transactions = await TransactionCRUD.list_all(session, limit)

                    return {
                        "transactions": [t.to_dict() for t in transactions],
                        "total": len(transactions)
                    }

            except Exception as e:
                logger.error(f"[get_transactions] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/products")
        async def create_product(product_data: Dict[str, Any]):
            """
            POST /products - 商品作成

            リクエスト:
            {
              "sku": "SHOE-001",
              "name": "商品名",
              "description": "説明",
              "price": 10000,  // cents単位
              "inventory_count": 100,
              "product_metadata": { "category": "shoes", "brand": "Nike" }
            }
            """
            try:
                async with self.db_manager.get_session() as session:
                    # SKU重複チェック
                    existing = await ProductCRUD.get_by_sku(session, product_data["sku"])
                    if existing:
                        raise HTTPException(status_code=400, detail="SKU already exists")

                    # 商品作成
                    product = await ProductCRUD.create(session, product_data)

                    logger.info(f"[Merchant] Created product: {product.id}, SKU: {product.sku}")

                    return product.to_dict()

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[create_product] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.delete("/products/{product_id}")
        async def delete_product(product_id: str):
            """
            DELETE /products/{id} - 商品削除
            """
            try:
                async with self.db_manager.get_session() as session:
                    product = await ProductCRUD.get_by_id(session, product_id)
                    if not product:
                        raise HTTPException(status_code=404, detail="Product not found")

                    await ProductCRUD.delete(session, product_id)

                    logger.info(f"[Merchant] Deleted product: {product_id}")

                    return {
                        "status": "deleted",
                        "product_id": product_id
                    }

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[delete_product] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

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

            # AP2仕様準拠：merchant_authorization JWT追加
            merchant_authorization_jwt = self._generate_merchant_authorization_jwt(
                cart_mandate,
                self.merchant_id
            )
            signed_cart_mandate["merchant_authorization"] = merchant_authorization_jwt

            logger.info(
                f"[A2A] Signed CartMandate: {cart_mandate['id']} "
                f"(with merchant_authorization JWT)"
            )

            return {
                "type": "ap2.mandates.CartMandate",
                "id": cart_mandate["id"],
                "payload": signed_cart_mandate
            }

        except Exception as e:
            logger.error(f"[handle_cart_mandate_sign_request] Error: {e}", exc_info=True)
            return {
                "type": "ap2.errors.Error",
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

    def _generate_merchant_authorization_jwt(
        self,
        cart_mandate: Dict[str, Any],
        merchant_id: str
    ) -> str:
        """
        AP2仕様準拠のmerchant_authorization JWTを生成

        JWT構造：
        - Header: { "alg": "ES256", "kid": "did:ap2:merchant:xxx#key-1", "typ": "JWT" }
        - Payload: {
            "iss": "did:ap2:merchant:xxx",  // Merchant
            "sub": "did:ap2:merchant:xxx",  // Same as iss
            "aud": "did:ap2:agent:payment_processor",  // Payment Processor
            "iat": <timestamp>,
            "exp": <timestamp + 900>,  // 15分後（AP2仕様では5-15分推奨）
            "jti": <unique_id>,  // リプレイ攻撃防止
            "cart_hash": "<cart_contents_hash>"
          }
        - Signature: ECDSA署名（merchantの秘密鍵）

        AP2仕様参照：
        refs/AP2-main/src/ap2/types/mandate.py - CartMandate.merchant_authorization

        完全なES256署名を使用したJWTを生成
        """
        import base64
        import hashlib
        import time

        now = datetime.now(timezone.utc)

        # 1. Cart Contentsのハッシュ計算
        # CartMandateの署名フィールドを除外してハッシュ化（AP2仕様）
        # compute_mandate_hash関数を使用して一貫性を保つ
        from v2.common.crypto import compute_mandate_hash
        cart_hash = compute_mandate_hash(cart_mandate, hash_format='hex')

        # 2. JWTのHeader
        header = {
            "alg": "ES256",  # ECDSA with SHA-256
            "kid": f"{merchant_id}#key-1",  # Key ID
            "typ": "JWT"
        }

        # 3. JWTのPayload
        payload = {
            "iss": merchant_id,  # Issuer: Merchant
            "sub": merchant_id,  # Subject: Merchant (same as issuer)
            "aud": "did:ap2:agent:payment_processor",  # Audience: Payment Processor
            "iat": int(now.timestamp()),  # Issued At
            "exp": int(now.timestamp()) + 900,  # Expiry: 15分後（AP2仕様推奨）
            "jti": str(uuid.uuid4()),  # JWT ID（リプレイ攻撃防止）
            "cart_hash": cart_hash  # CartContentsのハッシュ
        }

        # 4. Base64url エンコード
        def base64url_encode(data):
            json_str = json.dumps(data, separators=(',', ':'))
            return base64.urlsafe_b64encode(json_str.encode('utf-8')).rstrip(b'=').decode('utf-8')

        header_b64 = base64url_encode(header)
        payload_b64 = base64url_encode(payload)

        # 5. 署名生成
        # AP2仕様: ES256（ECDSA with P-256 and SHA-256）
        try:
            # 秘密鍵を取得（agent_idから鍵IDを抽出）
            key_id = self.agent_id.split(":")[-1]  # did:ap2:merchant -> merchant
            private_key = self.key_manager.get_private_key(key_id)

            if private_key is None:
                raise ValueError(f"Merchant private key not found: {key_id}")

            # 署名対象データ（header_b64.payload_b64）
            message_to_sign = f"{header_b64}.{payload_b64}".encode('utf-8')

            # ECDSA署名（ES256: ECDSA with SHA-256）
            from cryptography.hazmat.primitives import hashes
            from cryptography.hazmat.primitives.asymmetric import ec

            signature_bytes = private_key.sign(
                message_to_sign,
                ec.ECDSA(hashes.SHA256())
            )

            # Base64URLエンコード（パディングなし）
            signature_b64 = base64.urlsafe_b64encode(signature_bytes).rstrip(b'=').decode('utf-8')

            logger.info(
                f"[_generate_merchant_authorization_jwt] Generated signed JWT for CartMandate: "
                f"cart_id={cart_mandate.get('id')}, cart_hash={cart_hash[:16]}..., "
                f"alg=ES256, kid={header['kid']}"
            )

        except Exception as e:
            logger.error(
                f"[_generate_merchant_authorization_jwt] Failed to generate signature: {e}"
            )
            raise ValueError(f"Failed to sign merchant_authorization JWT: {e}")

        # 6. JWT組み立て
        jwt_token = f"{header_b64}.{payload_b64}.{signature_b64}"

        return jwt_token

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
