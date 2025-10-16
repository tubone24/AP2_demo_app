"""
v2/services/shopping_agent/agent.py

Shopping Agent実装
- ユーザーとの対話（Streaming応答）
- IntentMandateの作成
- Merchant Agentへの商品検索依頼（A2A通信）
- CartMandate選択・署名
- PaymentMandate作成
"""

import sys
import uuid
import json
import asyncio
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import logging

import httpx
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import (
    A2AMessage,
    ChatStreamRequest,
    StreamEvent,
    ProductSearchRequest,
)
from v2.common.database import DatabaseManager, MandateCRUD, TransactionCRUD

logger = logging.getLogger(__name__)


class ShoppingAgent(BaseAgent):
    """
    Shopping Agent

    ユーザーの購買代理エージェント
    - ユーザーとの対話（chat/stream）
    - IntentMandateの作成・管理
    - 他エージェントとのA2A通信
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:agent:shopping_agent",
            agent_name="Shopping Agent",
            passphrase=AgentPassphraseManager.get_passphrase("shopping_agent"),
            keys_directory="./keys"
        )

        # データベースマネージャー（絶対パスを使用）
        self.db_manager = DatabaseManager(database_url="sqlite+aiosqlite:////app/v2/data/ap2.db")

        # HTTPクライアント（他エージェントとの通信用）
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # エージェントエンドポイント（Docker Compose環境想定）
        self.merchant_agent_url = "http://merchant_agent:8001"
        self.merchant_url = "http://merchant:8002"
        self.credential_provider_url = "http://credential_provider:8003"
        self.payment_processor_url = "http://payment_processor:8004"

        # セッション管理（簡易版 - インメモリ）
        self.sessions: Dict[str, Dict[str, Any]] = {}

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Shopping Agentが受信するA2Aメッセージ：
        - ap2/CartMandate: Merchant Agentからのカート提案
        - ap2/ProductList: Merchant Agentからの商品リスト
        - ap2/SignatureResponse: Credential Providerからの署名結果
        """
        self.a2a_handler.register_handler("ap2/CartMandate", self.handle_cart_mandate)
        self.a2a_handler.register_handler("ap2/ProductList", self.handle_product_list)
        self.a2a_handler.register_handler("ap2/SignatureResponse", self.handle_signature_response)

    def register_endpoints(self):
        """
        Shopping Agent固有エンドポイントの登録
        """

        @self.app.post("/chat/stream")
        async def chat_stream(request: ChatStreamRequest):
            """
            POST /chat/stream - ユーザーとの対話（SSE Streaming）

            demo_app_v2.md:
            リクエスト： { user_input: string, session_id?: string }

            逐次イベントフォーマット（JSON lines）：
            { "type": "agent_text", "content": "..." }
            { "type": "signature_request", "mandate": { ...IntentMandate... } }
            { "type": "cart_options", "items": [...] }
            """
            session_id = request.session_id or str(uuid.uuid4())

            async def event_generator() -> AsyncGenerator[str, None]:
                try:
                    # セッション初期化
                    if session_id not in self.sessions:
                        self.sessions[session_id] = {
                            "messages": [],
                            "step": "initial",  # 対話フローのステップ
                            "intent": None,
                            "max_amount": None,
                            "categories": [],
                            "brands": [],
                            "intent_mandate": None,
                            "cart_mandate": None,
                        }

                    session = self.sessions[session_id]
                    session["messages"].append({"role": "user", "content": request.user_input})

                    # 固定応答フロー（LLM統合前）
                    async for event in self._generate_fixed_response(request.user_input, session):
                        yield f"data: {json.dumps(event.model_dump(exclude_none=True))}\n\n"
                        await asyncio.sleep(0.1)  # 少し遅延を入れて自然に

                    # 完了イベント
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"

                except Exception as e:
                    logger.error(f"[chat_stream] Error: {e}", exc_info=True)
                    error_event = StreamEvent(type="error", error=str(e))
                    yield f"data: {json.dumps(error_event.model_dump(exclude_none=True))}\n\n"

            return EventSourceResponse(event_generator())

        @self.app.get("/products")
        async def get_products(query: str = "", limit: int = 10):
            """
            GET /products - 商品検索（Merchant Agentへプロキシ）
            """
            try:
                # Merchant Agentに商品検索をA2A経由で依頼
                # （簡易版：直接HTTPで問い合わせ）
                response = await self.http_client.get(
                    f"{self.merchant_agent_url}/search",
                    params={"query": query, "limit": limit}
                )
                response.raise_for_status()
                return response.json()

            except httpx.HTTPError as e:
                logger.error(f"[get_products] HTTP error: {e}")
                raise HTTPException(status_code=502, detail="Failed to fetch products")

        @self.app.get("/transactions/{transaction_id}")
        async def get_transaction(transaction_id: str):
            """
            GET /transactions/{id} - トランザクション取得
            """
            async with self.db_manager.get_session() as session:
                transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                if not transaction:
                    raise HTTPException(status_code=404, detail="Transaction not found")
                return transaction.to_dict()

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_cart_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """CartMandateを受信（Merchant Agentから）"""
        logger.info("[ShoppingAgent] Received CartMandate")
        cart_mandate = message.dataPart.payload

        # データベースに保存
        async with self.db_manager.get_session() as session:
            await MandateCRUD.create(session, {
                "id": cart_mandate["id"],
                "type": "Cart",
                "status": "pending_signature",
                "payload": cart_mandate,
                "issuer": message.header.sender
            })

        return {
            "type": "ap2/Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "cart_mandate_id": cart_mandate["id"]
            }
        }

    async def handle_product_list(self, message: A2AMessage) -> Dict[str, Any]:
        """商品リストを受信（Merchant Agentから）"""
        logger.info("[ShoppingAgent] Received ProductList")
        products = message.dataPart.payload.get("products", [])

        return {
            "type": "ap2/Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "product_count": len(products)
            }
        }

    async def handle_signature_response(self, message: A2AMessage) -> Dict[str, Any]:
        """署名結果を受信（Credential Providerから）"""
        logger.info("[ShoppingAgent] Received SignatureResponse")
        signature_data = message.dataPart.payload

        return {
            "type": "ap2/Acknowledgement",
            "id": str(uuid.uuid4()),
            "payload": {
                "status": "received",
                "verified": signature_data.get("verified", False)
            }
        }

    # ========================================
    # 固定応答フロー（LLM統合前）
    # ========================================

    async def _generate_fixed_response(
        self,
        user_input: str,
        session: Dict[str, Any]
    ) -> AsyncGenerator[StreamEvent, None]:
        """
        固定応答を生成（LLM統合前の簡易版）

        改善されたフロー：
        1. 挨拶 → 質問促す
        2. Intent入力 → 最大金額を質問
        3. 最大金額入力 → カテゴリーを質問（オプション）
        4. カテゴリー入力 → ブランドを質問（オプション）
        5. ブランド入力 → IntentMandate生成 → 署名リクエスト
        6. 署名完了 → 商品検索 → CartMandate提案
        7. カート承認 → PaymentMandate生成 → 決済
        """
        user_input_lower = user_input.lower()
        current_step = session.get("step", "initial")

        # ステップ1: 初回挨拶
        if current_step == "initial":
            if any(word in user_input_lower for word in ["こんにちは", "hello", "hi", "購入", "買い", "探"]):
                yield StreamEvent(
                    type="agent_text",
                    content="こんにちは！AP2 Shopping Agentです。"
                )
                await asyncio.sleep(0.3)
                yield StreamEvent(
                    type="agent_text",
                    content="何をお探しですか？例えば「ランニングシューズが欲しい」のように教えてください。"
                )
                session["step"] = "ask_intent"
                return

            # Intent入力された場合
            session["intent"] = user_input
            session["step"] = "ask_max_amount"

            yield StreamEvent(
                type="agent_text",
                content=f"「{user_input}」ですね！"
            )
            await asyncio.sleep(0.3)
            yield StreamEvent(
                type="agent_text",
                content="最大金額を教えてください。（例：50000円、または50000）"
            )
            return

        # ステップ2: 最大金額を質問
        elif current_step == "ask_intent":
            session["intent"] = user_input
            session["step"] = "ask_max_amount"

            yield StreamEvent(
                type="agent_text",
                content=f"「{user_input}」ですね！"
            )
            await asyncio.sleep(0.3)
            yield StreamEvent(
                type="agent_text",
                content="最大金額を教えてください。（例：50000円、または50000）"
            )
            return

        # ステップ3: 最大金額入力 → カテゴリー質問
        elif current_step == "ask_max_amount":
            # 金額をパース
            import re
            amount_match = re.search(r'(\d+)', user_input)
            if amount_match:
                max_amount = int(amount_match.group(1))
                session["max_amount"] = max_amount

                yield StreamEvent(
                    type="agent_text",
                    content=f"最大金額を{max_amount:,}円に設定しました。"
                )
                await asyncio.sleep(0.3)
                yield StreamEvent(
                    type="agent_text",
                    content="カテゴリーを指定しますか？（例：Running Shoes, Sports Apparel）\n指定しない場合は「スキップ」と入力してください。"
                )
                session["step"] = "ask_categories"
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="金額が認識できませんでした。数字で入力してください。（例：50000）"
                )
            return

        # ステップ4: カテゴリー入力 → ブランド質問
        elif current_step == "ask_categories":
            if "スキップ" in user_input or "skip" in user_input_lower:
                session["categories"] = []
                yield StreamEvent(
                    type="agent_text",
                    content="カテゴリーは指定しません。"
                )
            else:
                # カンマ区切りでカテゴリーを分割
                categories = [c.strip() for c in user_input.split(",")]
                session["categories"] = categories
                yield StreamEvent(
                    type="agent_text",
                    content=f"カテゴリー: {', '.join(categories)}"
                )

            await asyncio.sleep(0.3)
            yield StreamEvent(
                type="agent_text",
                content="ブランドを指定しますか？（例：Nike, Adidas）\n指定しない場合は「スキップ」と入力してください。"
            )
            session["step"] = "ask_brands"
            return

        # ステップ5: ブランド入力 → IntentMandate生成
        elif current_step == "ask_brands":
            if "スキップ" in user_input or "skip" in user_input_lower:
                session["brands"] = []
                yield StreamEvent(
                    type="agent_text",
                    content="ブランドは指定しません。"
                )
            else:
                # カンマ区切りでブランドを分割
                brands = [b.strip() for b in user_input.split(",")]
                session["brands"] = brands
                yield StreamEvent(
                    type="agent_text",
                    content=f"ブランド: {', '.join(brands)}"
                )

            await asyncio.sleep(0.5)

            # IntentMandate生成
            intent_mandate = self._create_intent_mandate(
                session["intent"],
                session
            )
            session["intent_mandate"] = intent_mandate
            session["step"] = "intent_signature_requested"

            yield StreamEvent(
                type="agent_text",
                content="購入条件が確認できました。購入権限（IntentMandate）の署名をお願いします。"
            )
            await asyncio.sleep(0.2)

            # 署名リクエスト
            yield StreamEvent(
                type="signature_request",
                mandate=intent_mandate,
                mandate_type="intent"
            )
            return

        # ステップ6: 署名完了後、商品検索
        elif current_step == "intent_signature_requested":
            if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
                session["step"] = "intent_signed"

                yield StreamEvent(
                    type="agent_text",
                    content="署名ありがとうございます！商品を検索中..."
                )
                await asyncio.sleep(0.5)

                # Merchant Agentに商品検索依頼（固定応答）
                sample_products = [
                    {
                        "id": "prod_001",
                        "sku": "SHOE-RUN-001",
                        "name": "ナイキ エアズーム ペガサス 40",
                        "price": 14800,
                        "image_url": "https://placehold.co/400x400/333/FFF?text=Nike+Pegasus"
                    },
                    {
                        "id": "prod_002",
                        "sku": "SHOE-RUN-002",
                        "name": "アディダス ウルトラブースト 22",
                        "price": 19800,
                        "image_url": "https://placehold.co/400x400/000/FFF?text=Adidas+Ultraboost"
                    }
                ]

                yield StreamEvent(
                    type="cart_options",
                    items=sample_products
                )

                yield StreamEvent(
                    type="agent_text",
                    content="上記の商品が見つかりました。どちらか選択してください。"
                )

                session["step"] = "product_selection"
                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="署名を完了してから「署名完了」と入力してください。"
                )
                return

        # ステップ7: 商品選択後 → CartMandate作成
        elif current_step == "product_selection":
            # 商品IDをパース（"prod_001"や"1"など）
            selected_product = None
            if "prod_001" in user_input or "1" in user_input or "ナイキ" in user_input or "nike" in user_input_lower:
                selected_product = {
                    "id": "prod_001",
                    "sku": "SHOE-RUN-001",
                    "name": "ナイキ エアズーム ペガサス 40",
                    "price": 14800,
                }
            elif "prod_002" in user_input or "2" in user_input or "アディダス" in user_input or "adidas" in user_input_lower:
                selected_product = {
                    "id": "prod_002",
                    "sku": "SHOE-RUN-002",
                    "name": "アディダス ウルトラブースト 22",
                    "price": 19800,
                }

            if not selected_product:
                yield StreamEvent(
                    type="agent_text",
                    content="商品が認識できませんでした。「1」または「2」、または商品名を入力してください。"
                )
                return

            session["selected_product"] = selected_product

            yield StreamEvent(
                type="agent_text",
                content=f"「{selected_product['name']}」を選択しました。"
            )
            await asyncio.sleep(0.3)

            # CartMandateを作成（未署名）
            cart_mandate = self._create_cart_mandate(selected_product, session)

            yield StreamEvent(
                type="agent_text",
                content="カート内容をMerchantに確認中..."
            )
            await asyncio.sleep(0.3)

            # MerchantにCartMandateの署名を依頼
            try:
                signed_cart_mandate = await self._request_merchant_signature(cart_mandate)
                session["cart_mandate"] = signed_cart_mandate
                session["step"] = "cart_signature_requested"

                yield StreamEvent(
                    type="agent_text",
                    content="Merchantの署名を確認しました。カート内容を確認して、あなたの署名をお願いします。"
                )
                await asyncio.sleep(0.2)

                # 署名リクエスト（Merchant署名済みのCartMandateをユーザーに提示）
                yield StreamEvent(
                    type="signature_request",
                    mandate=signed_cart_mandate,
                    mandate_type="cart"
                )
            except Exception as e:
                logger.error(f"[_generate_fixed_response] Merchant signature failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。Merchantの署名取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
            return

        # ステップ8: CartMandate署名完了後 → PaymentMandate作成
        elif current_step == "cart_signature_requested":
            if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
                session["step"] = "cart_signed"

                yield StreamEvent(
                    type="agent_text",
                    content="カートの署名ありがとうございます！決済情報を準備中..."
                )
                await asyncio.sleep(0.5)

                # PaymentMandateを作成
                payment_mandate = self._create_payment_mandate(session)
                session["payment_mandate"] = payment_mandate
                session["step"] = "payment_signature_requested"

                yield StreamEvent(
                    type="agent_text",
                    content="決済承認の署名をお願いします。"
                )
                await asyncio.sleep(0.2)

                # 署名リクエスト
                yield StreamEvent(
                    type="signature_request",
                    mandate=payment_mandate,
                    mandate_type="payment"
                )
                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="署名を完了してから「署名完了」と入力してください。"
                )
                return

        # ステップ9: PaymentMandate署名完了後 → 決済処理
        elif current_step == "payment_signature_requested":
            if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
                session["step"] = "payment_signed"

                yield StreamEvent(
                    type="agent_text",
                    content="決済を処理中..."
                )
                await asyncio.sleep(1.0)

                # 決済処理（簡易版）
                transaction_id = f"txn_{uuid.uuid4().hex[:8]}"
                session["transaction_id"] = transaction_id

                yield StreamEvent(
                    type="agent_text",
                    content=f"✅ 決済が完了しました！\n\n取引ID: {transaction_id}\n商品: {session['selected_product']['name']}\n金額: ¥{session['selected_product']['price']:,}\n\nご購入ありがとうございました！"
                )

                # セッションをリセット
                session["step"] = "completed"
                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="署名を完了してから「署名完了」と入力してください。"
                )
                return

        # ステップ10: 完了後
        elif current_step == "completed":
            yield StreamEvent(
                type="agent_text",
                content="取引は完了しました。新しい購入を始めるには「こんにちは」と入力してください。"
            )
            return

        # デフォルト応答（予期しないステップ）
        yield StreamEvent(
            type="agent_text",
            content=f"申し訳ありません。現在のステップ（{current_step}）では対応できません。「こんにちは」と入力して最初からやり直してください。"
        )

    def _create_intent_mandate(self, intent: str, session: Dict[str, Any]) -> Dict[str, Any]:
        """IntentMandateを作成（セッション情報を使用）"""
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)

        # セッションから情報を取得
        max_amount = session.get("max_amount", 50000)  # デフォルト50000円
        categories = session.get("categories", [])
        brands = session.get("brands", [])

        intent_mandate = {
            "id": f"intent_{uuid.uuid4().hex[:8]}",
            "type": "IntentMandate",
            "version": "0.2",
            "user_id": "user_demo_001",  # 固定（後でセッション管理と統合）
            "user_public_key": "user_public_key_placeholder",
            "intent": intent,
            "constraints": {
                "valid_until": expires_at.isoformat().replace('+00:00', 'Z'),
                "max_amount": {
                    "value": f"{max_amount}.00",
                    "currency": "JPY"
                },
                "categories": categories if categories else [],
                "merchants": [],
                "brands": brands if brands else []
            },
            "created_at": now.isoformat().replace('+00:00', 'Z'),
            "expires_at": expires_at.isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[ShoppingAgent] IntentMandate created: max_amount={max_amount}, categories={categories}, brands={brands}")

        return intent_mandate

    def _create_cart_mandate(self, product: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
        """CartMandateを作成"""
        now = datetime.now(timezone.utc)

        cart_mandate = {
            "id": f"cart_{uuid.uuid4().hex[:8]}",
            "type": "CartMandate",
            "version": "0.2",
            "merchant_id": "did:ap2:merchant:demo_merchant",
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "items": [
                {
                    "product_id": product["id"],
                    "sku": product["sku"],
                    "name": product["name"],
                    "quantity": 1,
                    "unit_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    },
                    "total_price": {
                        "value": f"{product['price']}.00",
                        "currency": "JPY"
                    }
                }
            ],
            "total_amount": {
                "value": f"{product['price']}.00",
                "currency": "JPY"
            },
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[ShoppingAgent] CartMandate created: product={product['name']}, total={product['price']}")

        return cart_mandate

    def _create_payment_mandate(self, session: Dict[str, Any]) -> Dict[str, Any]:
        """PaymentMandateを作成"""
        now = datetime.now(timezone.utc)
        product = session.get("selected_product", {})

        payment_mandate = {
            "id": f"payment_{uuid.uuid4().hex[:8]}",
            "type": "PaymentMandate",
            "version": "0.2",
            "cart_mandate_id": session.get("cart_mandate", {}).get("id"),
            "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
            "payer_id": "user_demo_001",
            "payee_id": "did:ap2:merchant:demo_merchant",
            "amount": {
                "value": f"{product['price']}.00",
                "currency": "JPY"
            },
            "payment_method": {
                "type": "card",
                "token": "pm_001",
                "last4": "4242"
            },
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        logger.info(f"[ShoppingAgent] PaymentMandate created: amount={product['price']}")

        return payment_mandate

    async def _request_merchant_signature(self, cart_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """
        MerchantにCartMandateの署名を依頼

        AP2仕様準拠：
        1. Shopping AgentがCartMandateを作成（未署名）
        2. MerchantがCartMandateに署名
        3. Shopping AgentがMerchant署名を検証
        """
        logger.info(f"[ShoppingAgent] Requesting Merchant signature for CartMandate: {cart_mandate['id']}")

        try:
            # MerchantにPOST /sign/cartで署名依頼
            response = await self.http_client.post(
                f"{self.merchant_url}/sign/cart",
                json={"cart_mandate": cart_mandate},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 署名済みCartMandateを取得
            signed_cart_mandate = result.get("signed_cart_mandate")
            if not signed_cart_mandate:
                raise ValueError("Merchant did not return signed_cart_mandate")

            # Merchant署名を検証
            merchant_signature = signed_cart_mandate.get("merchant_signature")
            if not merchant_signature:
                raise ValueError("CartMandate does not contain merchant_signature")

            # v2.common.models.Signatureに変換
            from v2.common.models import Signature
            signature_obj = Signature(
                algorithm=merchant_signature.get("algorithm", "ECDSA").upper(),
                value=merchant_signature["value"],
                public_key=merchant_signature["public_key"],
                signed_at=merchant_signature["signed_at"]
            )

            # 署名対象データ（merchant_signature除外）
            cart_data_for_verification = signed_cart_mandate.copy()
            cart_data_for_verification.pop("merchant_signature", None)
            cart_data_for_verification.pop("user_signature", None)

            # 署名検証
            is_valid = self.signature_manager.verify_mandate_signature(
                cart_data_for_verification,
                signature_obj
            )

            if not is_valid:
                raise ValueError("Merchant signature verification failed")

            logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate: {cart_mandate['id']}")
            return signed_cart_mandate

        except httpx.HTTPError as e:
            logger.error(f"[_request_merchant_signature] HTTP error: {e}")
            raise ValueError(f"Failed to request Merchant signature: {e}")
        except Exception as e:
            logger.error(f"[_request_merchant_signature] Error: {e}", exc_info=True)
            raise
