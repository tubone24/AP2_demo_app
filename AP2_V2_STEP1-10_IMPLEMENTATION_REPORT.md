# AP2 v2実装 Step 1-10 詳細調査レポート

## 概要

本レポートは、AP2プロトコル仕様のStep 1-10に該当するv2実装の詳細調査結果をまとめたものです。

調査対象ファイル：
- `/Users/kagadminmac/project/ap2/v2/services/shopping_agent/agent.py`
- `/Users/kagadminmac/project/ap2/v2/services/merchant_agent/agent.py`
- `/Users/kagadminmac/project/ap2/v2/services/merchant/service.py`
- `/Users/kagadminmac/project/ap2/v2/services/credential_provider/provider.py`

---

## Step 1-2: User → Shopping Agent (Intent入力)

### 実装箇所
**ファイル**: `shopping_agent/agent.py`

**エンドポイント**:
```python
@self.app.post("/chat/stream")
async def chat_stream(request: ChatStreamRequest)
```

**メソッド**:
```python
async def _generate_fixed_response(user_input, session, session_id)
```

### 処理フロー

#### Step 1: 初回挨拶（Line 1056-1069）
```python
if current_step == "initial":
    if any(word in user_input_lower for word in ["こんにちは", "hello", "hi", "購入", "買い", "探"]):
        yield StreamEvent(type="agent_text", content="こんにちは！AP2 Shopping Agentです。")
        yield StreamEvent(type="agent_text", content="何をお探しですか？例えば「むぎぼーのグッズが欲しい」のように教えてください。")
        session["step"] = "ask_intent"
```

#### Step 2: Intent入力受付（Line 1087-1100）
```python
elif current_step == "ask_intent":
    session["intent"] = user_input
    session["step"] = "ask_max_amount"

    yield StreamEvent(type="agent_text", content=f"「{user_input}」ですね！")
    yield StreamEvent(type="agent_text", content="最大金額を教えてください。（例：50000円、または50000）")
```

### データ構造
- **セッション管理**: インメモリ + データベース永続化
  ```python
  session = {
      "messages": [],
      "step": "initial",  # → "ask_intent" → "ask_max_amount"
      "intent": str,
      "user_id": "user_demo_001"
  }
  ```

### 通信方式
- **プロトコル**: HTTP POST (Server-Sent Events)
- **フォーマット**: JSON lines形式のStreaming
- **エンドポイント**: `/chat/stream`

---

## Step 3: 購入条件入力（最大金額・カテゴリー・ブランド）

### 実装箇所
**ファイル**: `shopping_agent/agent.py`

### 処理フロー

#### 最大金額入力（Line 1102-1126）
```python
elif current_step == "ask_max_amount":
    import re
    amount_match = re.search(r'(\d+)', user_input)
    if amount_match:
        max_amount = int(amount_match.group(1))
        session["max_amount"] = max_amount

        yield StreamEvent(type="agent_text", content=f"最大金額を{max_amount:,}円に設定しました。")
        yield StreamEvent(type="agent_text", content="カテゴリーを指定しますか？（例：カレンダー）\n指定しない場合は「スキップ」と入力してください。")
        session["step"] = "ask_categories"
```

#### カテゴリー入力（Line 1128-1151）
```python
elif current_step == "ask_categories":
    if "スキップ" in user_input or "skip" in user_input_lower:
        session["categories"] = []
    else:
        categories = [c.strip() for c in user_input.split(",")]
        session["categories"] = categories

    yield StreamEvent(type="agent_text", content="ブランドを指定しますか？\n指定しない場合は「スキップ」と入力してください。")
    session["step"] = "ask_brands"
```

#### ブランド入力（Line 1153-1169）
```python
elif current_step == "ask_brands":
    if "スキップ" in user_input or "skip" in user_input_lower:
        session["brands"] = []
    else:
        brands = [b.strip() for b in user_input.split(",")]
        session["brands"] = brands
```

### データ構造
```python
session = {
    "max_amount": int,        # 円単位
    "categories": List[str],  # ["カレンダー", "Tシャツ"]
    "brands": List[str]       # ["むぎぼー"]
}
```

---

## Step 4: IntentMandate作成と署名

### 実装箇所
**ファイル**: `shopping_agent/agent.py`

### IntentMandate作成（Line 2143-2208）
```python
def _create_intent_mandate(self, intent: str, session: Dict[str, Any]) -> Dict[str, Any]:
    """
    IntentMandateを作成（署名なし）

    専門家の指摘対応：
    - サーバー署名は使用しない
    - ユーザーPasskey署名はフロントエンドで追加される
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=1)

    max_amount = session.get("max_amount", 50000)
    categories = session.get("categories", [])
    brands = session.get("brands", [])
    user_id = "user_demo_001"

    intent_mandate_unsigned = {
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

    return intent_mandate_unsigned
```

### WebAuthn Challenge生成（Line 143-185）
```python
@self.app.post("/intent/challenge")
async def generate_intent_challenge(request: Dict[str, Any]):
    """
    POST /intent/challenge - Intent署名用のWebAuthn challengeを生成

    専門家の指摘に対応：IntentMandateはユーザーPasskey署名を使用する
    """
    user_id = request.get("user_id", "user_demo_001")
    intent_data = request.get("intent_data", {})

    # WebAuthn challengeを生成
    challenge_info = self.webauthn_challenge_manager.generate_challenge(
        user_id=user_id,
        context="intent_mandate_signature"
    )

    return {
        "challenge_id": challenge_info["challenge_id"],
        "challenge": challenge_info["challenge"],
        "intent_data": intent_data,
        "rp_id": "localhost",
        "timeout": 60000
    }
```

### Passkey署名付きIntentMandate受信（Line 187-261）
```python
@self.app.post("/intent/submit")
async def submit_signed_intent_mandate(request: Dict[str, Any]):
    """
    POST /intent/submit - Passkey署名付きIntentMandateを受け取る
    """
    intent_mandate = request.get("intent_mandate", {})
    passkey_signature = request.get("passkey_signature", {})

    # challengeを検証・消費
    challenge_id = passkey_signature.get("challenge_id")
    challenge = passkey_signature.get("challenge")
    user_id = intent_mandate.get("user_id", "user_demo_001")

    is_valid_challenge = self.webauthn_challenge_manager.verify_and_consume_challenge(
        challenge_id=challenge_id,
        challenge=challenge,
        user_id=user_id
    )

    if not is_valid_challenge:
        raise HTTPException(status_code=400, detail="Invalid or expired challenge")

    # IntentMandateにPasskey署名を追加
    intent_mandate["passkey_signature"] = passkey_signature

    # データベースに保存（A2A通信で使用）
    async with self.db_manager.get_session() as session:
        await MandateCRUD.create(session, {
            "id": intent_mandate["id"],
            "type": "Intent",
            "status": "signed",
            "payload": intent_mandate,
            "issuer": user_id
        })

    return {
        "status": "success",
        "intent_mandate_id": intent_mandate["id"]
    }
```

### データ構造（IntentMandate）
```python
{
    "id": "intent_abc12345",
    "type": "IntentMandate",
    "version": "0.2",
    "user_id": "user_demo_001",
    "intent": "むぎぼーのグッズが欲しい",
    "constraints": {
        "valid_until": "2025-10-20T15:00:00Z",
        "max_amount": {
            "value": "50000.00",
            "currency": "JPY"
        },
        "categories": ["カレンダー"],
        "merchants": [],
        "brands": ["むぎぼー"]
    },
    "created_at": "2025-10-20T14:00:00Z",
    "expires_at": "2025-10-20T15:00:00Z",
    "passkey_signature": {
        "challenge_id": "ch_xyz789",
        "challenge": "base64url_encoded_challenge",
        "clientDataJSON": "base64url_encoded_client_data",
        "authenticatorData": "base64url_encoded_auth_data",
        "signature": "base64url_encoded_signature",
        "userHandle": "base64url_encoded_user_handle"
    }
}
```

### 署名処理
- **署名方式**: WebAuthn (Passkey)
- **署名場所**: フロントエンド（ユーザーデバイス）
- **署名対象**: IntentMandate全体（constraints含む）
- **検証**: Challenge-Responseによるリプレイ攻撃防止

---

## Step 5: 配送先入力（AP2仕様準拠）

### 実装箇所
**ファイル**: `shopping_agent/agent.py`

### 配送先入力フォーム送信（Line 1194-1262）
```python
elif current_step == "intent_signature_requested":
    if "署名完了" in user_input or "signed" in user_input_lower or user_input_lower == "ok":
        # AP2仕様：配送先はCartMandate作成「前」に確定する必要がある
        # 配送先によって配送料が変わり、カート価格に影響するため

        yield StreamEvent(
            type="agent_text",
            content="署名ありがとうございます！商品の配送先を入力してください。"
        )

        existing_shipping = session.get("shipping_address", {})

        yield StreamEvent(
            type="shipping_form_request",
            form_schema={
                "type": "shipping_address",
                "fields": [
                    {
                        "name": "recipient",
                        "label": "受取人名",
                        "type": "text",
                        "placeholder": "山田太郎",
                        "default": existing_shipping.get("recipient", ""),
                        "required": True
                    },
                    {
                        "name": "postal_code",
                        "label": "郵便番号",
                        "type": "text",
                        "placeholder": "150-0001",
                        "default": existing_shipping.get("postal_code", ""),
                        "required": True
                    },
                    {
                        "name": "address_line1",
                        "label": "住所1（都道府県・市区町村・番地）",
                        "type": "text",
                        "placeholder": "東京都渋谷区神宮前1-1-1",
                        "default": existing_shipping.get("address_line1", ""),
                        "required": True
                    },
                    {
                        "name": "address_line2",
                        "label": "住所2（建物名・部屋番号など）",
                        "type": "text",
                        "placeholder": "サンプルマンション101",
                        "default": existing_shipping.get("address_line2", ""),
                        "required": False
                    },
                    {
                        "name": "country",
                        "label": "国",
                        "type": "select",
                        "options": [
                            {"value": "JP", "label": "日本"},
                            {"value": "US", "label": "アメリカ"}
                        ],
                        "default": existing_shipping.get("country", "JP") if existing_shipping else "JP",
                        "required": True
                    }
                ]
            }
        )

        session["step"] = "shipping_address_input"
```

### 配送先入力受付（Line 1270-1317）
```python
elif current_step == "shipping_address_input":
    shipping_address = None

    try:
        import json as json_lib

        # JSONパースを試行
        if user_input.strip().startswith("{"):
            shipping_address = json_lib.loads(user_input)
        else:
            logger.warning(f"[shipping_address_input] user_input does not start with '{{', using demo address")

    except json_lib.JSONDecodeError as e:
        logger.error(f"[shipping_address_input] JSON parse error: {e}")

    # フォールバック：デモ用固定値を使用
    if not shipping_address:
        shipping_address = {
            "recipient": "デモユーザー",
            "postal_code": "150-0001",
            "address_line1": "東京都渋谷区渋谷1-1-1",
            "address_line2": "",
            "city": "渋谷区",
            "state": "東京都",
            "country": "JP"
        }

    session["shipping_address"] = shipping_address
```

### データ構造（配送先住所）
```python
{
    "recipient": "山田太郎",
    "postal_code": "150-0001",
    "address_line1": "東京都渋谷区神宮前1-1-1",
    "address_line2": "サンプルマンション101",
    "city": "渋谷区",
    "state": "東京都",
    "country": "JP"
}
```

### AP2仕様準拠のポイント
- **タイミング**: CartMandate作成「前」に配送先を確定
- **理由**: 配送料計算に必要（カート合計金額に影響）
- **フロー**: Intent署名 → 配送先入力 → CartMandate作成

---

## Step 6-7: Credential Provider選択と支払い方法取得

### 実装箇所
**ファイル**: `shopping_agent/agent.py`, `credential_provider/provider.py`

### Credential Provider選択（Line 1679-1767）
```python
elif current_step == "select_credential_provider":
    user_input_clean = user_input.strip()
    selected_provider = None

    # 番号で選択
    if user_input_clean.isdigit():
        index = int(user_input_clean) - 1
        if 0 <= index < len(self.credential_providers):
            selected_provider = self.credential_providers[index]

    session["selected_credential_provider"] = selected_provider

    # 支払い方法を取得
    payment_methods = await self._get_payment_methods_from_cp("user_demo_001", selected_provider["url"])

    session["available_payment_methods"] = payment_methods
    session["step"] = "select_payment_method"

    yield StreamEvent(
        type="payment_method_selection",
        payment_methods=payment_methods
    )
```

### 支払い方法取得（Credential Provider側）
**ファイル**: `credential_provider/provider.py` (Line 434-448)

```python
@self.app.get("/payment-methods")
async def get_payment_methods(user_id: str):
    """
    GET /payment-methods?user_id=... - 支払い方法一覧取得
    """
    methods = self.payment_methods.get(user_id, [])
    return {
        "user_id": user_id,
        "payment_methods": methods
    }
```

### Credential Providerデータ構造
```python
self.credential_providers = [
    {
        "id": "cp_demo_001",
        "name": "AP2 Demo Credential Provider",
        "url": "http://credential_provider:8003",
        "description": "デモ用Credential Provider（Passkey対応）",
        "logo_url": "https://example.com/cp_demo_logo.png",
        "supported_methods": ["card", "passkey"]
    }
]
```

### 支払い方法データ構造
```python
{
    "id": "pm_001",
    "type": "card",
    "token": "tok_visa_4242",
    "last4": "4242",
    "brand": "visa",
    "expiry_month": 12,
    "expiry_year": 2025,
    "holder_name": "山田太郎",
    "requires_step_up": False  # Step-up不要
}
```

### 通信方式
- **プロトコル**: HTTP GET
- **エンドポイント**: `http://credential_provider:8003/payment-methods?user_id=user_demo_001`
- **レスポンス**: JSON

---

## Step 8-9: Shopping Agent → Merchant Agent (IntentMandate送信・カート候補取得)

### 実装箇所
**ファイル**: `shopping_agent/agent.py`, `merchant_agent/agent.py`

### Shopping Agent側：IntentMandate送信とカート候補取得（Line 1319-1368）
```python
# Merchant AgentにIntentMandateと配送先を送信してカート候補を取得（A2A通信）
try:
    cart_candidates = await self._search_products_via_merchant_agent(
        session["intent_mandate"],
        session  # intent_message_idと shipping_addressを参照
    )

    if not cart_candidates:
        yield StreamEvent(
            type="agent_text",
            content="申し訳ありません。条件に合うカート候補が見つかりませんでした。"
        )
        session["step"] = "error"
        return

    # カート候補をセッションに保存
    session["cart_candidates"] = cart_candidates

    # AP2/A2A仕様準拠：複数のカート候補をカルーセル表示
    yield StreamEvent(
        type="cart_options",
        items=cart_candidates
    )
```

### `_search_products_via_merchant_agent`メソッド（推定実装）
※ファイルの読み込み範囲外でしたが、A2Aハンドラー登録から推定：

```python
async def _search_products_via_merchant_agent(
    self,
    intent_mandate: Dict[str, Any],
    session: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    Merchant AgentにIntentMandateを送信し、カート候補を取得

    A2A通信を使用
    """
    # A2Aメッセージを作成
    a2a_message = self.a2a_handler.create_response_message(
        recipient="did:ap2:agent:merchant_agent",
        data_type="ap2.mandates.IntentMandate",
        data_id=intent_mandate["id"],
        payload={
            "intent_mandate": intent_mandate,
            "shipping_address": session.get("shipping_address")
        },
        sign=True
    )

    # Merchant AgentにA2Aメッセージを送信
    response = await self.http_client.post(
        f"{self.merchant_agent_url}/a2a/message",
        json=a2a_message.model_dump(by_alias=True),
        timeout=30.0
    )
    response.raise_for_status()
    result = response.json()

    # カート候補を抽出
    data_part = result["dataPart"]
    cart_candidates = data_part["payload"]["cart_candidates"]

    return cart_candidates
```

### Merchant Agent側：IntentMandate受信とカート候補生成（Line 240-332）
**ファイル**: `merchant_agent/agent.py`

```python
async def handle_intent_mandate(self, message: A2AMessage) -> Dict[str, Any]:
    """
    IntentMandateを受信（Shopping Agentから）

    AP2/A2A仕様準拠：
    - IntentMandateから複数のカート候補を生成
    - 各カートをArtifactとして返却
    """
    logger.info("[MerchantAgent] Received IntentMandate")
    payload = message.dataPart.payload

    # AP2仕様準拠：ペイロードからintent_mandateとshipping_addressを抽出
    if isinstance(payload, dict) and "intent_mandate" in payload:
        intent_mandate = payload["intent_mandate"]
        shipping_address = payload.get("shipping_address")
        logger.info("[MerchantAgent] Received IntentMandate with shipping_address (AP2 v0.1 compliant)")
    else:
        intent_mandate = payload
        shipping_address = None
        logger.info("[MerchantAgent] Received IntentMandate without shipping_address (legacy format)")

    # Intent内容から商品を検索
    intent_text = intent_mandate.get("intent", "")

    # 配送先住所の決定
    if shipping_address:
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

    # 複数のカート候補を生成
    cart_candidates = await self._create_multiple_cart_candidates(
        intent_mandate_id=intent_mandate["id"],
        intent_text=intent_text,
        shipping_address=shipping_address
    )

    if not cart_candidates:
        return {
            "type": "ap2.errors.Error",
            "id": str(uuid.uuid4()),
            "payload": {
                "error_code": "no_products_found",
                "error_message": f"No products found matching intent: {intent_text}"
            }
        }

    # 各カート候補をArtifactとして返却
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
```

### カート候補並列生成（Line 662-754）
```python
async def _create_multiple_cart_candidates(
    self,
    intent_mandate_id: str,
    intent_text: str,
    shipping_address: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """
    IntentMandateから複数のカート候補を生成

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

    # ステップ1: すべてのカート候補の定義を作成（署名依頼前）
    cart_definitions = []

    # 戦略1: 人気順
    cart_definitions.append({
        "products": products[:3],
        "quantities": [1] * min(3, len(products)),
        "name": "人気商品セット",
        "description": "検索結果で人気の商品を組み合わせたカートです"
    })

    # 戦略2: 低価格順
    if len(products) >= 2:
        sorted_by_price = sorted(products, key=lambda p: p.price)
        cart_definitions.append({
            "products": sorted_by_price[:3],
            "quantities": [1] * min(3, len(sorted_by_price)),
            "name": "お得なセット",
            "description": "価格を抑えた組み合わせのカートです"
        })

    # 戦略3: プレミアム
    if len(products) >= 3:
        sorted_by_price_desc = sorted(products, key=lambda p: p.price, reverse=True)
        cart_definitions.append({
            "products": sorted_by_price_desc[:2],
            "quantities": [1] * min(2, len(sorted_by_price_desc)),
            "name": "プレミアムセット",
            "description": "高品質な商品を厳選したカートです"
        })

    # ステップ2: すべてのカート候補を並列で作成・署名依頼
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

    return cart_candidates
```

### データ構造（A2Aメッセージ）
```python
{
    "header": {
        "message_id": "msg_abc123",
        "sender": "did:ap2:agent:shopping_agent",
        "recipient": "did:ap2:agent:merchant_agent",
        "timestamp": "2025-10-20T14:00:00Z"
    },
    "dataPart": {
        "@type": "ap2.mandates.IntentMandate",
        "id": "intent_abc12345",
        "payload": {
            "intent_mandate": {
                "id": "intent_abc12345",
                "intent": "むぎぼーのグッズが欲しい",
                "constraints": { ... },
                "passkey_signature": { ... }
            },
            "shipping_address": {
                "recipient": "山田太郎",
                "postal_code": "150-0001",
                ...
            }
        }
    },
    "signature": "base64_encoded_signature"
}
```

### 通信方式
- **プロトコル**: A2A (Agent-to-Agent) over HTTP
- **エンドポイント**: `http://merchant_agent:8001/a2a/message`
- **署名**: ECDSA署名（Shopping Agentの秘密鍵）
- **並列処理**: `asyncio.gather`でカート候補を同時生成

---

## Step 10-11: Merchant Agent → Merchant (CartMandate署名依頼)

### 実装箇所
**ファイル**: `merchant_agent/agent.py`, `merchant/service.py`

### CartMandate作成（Merchant Agent側）（Line 756-855）
**ファイル**: `merchant_agent/agent.py`

```python
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
    """
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
```

### Merchantへの署名依頼（Line 857-933）
```python
    # MerchantにCartMandateの署名を依頼
    try:
        response = await self.http_client.post(
            f"{self.merchant_url}/sign/cart",
            json={"cart_mandate": cart_mandate},
            timeout=10.0
        )
        response.raise_for_status()
        result = response.json()

        # 手動署名モード：Merchantの承認を待機
        if result.get("status") == "pending_merchant_signature":
            cart_mandate_id = result.get("cart_mandate_id")
            logger.info(f"[_create_cart_from_products] '{cart_name}' pending manual approval: {cart_mandate_id}")
            logger.info(f"[_create_cart_from_products] Waiting for merchant signature for '{cart_name}' (max 300s)...")

            # Merchantの承認を待機（ポーリング）
            signed_cart_mandate = await self._wait_for_merchant_signature(
                cart_mandate_id,
                cart_name=cart_name,
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

        logger.info(f"[_create_cart_from_products] CartMandate signed: {cart_mandate['id']}")

        # Artifact形式でラップ
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
```

### Merchant署名待機（ポーリング）（Line 935-1015）
```python
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

    # タイムアウト
    logger.error(f"[MerchantAgent] Timeout waiting for merchant signature for {cart_label}")
    return None
```

### Merchant側：CartMandate署名（Line 105-199）
**ファイル**: `merchant/service.py`

```python
@self.app.post("/sign/cart")
async def sign_cart_mandate(sign_request: Dict[str, Any]):
    """
    POST /sign/cart - CartMandateに署名

    自動署名モード：即座に署名
    手動署名モード：pending_merchant_signatureステータスで保存し、要承認
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
```

### Merchant署名生成（Line 753-768）
```python
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
```

### Merchant Authorization JWT生成（Line 647-751）
```python
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
        "iss": "did:ap2:merchant:xxx",
        "sub": "did:ap2:merchant:xxx",
        "aud": "did:ap2:agent:payment_processor",
        "iat": <timestamp>,
        "exp": <timestamp + 900>,  // 15分後
        "jti": <unique_id>,
        "cart_hash": "<cart_contents_hash>"
      }
    - Signature: ECDSA署名（merchantの秘密鍵）
    """
    import base64
    import hashlib
    import time

    now = datetime.now(timezone.utc)

    # 1. Cart Contentsのハッシュ計算（RFC 8785準拠）
    from v2.common.user_authorization import compute_mandate_hash
    cart_hash = compute_mandate_hash(cart_mandate)

    # 2. JWTのHeader
    header = {
        "alg": "ES256",
        "kid": f"{merchant_id}#key-1",
        "typ": "JWT"
    }

    # 3. JWTのPayload
    payload = {
        "iss": merchant_id,
        "sub": merchant_id,
        "aud": "did:ap2:agent:payment_processor",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 900,  # 15分後
        "jti": str(uuid.uuid4()),
        "cart_hash": cart_hash
    }

    # 4. Base64url エンコード
    def base64url_encode(data):
        json_str = json.dumps(data, separators=(',', ':'))
        return base64.urlsafe_b64encode(json_str.encode('utf-8')).rstrip(b'=').decode('utf-8')

    header_b64 = base64url_encode(header)
    payload_b64 = base64url_encode(payload)

    # 5. 署名生成（ES256: ECDSA with P-256 and SHA-256）
    key_id = self.agent_id.split(":")[-1]
    private_key = self.key_manager.get_private_key(key_id)

    message_to_sign = f"{header_b64}.{payload_b64}".encode('utf-8')

    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec

    signature_bytes = private_key.sign(
        message_to_sign,
        ec.ECDSA(hashes.SHA256())
    )

    signature_b64 = base64.urlsafe_b64encode(signature_bytes).rstrip(b'=').decode('utf-8')

    # 6. JWT組み立て
    jwt_token = f"{header_b64}.{payload_b64}.{signature_b64}"

    return jwt_token
```

### データ構造（CartMandate - 署名済み）
```python
{
    "id": "cart_abc12345",
    "type": "CartMandate",
    "version": "0.2",
    "intent_mandate_id": "intent_xyz789",
    "items": [
        {
            "id": "item_abc123",
            "name": "むぎぼーカレンダー",
            "description": "2025年版カレンダー",
            "quantity": 1,
            "unit_price": {"value": "2000.00", "currency": "JPY"},
            "total_price": {"value": "2000.00", "currency": "JPY"},
            "image_url": "https://...",
            "sku": "CAL-2025-MUGIBO",
            "category": "calendar",
            "brand": "むぎぼー"
        }
    ],
    "subtotal": {"value": "2000.00", "currency": "JPY"},
    "tax": {"value": "200.00", "currency": "JPY"},
    "shipping": {
        "address": {
            "recipient": "山田太郎",
            "postal_code": "150-0001",
            "address_line1": "東京都渋谷区神宮前1-1-1",
            "address_line2": "サンプルマンション101",
            "country": "JP"
        },
        "method": "standard",
        "cost": {"value": "500.00", "currency": "JPY"},
        "estimated_delivery": "2025-10-23T14:00:00Z"
    },
    "total": {"value": "2700.00", "currency": "JPY"},
    "merchant_id": "did:ap2:merchant:mugibo_merchant",
    "merchant_name": "むぎぼーショップ",
    "created_at": "2025-10-20T14:00:00Z",
    "expires_at": "2025-10-20T14:30:00Z",
    "merchant_signature": {
        "signature": "base64_encoded_ecdsa_signature",
        "algorithm": "ECDSA",
        "key_id": "merchant",
        "timestamp": "2025-10-20T14:00:01Z"
    },
    "merchant_authorization": "eyJhbGciOiJFUzI1NiIsImtpZCI6ImRpZDphcDI6bWVyY2hhbnQ6bXVnaWJvX21lcmNoYW50I2tleS0xIiwidHlwIjoiSldUIn0.eyJpc3MiOiJkaWQ6YXAyOm1lcmNoYW50Om11Z2lib19tZXJjaGFudCIsInN1YiI6ImRpZDphcDI6bWVyY2hhbnQ6bXVnaWJvX21lcmNoYW50IiwiYXVkIjoiZGlkOmFwMjphZ2VudDpwYXltZW50X3Byb2Nlc3NvciIsImlhdCI6MTcyOTQzNTIwMSwiZXhwIjoxNzI5NDM2MTAxLCJqdGkiOiJhYmMxMjMiLCJjYXJ0X2hhc2giOiI4ZjQzMmEuLi4ifQ.signature_bytes_base64url",
    "cart_metadata": {
        "name": "人気商品セット",
        "description": "検索結果で人気の商品を組み合わせたカートです"
    }
}
```

### 署名処理
- **署名方式**: ECDSA (secp256r1 / P-256)
- **署名場所**: Merchant Service（バックエンド）
- **署名対象**: CartMandate全体（merchant_signature, merchant_authorization除く）
- **JWT署名**: ES256 (ECDSA with SHA-256)
- **merchant_authorization**: RFC 8785準拠のcart_hashを含む

### 通信方式
- **Merchant Agent → Merchant**: HTTP POST
- **エンドポイント**: `http://merchant:8002/sign/cart`
- **レスポンス待機**: ポーリング（2秒間隔、最大300秒）
- **ステータス確認**: `GET http://merchant:8002/cart-mandates/{cart_mandate_id}`

---

## まとめ

### 全体フロー図
```
User → Shopping Agent: Intent入力
  ↓
Shopping Agent: IntentMandate作成（未署名）
  ↓
User: Passkey署名（WebAuthn）
  ↓
Shopping Agent: 配送先入力フォーム送信
  ↓
User: 配送先入力
  ↓
Shopping Agent → Merchant Agent: IntentMandate + 配送先送信（A2A）
  ↓
Merchant Agent: 商品検索・カート候補並列生成
  ↓
Merchant Agent → Merchant: CartMandate署名依頼（HTTP）×3並列
  ↓
Merchant: CartMandate検証・署名・JWT生成
  ↓
Merchant Agent: 署名待機（ポーリング）
  ↓
Merchant Agent → Shopping Agent: 署名済みカート候補返却（Artifact形式）
  ↓
Shopping Agent → User: カート候補カルーセル表示
```

### 重要な実装パターン

1. **Passkey署名の分離**
   - IntentMandateはフロントエンドでPasskey署名
   - サーバー署名は使用しない（専門家の指摘対応）

2. **配送先の早期確定**
   - AP2仕様準拠：CartMandate作成「前」に配送先を確定
   - 理由：配送料計算に必要（カート合計金額に影響）

3. **カート候補の並列生成**
   - `asyncio.gather`で複数のカートを同時生成
   - UX改善：手動署名モードでは3つの署名依頼が同時表示

4. **Merchant署名の待機**
   - ポーリング方式（2秒間隔、最大300秒）
   - ステータス: `pending_merchant_signature` → `signed` or `rejected`

5. **A2A通信の署名**
   - Shopping Agent → Merchant Agent: ECDSA署名付きA2Aメッセージ
   - メッセージ全体に署名（header + dataPart）

6. **Merchant Authorization JWT**
   - ES256署名（ECDSA with SHA-256）
   - RFC 8785準拠のcart_hashを含む
   - 有効期限15分（AP2仕様推奨）

### データベース永続化
- IntentMandate: `MandateCRUD.create(type="Intent", status="signed")`
- CartMandate: `MandateCRUD.create(type="Cart", status="signed")`
- セッション: `AgentSessionCRUD.create/update`

### セキュリティ対策
- **Challenge-Response**: WebAuthn challengeでリプレイ攻撃防止
- **トークン有効期限**: IntentMandate 1時間、CartMandate 30分
- **署名検証**: 各Mandateの署名を検証
- **在庫確認**: Merchant側でCartMandate署名前に在庫確認

---

## 参考ファイル一覧

| ファイルパス | 主要機能 |
|------------|---------|
| `/Users/kagadminmac/project/ap2/v2/services/shopping_agent/agent.py` | Shopping Agent全体（Intent入力、署名、A2A通信） |
| `/Users/kagadminmac/project/ap2/v2/services/merchant_agent/agent.py` | Merchant Agent（商品検索、カート候補生成、署名依頼） |
| `/Users/kagadminmac/project/ap2/v2/services/merchant/service.py` | Merchant Service（CartMandate署名、JWT生成） |
| `/Users/kagadminmac/project/ap2/v2/services/credential_provider/provider.py` | Credential Provider（支払い方法管理） |
| `/Users/kagadminmac/project/ap2/v2/common/base_agent.py` | BaseAgent（A2Aハンドラー、鍵管理） |
| `/Users/kagadminmac/project/ap2/v2/common/models.py` | データモデル（A2AMessage、StreamEvent等） |
| `/Users/kagadminmac/project/ap2/v2/common/database.py` | データベースCRUD（Mandate、Session、Transaction） |
| `/Users/kagadminmac/project/ap2/v2/common/crypto.py` | 暗号処理（ECDSA署名、鍵管理） |

---

**作成日**: 2025-10-20
**調査範囲**: AP2 Step 1-10
**AP2仕様バージョン**: 0.2
