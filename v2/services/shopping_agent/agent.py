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
from v2.common.risk_assessment import RiskAssessmentEngine

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
        self.payment_processor_url = "http://payment_processor:8004"

        # 複数のCredential Providerに対応
        self.credential_providers = [
            {
                "id": "cp_demo_001",
                "name": "AP2 Demo Credential Provider",
                "url": "http://credential_provider:8003",
                "description": "デモ用Credential Provider（Passkey対応）",
                "logo_url": "https://example.com/cp_demo_logo.png",
                "supported_methods": ["card", "passkey"]
            },
            {
                "id": "cp_demo_002",
                "name": "Alternative Credential Provider",
                "url": "http://credential_provider:8003",  # デモ環境では同じ
                "description": "代替Credential Provider",
                "logo_url": "https://example.com/cp_alt_logo.png",
                "supported_methods": ["card"]
            }
        ]

        # セッション管理（簡易版 - インメモリ）
        self.sessions: Dict[str, Dict[str, Any]] = {}

        # リスク評価エンジン
        self.risk_engine = RiskAssessmentEngine()

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Shopping Agentが受信するA2Aメッセージ：
        - ap2/CartMandate: Merchant Agentからのカート提案
        - ap2/ProductList: Merchant Agentからの商品リスト
        - ap2/SignatureResponse: Credential Providerからの署名結果
        """
        self.a2a_handler.register_handler("ap2.mandates.CartMandate", self.handle_cart_mandate)
        self.a2a_handler.register_handler("ap2.responses.ProductList", self.handle_product_list)
        self.a2a_handler.register_handler("ap2.responses.SignatureResponse", self.handle_signature_response)

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
            "type": "ap2.responses.Acknowledgement",
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
            "type": "ap2.responses.Acknowledgement",
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
            "type": "ap2.responses.Acknowledgement",
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
                    content="何をお探しですか？例えば「むぎぼーのグッズが欲しい」のように教えてください。"
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
                    content="カテゴリーを指定しますか？（例：カレンダー）\n指定しない場合は「スキップ」と入力してください。"
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
                content="ブランドを指定しますか？\n指定しない場合は「スキップ」と入力してください。"
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

        # ステップ6: 署名完了後、商品検索（Merchant AgentへA2A通信）
        elif current_step == "intent_signature_requested":
            if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
                session["step"] = "intent_signed"

                yield StreamEvent(
                    type="agent_text",
                    content="署名ありがとうございます！Merchant Agentに商品を検索依頼中..."
                )
                await asyncio.sleep(0.5)

                # Merchant AgentにIntentMandateを送信して商品検索依頼（A2A通信）
                try:
                    products = await self._search_products_via_merchant_agent(session["intent_mandate"])

                    if not products:
                        yield StreamEvent(
                            type="agent_text",
                            content="申し訳ありません。条件に合う商品が見つかりませんでした。"
                        )
                        session["step"] = "error"
                        return

                    # 商品リストをセッションに保存
                    session["available_products"] = products

                    yield StreamEvent(
                        type="cart_options",
                        items=products
                    )

                    yield StreamEvent(
                        type="agent_text",
                        content="上記の商品が見つかりました。どちらか選択してください。"
                    )
                except Exception as e:
                    logger.error(f"[_generate_fixed_response] Product search via Merchant Agent failed: {e}")
                    yield StreamEvent(
                        type="agent_text",
                        content=f"申し訳ありません。商品検索に失敗しました: {str(e)}"
                    )
                    session["step"] = "error"
                    return

                session["step"] = "product_selection"
                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="署名を完了してから「署名完了」と入力してください。"
                )
                return

        # ステップ7: 商品選択後 → CartMandate作成（Merchant Agentを経由）
        elif current_step == "product_selection":
            # 利用可能な商品リストから選択
            available_products = session.get("available_products", [])
            if not available_products:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。商品リストが見つかりません。最初からやり直してください。"
                )
                session["step"] = "error"
                return

            # 商品選択（番号または商品名）
            selected_product = None
            user_input_clean = user_input.strip()

            # 番号で選択（1, 2, 3...）
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(available_products):
                    selected_product = available_products[index]

            # 商品IDで選択（"prod_001"など）
            if not selected_product:
                for product in available_products:
                    if product.get("id") in user_input:
                        selected_product = product
                        break

            # 商品名で選択（部分一致）
            if not selected_product:
                for product in available_products:
                    if user_input_lower in product.get("name", "").lower():
                        selected_product = product
                        break

            if not selected_product:
                yield StreamEvent(
                    type="agent_text",
                    content=f"商品が認識できませんでした。番号（1〜{len(available_products)}）または商品名を入力してください。"
                )
                return

            session["selected_product"] = selected_product

            yield StreamEvent(
                type="agent_text",
                content=f"「{selected_product['name']}」を選択しました。"
            )
            await asyncio.sleep(0.3)

            # AP2 Step 2-3: Credential Provider選択
            yield StreamEvent(
                type="agent_text",
                content="決済に使用するCredential Providerを選択してください。"
            )
            await asyncio.sleep(0.2)

            # Credential Providerリストをリッチコンテンツで送信
            yield StreamEvent(
                type="credential_provider_selection",
                providers=self.credential_providers
            )

            session["step"] = "select_credential_provider"
            return

        # ステップ7.1: Credential Provider選択
        elif current_step == "select_credential_provider":
            user_input_clean = user_input.strip()
            selected_provider = None

            # 番号で選択
            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(self.credential_providers):
                    selected_provider = self.credential_providers[index]

            # IDで選択
            if not selected_provider:
                for provider in self.credential_providers:
                    if provider["id"] in user_input:
                        selected_provider = provider
                        break

            if not selected_provider:
                yield StreamEvent(
                    type="agent_text",
                    content=f"Credential Providerが認識できませんでした。番号（1〜{len(self.credential_providers)}）を入力してください。"
                )
                return

            session["selected_credential_provider"] = selected_provider

            yield StreamEvent(
                type="agent_text",
                content=f"{selected_provider['name']}を選択しました。"
            )
            await asyncio.sleep(0.3)

            # AP2 Step 4: 配送先入力（CartMandate作成前に必須）
            yield StreamEvent(
                type="agent_text",
                content="配送先を入力してください。最終的な価格（送料込み）を確定するために必要です。"
            )
            await asyncio.sleep(0.2)

            # 配送先フォームをリッチコンテンツで送信
            yield StreamEvent(
                type="shipping_form_request",
                form_schema={
                    "type": "shipping_address",
                    "fields": [
                        {
                            "name": "recipient",
                            "label": "受取人名",
                            "type": "text",
                            "required": True,
                            "placeholder": "山田太郎"
                        },
                        {
                            "name": "postal_code",
                            "label": "郵便番号",
                            "type": "text",
                            "required": True,
                            "placeholder": "150-0001",
                            "pattern": "\\d{3}-?\\d{4}"
                        },
                        {
                            "name": "address_line1",
                            "label": "住所1（都道府県・市区町村・番地）",
                            "type": "text",
                            "required": True,
                            "placeholder": "東京都渋谷区神宮前1-1-1"
                        },
                        {
                            "name": "address_line2",
                            "label": "住所2（建物名・部屋番号）",
                            "type": "text",
                            "required": False,
                            "placeholder": "サンプルマンション101"
                        },
                        {
                            "name": "country",
                            "label": "国",
                            "type": "select",
                            "required": True,
                            "options": [
                                {"value": "JP", "label": "日本"},
                                {"value": "US", "label": "アメリカ"},
                                {"value": "GB", "label": "イギリス"}
                            ],
                            "default": "JP"
                        }
                    ]
                }
            )

            session["step"] = "input_shipping_address"
            return

        # ステップ7.2: 配送先入力完了 → 支払い方法取得
        elif current_step == "input_shipping_address":
            # JSONとしてパース（フロントエンドからJSONで送信される想定）
            try:
                import json as json_lib
                if user_input.strip().startswith("{"):
                    shipping_address = json_lib.loads(user_input)
                else:
                    # デモ用：固定値を使用
                    shipping_address = {
                        "recipient": "山田太郎",
                        "postal_code": "150-0001",
                        "address_line1": "東京都渋谷区神宮前1-1-1",
                        "address_line2": "サンプルマンション101",
                        "country": "JP"
                    }

                session["shipping_address"] = shipping_address

                yield StreamEvent(
                    type="agent_text",
                    content=f"配送先を設定しました：{shipping_address['recipient']} 様"
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.warning(f"[_generate_fixed_response] Failed to parse shipping address: {e}")
                # デモ用：固定値を使用
                session["shipping_address"] = {
                    "recipient": "山田太郎",
                    "postal_code": "150-0001",
                    "address_line1": "東京都渋谷区神宮前1-1-1",
                    "address_line2": "サンプルマンション101",
                    "country": "JP"
                }

                yield StreamEvent(
                    type="agent_text",
                    content="配送先を設定しました（デモ用固定値）。"
                )
                await asyncio.sleep(0.3)

            # AP2 Step 6-7: Credential Providerから支払い方法を取得
            yield StreamEvent(
                type="agent_text",
                content="Credential Providerから利用可能な支払い方法を取得中..."
            )
            await asyncio.sleep(0.3)

            try:
                # 選択されたCredential Providerから支払い方法を取得
                selected_cp = session.get("selected_credential_provider", self.credential_providers[0])
                payment_methods = await self._get_payment_methods_from_cp("user_demo_001", selected_cp["url"])

                if not payment_methods:
                    yield StreamEvent(
                        type="agent_text",
                        content="申し訳ありません。利用可能な支払い方法が見つかりませんでした。"
                    )
                    session["step"] = "error"
                    return

                session["available_payment_methods"] = payment_methods
                session["step"] = "select_payment_method"

                # 支払い方法をリッチコンテンツで表示
                yield StreamEvent(
                    type="agent_text",
                    content="以下の支払い方法から選択してください。"
                )
                await asyncio.sleep(0.2)

                yield StreamEvent(
                    type="payment_method_selection",
                    payment_methods=payment_methods
                )
                return

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment methods retrieval failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法の取得に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

        # ステップ7.5: 支払い方法選択 → CartMandate作成
        elif current_step == "select_payment_method":
            available_payment_methods = session.get("available_payment_methods", [])
            if not available_payment_methods:
                yield StreamEvent(
                    type="agent_text",
                    content="申し訳ありません。支払い方法リストが見つかりません。"
                )
                session["step"] = "error"
                return

            # 支払い方法選択（番号）
            user_input_clean = user_input.strip()
            selected_payment_method = None

            if user_input_clean.isdigit():
                index = int(user_input_clean) - 1
                if 0 <= index < len(available_payment_methods):
                    selected_payment_method = available_payment_methods[index]

            if not selected_payment_method:
                yield StreamEvent(
                    type="agent_text",
                    content=f"支払い方法が認識できませんでした。番号（1〜{len(available_payment_methods)}）を入力してください。"
                )
                return

            session["selected_payment_method"] = selected_payment_method

            yield StreamEvent(
                type="agent_text",
                content=f"{selected_payment_method['brand'].upper()} ****{selected_payment_method['last4']}を選択しました。"
            )
            await asyncio.sleep(0.3)

            # AP2 Step 17-18: 支払い方法のトークン化
            yield StreamEvent(
                type="agent_text",
                content="Credential Providerで支払い方法をトークン化中..."
            )
            await asyncio.sleep(0.3)

            try:
                # 選択されたCredential Providerを使用してトークン化
                selected_cp = session.get("selected_credential_provider", self.credential_providers[0])
                tokenized_payment_method = await self._tokenize_payment_method(
                    "user_demo_001",
                    selected_payment_method['id'],
                    selected_cp["url"]
                )

                # トークン化された支払い方法をセッションに保存（元の情報も保持）
                session["tokenized_payment_method"] = {
                    **selected_payment_method,
                    "token": tokenized_payment_method["token"],
                    "token_expires_at": tokenized_payment_method["expires_at"]
                }

                yield StreamEvent(
                    type="agent_text",
                    content="支払い方法のトークン化が完了しました。"
                )
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.error(f"[_generate_fixed_response] Payment method tokenization failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。支払い方法のトークン化に失敗しました: {str(e)}"
                )
                session["step"] = "error"
                return

            yield StreamEvent(
                type="agent_text",
                content="Merchant Agentにカート作成・署名を依頼中..."
            )
            await asyncio.sleep(0.3)

            # Merchant AgentにCartRequestを送信（A2A通信）
            # Merchant AgentがCartMandateを作成し、Merchantに署名依頼して、署名済みCartMandateを返却
            try:
                signed_cart_mandate = await self._request_cart_from_merchant_agent(
                    session["selected_product"],
                    session
                )
                session["cart_mandate"] = signed_cart_mandate
                session["step"] = "cart_signature_requested"

                yield StreamEvent(
                    type="agent_text",
                    content="Merchant Agentを経由してMerchantの署名を確認しました。カート内容を確認して、あなたの署名をお願いします。"
                )
                await asyncio.sleep(0.2)

                # 署名リクエスト（Merchant署名済みのCartMandateをユーザーに提示）
                yield StreamEvent(
                    type="signature_request",
                    mandate=signed_cart_mandate,
                    mandate_type="cart"
                )
            except Exception as e:
                logger.error(f"[_generate_fixed_response] CartMandate request via Merchant Agent failed: {e}")
                yield StreamEvent(
                    type="agent_text",
                    content=f"申し訳ありません。Merchant Agentを経由したCartMandateの取得に失敗しました: {str(e)}"
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

        # ステップ9: PaymentMandate署名完了後 → WebAuthn Device Attestation要求（AP2 Step 20-22）
        elif current_step == "payment_signature_requested":
            if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
                session["step"] = "webauthn_attestation_requested"

                # Passkey/WebAuthnを使用することを記録（AP2仕様準拠）
                # transaction_type決定時に使用
                session["will_use_passkey"] = True

                yield StreamEvent(
                    type="agent_text",
                    content="決済の署名ありがとうございます！セキュリティのため、デバイス認証（WebAuthn/Passkey）を実施します。"
                )
                await asyncio.sleep(0.5)

                # WebAuthn challengeを生成（簡易版）
                import secrets
                challenge = secrets.token_urlsafe(32)
                session["webauthn_challenge"] = challenge

                yield StreamEvent(
                    type="webauthn_request",
                    challenge=challenge,
                    rp_id="localhost",
                    timeout=60000
                )

                yield StreamEvent(
                    type="agent_text",
                    content="デバイス認証を完了してから「認証完了」と入力してください。\n（デモ環境では「認証完了」と入力するとスキップできます）"
                )
                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="署名を完了してから「署名完了」と入力してください。"
                )
                return

        # ステップ10: WebAuthn Attestation完了後 → Credential Providerへ検証依頼（AP2 Step 23）
        elif current_step == "webauthn_attestation_requested":
            if "認証完了" in user_input or "attestation" in user_input_lower or user_input_lower == "ok":
                session["step"] = "attestation_verifying"

                yield StreamEvent(
                    type="agent_text",
                    content="デバイス認証を確認しています..."
                )
                await asyncio.sleep(0.5)

                # WebAuthn attestationをモック（実際はフロントエンドから送信される）
                mock_attestation = {
                    "challenge": session.get("webauthn_challenge", ""),
                    "rawId": "mock_credential_id_" + uuid.uuid4().hex[:16],
                    "type": "public-key",
                    "attestation_type": "passkey",
                    "response": {
                        "authenticatorData": "mock_authenticator_data",
                        "clientDataJSON": "mock_client_data_json",
                        "signature": "mock_signature"
                    }
                }

                # AP2 Step 23: PaymentMandate + AttestationをCredential Providerに送信
                try:
                    # 選択されたCredential ProviderのURLを取得
                    selected_cp = session.get("selected_credential_provider", self.credential_providers[0])

                    verification_result = await self._verify_attestation_with_cp(
                        session["payment_mandate"],
                        mock_attestation,
                        selected_cp["url"]
                    )

                    if verification_result.get("verified"):
                        logger.info(f"[ShoppingAgent] WebAuthn attestation verified by Credential Provider")
                        session["attestation_token"] = verification_result.get("token")
                        session["step"] = "payment_processing"

                        yield StreamEvent(
                            type="agent_text",
                            content="✅ デバイス認証が完了しました。決済を処理中..."
                        )
                        await asyncio.sleep(0.5)

                        # Payment ProcessorにPaymentMandateを送信（A2A通信）
                        payment_result = await self._process_payment_via_payment_processor(
                            session["payment_mandate"]
                        )

                        if payment_result.get("status") == "captured":
                            transaction_id = payment_result.get("transaction_id")
                            receipt_url = payment_result.get("receipt_url")

                            session["transaction_id"] = transaction_id

                            yield StreamEvent(
                                type="agent_text",
                                content=f"✅ 決済が完了しました！\n\n取引ID: {transaction_id}\n商品: {session['selected_product']['name']}\n金額: ¥{session['selected_product']['price']:,}\n\n{receipt_url}\n\nご購入ありがとうございました！"
                            )

                            # セッションをリセット
                            session["step"] = "completed"
                        else:
                            # 決済失敗
                            error_message = payment_result.get("error", "決済処理に失敗しました")
                            yield StreamEvent(
                                type="agent_text",
                                content=f"❌ 決済に失敗しました: {error_message}\n\nもう一度お試しください。"
                            )
                            session["step"] = "payment_failed"

                    else:
                        # デバイス認証失敗
                        yield StreamEvent(
                            type="agent_text",
                            content=f"❌ デバイス認証に失敗しました。もう一度お試しください。"
                        )
                        session["step"] = "attestation_failed"

                except Exception as e:
                    logger.error(f"[_generate_fixed_response] Attestation verification or payment processing failed: {e}")
                    yield StreamEvent(
                        type="agent_text",
                        content=f"❌ 処理中にエラーが発生しました: {str(e)}"
                    )
                    session["step"] = "payment_failed"

                return
            else:
                yield StreamEvent(
                    type="agent_text",
                    content="デバイス認証を完了してから「認証完了」と入力してください。"
                )
                return

        # ステップ11: 完了後
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
        """
        IntentMandateを作成（セッション情報を使用）

        AP2仕様準拠（Step 3-4）：
        - Userの公開鍵を取得
        - IntentMandateに署名を追加
        """
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=1)

        # セッションから情報を取得
        max_amount = session.get("max_amount", 50000)  # デフォルト50000円
        categories = session.get("categories", [])
        brands = session.get("brands", [])

        # User IDを取得（デモ用固定値）
        user_id = "user_demo_001"

        # IntentMandate基本情報（署名前）
        intent_mandate_base = {
            "id": f"intent_{uuid.uuid4().hex[:8]}",
            "type": "IntentMandate",
            "version": "0.2",
            "user_id": user_id,
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

        # User公開鍵を取得
        try:
            user_public_key_pem = self.key_manager.get_public_key_pem(user_id)
            intent_mandate_base["user_public_key"] = user_public_key_pem
        except Exception as e:
            logger.warning(f"[ShoppingAgent] Failed to get user public key: {e}. Using placeholder.")
            intent_mandate_base["user_public_key"] = "user_public_key_placeholder"

        # User署名を生成
        try:
            user_signature = self.signature_manager.sign_mandate(intent_mandate_base, user_id)
            intent_mandate = intent_mandate_base.copy()
            intent_mandate["user_signature"] = user_signature.model_dump()

            logger.info(
                f"[ShoppingAgent] IntentMandate created with user signature: "
                f"id={intent_mandate['id']}, max_amount={max_amount}, "
                f"categories={categories}, brands={brands}"
            )
        except Exception as e:
            logger.error(f"[ShoppingAgent] Failed to sign IntentMandate: {e}. Returning unsigned mandate.")
            # 署名失敗時は署名なしで返す（デモ環境での互換性）
            intent_mandate = intent_mandate_base
            logger.warning("[ShoppingAgent] IntentMandate created without user signature (fallback)")

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
        """
        PaymentMandateを作成（リスク評価統合版）

        AP2仕様準拠（Step 19）：
        - トークン化された支払い方法を使用
        - セキュアトークンをPaymentMandateに含める
        - リスク評価を実施してリスクスコアと不正指標を追加
        """
        now = datetime.now(timezone.utc)
        product = session.get("selected_product", {})

        # セッションからトークン化された支払い方法を取得（AP2 Step 17-18）
        tokenized_payment_method = session.get("tokenized_payment_method", {})

        # トークン化された支払い方法が存在しない場合はエラー
        if not tokenized_payment_method or not tokenized_payment_method.get("token"):
            logger.error("[ShoppingAgent] No tokenized payment method available")
            raise ValueError("No tokenized payment method available")

        # PaymentMandateを作成（リスク評価前の基本情報）
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
                "type": tokenized_payment_method.get("type", "card"),
                "token": tokenized_payment_method["token"],  # セキュアトークン（AP2 Step 17-18でトークン化済み）
                "last4": tokenized_payment_method.get("last4", "0000"),
                "brand": tokenized_payment_method.get("brand", "unknown"),
                "expiry_month": tokenized_payment_method.get("expiry_month"),
                "expiry_year": tokenized_payment_method.get("expiry_year")
            },
            # Passkey/WebAuthnを使用している場合はhuman_present（AP2仕様準拠）
            "transaction_type": "human_present" if session.get("will_use_passkey", False) else "human_not_present",
            "agent_involved": True,  # Shopping Agent経由
            "created_at": now.isoformat().replace('+00:00', 'Z')
        }

        # リスク評価を実施
        try:
            logger.info("[ShoppingAgent] Performing risk assessment...")
            risk_result = self.risk_engine.assess_payment_mandate(
                payment_mandate=payment_mandate,
                cart_mandate=session.get("cart_mandate"),
                intent_mandate=session.get("intent_mandate")
            )

            # リスク評価結果をPaymentMandateに追加
            payment_mandate["risk_score"] = risk_result.risk_score
            payment_mandate["fraud_indicators"] = risk_result.fraud_indicators

            logger.info(
                f"[ShoppingAgent] Risk assessment completed: "
                f"score={risk_result.risk_score}, "
                f"recommendation={risk_result.recommendation}, "
                f"indicators={risk_result.fraud_indicators}"
            )

            # 高リスクの場合は警告ログ
            if risk_result.recommendation == "decline":
                logger.warning(
                    f"[ShoppingAgent] High-risk transaction detected! "
                    f"score={risk_result.risk_score}, "
                    f"recommendation={risk_result.recommendation}"
                )

        except Exception as e:
            logger.error(f"[ShoppingAgent] Risk assessment failed: {e}", exc_info=True)
            # リスク評価失敗時はデフォルト値を設定
            payment_mandate["risk_score"] = 50  # 中リスク
            payment_mandate["fraud_indicators"] = ["risk_assessment_failed"]

        logger.info(
            f"[ShoppingAgent] PaymentMandate created: "
            f"amount={product['price']}, "
            f"payment_method={tokenized_payment_method.get('brand')} ****{tokenized_payment_method.get('last4')}, "
            f"token={tokenized_payment_method['token'][:20]}..., "
            f"risk_score={payment_mandate.get('risk_score')}"
        )

        return payment_mandate

    async def _process_payment_via_payment_processor(self, payment_mandate: Dict[str, Any]) -> Dict[str, Any]:
        """
        Payment ProcessorにPaymentMandateを送信して決済処理を依頼

        AP2仕様準拠：
        1. Shopping AgentがPaymentMandateをPayment Processorに送信（A2A通信）
        2. Payment Processorが決済処理を実行
        3. Payment Processorが決済結果を返却
        """
        logger.info(f"[ShoppingAgent] Requesting payment processing for PaymentMandate: {payment_mandate['id']}")

        try:
            # A2Aメッセージを作成（署名付き）
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:payment_processor",
                data_type="ap2.mandates.PaymentMandate",
                data_id=payment_mandate["id"],
                payload=payment_mandate,
                sign=True
            )

            # Payment ProcessorにA2Aメッセージを送信
            response = await self.http_client.post(
                f"{self.payment_processor_url}/a2a/message",
                json=message.model_dump(by_alias=True),
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()

            # A2Aレスポンスからpayloadを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")

                if response_type == "ap2.responses.PaymentResult":
                    payload = data_part["payload"]
                    logger.info(f"[ShoppingAgent] Payment processing completed: status={payload.get('status')}")
                    return payload
                elif response_type == "ap2.errors.Error":
                    error_payload = data_part["payload"]
                    raise ValueError(f"Payment Processor error: {error_payload.get('error_message')}")
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Payment Processor")

        except httpx.HTTPError as e:
            logger.error(f"[_process_payment_via_payment_processor] HTTP error: {e}")
            raise ValueError(f"Failed to process payment: {e}")
        except Exception as e:
            logger.error(f"[_process_payment_via_payment_processor] Error: {e}", exc_info=True)
            raise

    async def _search_products_via_merchant_agent(self, intent_mandate: Dict[str, Any]) -> list[Dict[str, Any]]:
        """
        Merchant AgentにIntentMandateを送信して商品検索を依頼

        AP2仕様準拠（Step 8-9）：
        1. Shopping AgentがIntentMandateをMerchant Agentに送信（A2A通信）
        2. Merchant AgentがIntentMandateに基づいて商品検索
        3. Merchant Agentが商品リストを返却（ap2/ProductList）
        """
        logger.info(f"[ShoppingAgent] Searching products via Merchant Agent for IntentMandate: {intent_mandate['id']}")

        try:
            # A2Aメッセージを作成（署名付き）
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",
                data_type="ap2.mandates.IntentMandate",
                data_id=intent_mandate["id"],
                payload=intent_mandate,
                sign=True
            )

            # Merchant AgentにA2Aメッセージを送信
            response = await self.http_client.post(
                f"{self.merchant_agent_url}/a2a/message",
                json=message.model_dump(by_alias=True),
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()

            # A2Aレスポンスからproductsを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")
                if response_type == "ap2.responses.ProductList":
                    products = data_part["payload"].get("products", [])
                    logger.info(f"[ShoppingAgent] Received {len(products)} products from Merchant Agent")
                    return products
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[_search_products_via_merchant_agent] HTTP error: {e}")
            raise ValueError(f"Failed to search products via Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[_search_products_via_merchant_agent] Error: {e}", exc_info=True)
            raise

    async def _request_cart_from_merchant_agent(
        self,
        selected_product: Dict[str, Any],
        session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Merchant AgentにCartRequestを送信してCartMandateを作成・署名依頼

        AP2仕様準拠（Steps 10-12）：
        1. Shopping AgentがCartRequest（商品選択情報）をMerchant Agentに送信（A2A通信）
        2. Merchant AgentがCartMandateを作成
        3. Merchant AgentがMerchantに署名依頼
        4. Merchant Agentが署名済みCartMandateを返却
        """
        logger.info(f"[ShoppingAgent] Requesting CartMandate from Merchant Agent for product: {selected_product.get('id')}")

        try:
            # CartRequest作成
            cart_request = {
                "intent_mandate_id": session.get("intent_mandate", {}).get("id"),
                "items": [
                    {
                        "product_id": selected_product.get("id"),
                        "quantity": 1
                    }
                ],
                "shipping_address": {
                    "recipient": "山田太郎",
                    "postal_code": "150-0001",
                    "address_line1": "東京都渋谷区神宮前1-1-1",
                    "address_line2": "サンプルマンション101",
                    "country": "JP"
                }
            }

            # A2Aメッセージを作成（署名付き）
            message = self.a2a_handler.create_response_message(
                recipient="did:ap2:agent:merchant_agent",
                data_type="ap2.requests.CartRequest",
                data_id=str(uuid.uuid4()),
                payload=cart_request,
                sign=True
            )

            # Merchant AgentにA2Aメッセージを送信
            response = await self.http_client.post(
                f"{self.merchant_agent_url}/a2a/message",
                json=message.model_dump(by_alias=True),
                timeout=30.0
            )
            response.raise_for_status()
            result = response.json()

            # A2AレスポンスからCartMandateを抽出
            if isinstance(result, dict) and "dataPart" in result:
                data_part = result["dataPart"]
                # @typeエイリアスを使用
                response_type = data_part.get("@type") or data_part.get("type")

                if response_type == "ap2.mandates.CartMandate":
                    signed_cart_mandate = data_part["payload"]
                    logger.info(f"[ShoppingAgent] Received signed CartMandate from Merchant Agent: {signed_cart_mandate.get('id')}")

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

                    logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate")
                    return signed_cart_mandate

                elif response_type == "ap2.responses.CartMandatePending":
                    # 手動署名モード：Merchantの承認待ち
                    pending_info = data_part["payload"]
                    cart_mandate_id = pending_info.get("cart_mandate_id")
                    message = pending_info.get("message", "Merchant approval required")
                    logger.info(f"[ShoppingAgent] CartMandate is pending merchant approval: {cart_mandate_id}. Waiting for approval...")

                    # Merchantの承認/拒否を待機（ポーリング）
                    signed_cart_mandate = await self._wait_for_merchant_approval(cart_mandate_id)
                    return signed_cart_mandate

                elif response_type == "ap2.errors.Error":
                    error_payload = data_part["payload"]
                    raise ValueError(f"Merchant Agent error: {error_payload.get('error_message')}")
                else:
                    raise ValueError(f"Unexpected response type: {response_type}")
            else:
                raise ValueError("Invalid response format from Merchant Agent")

        except httpx.HTTPError as e:
            logger.error(f"[_request_cart_from_merchant_agent] HTTP error: {e}")
            raise ValueError(f"Failed to request CartMandate from Merchant Agent: {e}")
        except Exception as e:
            logger.error(f"[_request_cart_from_merchant_agent] Error: {e}", exc_info=True)
            raise

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

    async def _get_payment_methods_from_cp(self, user_id: str, credential_provider_url: str) -> list[Dict[str, Any]]:
        """
        Credential Providerから支払い方法を取得

        AP2仕様準拠（Step 6-7）：
        1. Shopping AgentがCredential Providerに支払い方法リストを要求
        2. Credential Providerが利用可能な支払い方法を返却
        """
        logger.info(f"[ShoppingAgent] Requesting payment methods from Credential Provider ({credential_provider_url}) for user: {user_id}")

        try:
            # Credential ProviderにGET /payment-methodsで支払い方法取得
            response = await self.http_client.get(
                f"{credential_provider_url}/payment-methods",
                params={"user_id": user_id},
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 支払い方法リストを取得
            payment_methods = result.get("payment_methods", [])
            if not payment_methods:
                logger.warning(f"[ShoppingAgent] No payment methods found for user: {user_id}")
                return []

            logger.info(f"[ShoppingAgent] Retrieved {len(payment_methods)} payment methods from Credential Provider")
            return payment_methods

        except httpx.HTTPError as e:
            logger.error(f"[_get_payment_methods_from_cp] HTTP error: {e}")
            raise ValueError(f"Failed to get payment methods from Credential Provider: {e}")
        except Exception as e:
            logger.error(f"[_get_payment_methods_from_cp] Error: {e}", exc_info=True)
            raise

    async def _tokenize_payment_method(self, user_id: str, payment_method_id: str, credential_provider_url: str) -> Dict[str, Any]:
        """
        Credential Providerで支払い方法をトークン化

        AP2仕様準拠（Step 17-18）：
        1. Shopping AgentがCredential Providerに支払い方法のトークン化を要求
        2. Credential Providerが一時的なセキュアトークンを生成して返却
        """
        logger.info(f"[ShoppingAgent] Requesting payment method tokenization for: {payment_method_id}")

        try:
            # Credential ProviderにPOST /payment-methods/tokenizeでトークン化依頼
            response = await self.http_client.post(
                f"{credential_provider_url}/payment-methods/tokenize",
                json={
                    "user_id": user_id,
                    "payment_method_id": payment_method_id
                },
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # トークン化結果を取得
            token = result.get("token")
            if not token:
                raise ValueError("Credential Provider did not return token")

            logger.info(f"[ShoppingAgent] Payment method tokenized: {payment_method_id} → {token[:20]}...")
            return result

        except httpx.HTTPError as e:
            logger.error(f"[_tokenize_payment_method] HTTP error: {e}")
            raise ValueError(f"Failed to tokenize payment method: {e}")
        except Exception as e:
            logger.error(f"[_tokenize_payment_method] Error: {e}", exc_info=True)
            raise

    async def _verify_attestation_with_cp(
        self,
        payment_mandate: Dict[str, Any],
        attestation: Dict[str, Any],
        credential_provider_url: str
    ) -> Dict[str, Any]:
        """
        Credential ProviderにWebAuthn attestationを検証依頼

        AP2仕様準拠（Step 20-22, 23）：
        1. Shopping AgentがPaymentMandate + AttestationをCredential Providerに送信
        2. Credential ProviderがWebAuthn attestationを検証
        3. 検証成功時、Credential Providerが認証トークンを発行
        """
        logger.info(f"[ShoppingAgent] Verifying WebAuthn attestation with Credential Provider ({credential_provider_url}) for PaymentMandate: {payment_mandate.get('id')}")

        try:
            # Credential ProviderにPOST /verify/attestationで検証依頼
            response = await self.http_client.post(
                f"{credential_provider_url}/verify/attestation",
                json={
                    "payment_mandate": payment_mandate,
                    "attestation": attestation
                },
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 検証結果を取得
            verified = result.get("verified", False)
            if verified:
                token = result.get("token")
                logger.info(f"[ShoppingAgent] WebAuthn attestation verified successfully: token={token[:20] if token else 'N/A'}...")
            else:
                logger.warning(f"[ShoppingAgent] WebAuthn attestation verification failed: {result.get('details')}")

            return result

        except httpx.HTTPError as e:
            logger.error(f"[_verify_attestation_with_cp] HTTP error: {e}")
            raise ValueError(f"Failed to verify attestation with Credential Provider: {e}")
        except Exception as e:
            logger.error(f"[_verify_attestation_with_cp] Error: {e}", exc_info=True)
            raise

    async def _wait_for_merchant_approval(self, cart_mandate_id: str, timeout: int = 120, poll_interval: int = 3) -> Dict[str, Any]:
        """
        Merchantの承認/拒否を待機（ポーリング）

        Args:
            cart_mandate_id: CartMandate ID
            timeout: 最大待機時間（秒）、デフォルト120秒
            poll_interval: ポーリング間隔（秒）、デフォルト3秒

        Returns:
            Dict[str, Any]: 署名済みCartMandate

        Raises:
            ValueError: タイムアウトまたは拒否された場合
        """
        logger.info(f"[ShoppingAgent] Waiting for merchant approval for CartMandate: {cart_mandate_id}, timeout={timeout}s")

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

                logger.debug(f"[ShoppingAgent] CartMandate {cart_mandate_id} status: {status}")

                # 署名完了
                if status == "signed":
                    logger.info(f"[ShoppingAgent] CartMandate {cart_mandate_id} has been approved and signed by merchant")

                    # Merchant署名を検証
                    merchant_signature = payload.get("merchant_signature")
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
                    cart_data_for_verification = payload.copy()
                    cart_data_for_verification.pop("merchant_signature", None)
                    cart_data_for_verification.pop("user_signature", None)

                    # 署名検証
                    is_valid = self.signature_manager.verify_mandate_signature(
                        cart_data_for_verification,
                        signature_obj
                    )

                    if not is_valid:
                        raise ValueError("Merchant signature verification failed")

                    logger.info(f"[ShoppingAgent] Merchant signature verified for CartMandate: {cart_mandate_id}")
                    return payload

                # 拒否された
                elif status == "rejected":
                    logger.warning(f"[ShoppingAgent] CartMandate {cart_mandate_id} has been rejected by merchant")
                    raise ValueError(f"CartMandateがMerchantに拒否されました（ID: {cart_mandate_id}）")

                # まだpending - 待機
                elif status == "pending_merchant_signature":
                    logger.debug(f"[ShoppingAgent] CartMandate {cart_mandate_id} is still pending, waiting...")
                    await asyncio.sleep(poll_interval)
                    elapsed_time = asyncio.get_event_loop().time() - start_time
                    continue

                # 予期しないステータス
                else:
                    logger.warning(f"[ShoppingAgent] Unexpected CartMandate status: {status}")
                    await asyncio.sleep(poll_interval)
                    elapsed_time = asyncio.get_event_loop().time() - start_time
                    continue

            except httpx.HTTPError as e:
                logger.error(f"[_wait_for_merchant_approval] HTTP error while checking status: {e}")
                await asyncio.sleep(poll_interval)
                elapsed_time = asyncio.get_event_loop().time() - start_time
                continue

            except Exception as e:
                logger.error(f"[_wait_for_merchant_approval] Error while checking status: {e}")
                raise

        # タイムアウト
        logger.error(f"[ShoppingAgent] Timeout waiting for merchant approval for CartMandate: {cart_mandate_id}")
        raise ValueError(f"Merchantの承認待ちがタイムアウトしました（ID: {cart_mandate_id}、{timeout}秒経過）。Merchant Dashboardで承認してください。")
