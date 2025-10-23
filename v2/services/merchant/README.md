# Merchant

**AP2 Protocol - 実店舗エンティティ**

Merchantは、実際の商店（むぎぼーショップ）を表すエンティティです。Cart Mandateに署名し、在庫管理、注文承認を行います。**Merchant AgentとMerchantは別エンティティ**であり、Merchantのみが署名権限を持ちます。

## 📋 目次

- [概要](#概要)
- [役割と責務](#役割と責務)
- [主要機能](#主要機能)
- [エンドポイント一覧](#エンドポイント一覧)
- [実装詳細](#実装詳細)
- [セキュリティ](#セキュリティ)
- [署名モード](#署名モード)
- [開発者向け情報](#開発者向け情報)

---

## 概要

### AP2での役割

- **AP2 Role**: `merchant`
- **DID**: `did:ap2:merchant` (注意: `did:ap2:agent:...` ではない)
- **Port**: `8002`
- **Database**: `v2/data/merchant.db`
- **店舗名**: むぎぼーショップ

### 主要な責務

1. **Cart Mandate署名**: ECDSA署名による承認
2. **在庫確認**: Cart作成前の在庫チェック
3. **注文承認**: 自動署名 or 手動承認
4. **Merchant Authorization JWT発行**: AP2仕様準拠のJWT
5. **署名鍵管理**: Merchantのみが秘密鍵を保持

---

## 役割と責務

### 1. エンティティ分離の重要性

**AP2仕様の要件**: MerchantとMerchant Agentは**別エンティティ**である必要があります。

```
┌──────────────┐      ┌──────────┐
│ Merchant     │ A2A  │ Merchant │
│ Agent        │─────>│          │
│              │      │ (署名)   │
│ (仲介)       │      │ (店舗側) │
│ 署名権限なし  │      │ 署名権限あり │
└──────────────┘      └──────────┘
```

**理由**:
- **セキュリティ**: 署名鍵をAgentから分離
- **責任分離**: 自動処理（Agent）と承認（Merchant）を明確化
- **監査**: Merchantによる明示的な承認プロセスが記録される
- **AP2準拠**: 仕様で要求される6エンティティアーキテクチャ

### 2. Cart Mandate署名の責務

Merchantは、以下の検証を行った後にCart Mandateに署名します：

1. **merchant_id検証**: 自店舗のCartか確認
2. **在庫確認**: 全商品の在庫が十分か確認
3. **価格検証**: 商品価格がデータベースと一致するか確認
4. **ECDSA署名**: Cart Mandateに署名
5. **Merchant Authorization JWT発行**: AP2仕様準拠のJWT生成

---

## 主要機能

### 1. Cart Mandate署名

**エンドポイント**: `POST /sign/cart`

**リクエスト**:

```json
{
  "cart_mandate": {
    "type": "CartMandate",
    "contents": {
      "id": "cart_abc123",
      "merchant_id": "did:ap2:merchant:mugibo_merchant",
      "items": [
        {
          "product_id": "prod_mugibo_calendar_001",
          "sku": "MUGIBO-CAL-2025",
          "name": "むぎぼーカレンダー2025",
          "quantity": 1,
          "unit_price": {"value": "1980", "currency": "JPY"},
          "total_price": {"value": "1980", "currency": "JPY"}
        }
      ],
      "subtotal": {"value": "1980", "currency": "JPY"},
      "shipping_cost": {"value": "500", "currency": "JPY"},
      "tax": {"value": "198", "currency": "JPY"},
      "total": {"value": "2678", "currency": "JPY"},
      "shipping_address": { /* ... */ }
    }
  }
}
```

**レスポンス（自動署名モード）**:

```json
{
  "signed_cart_mandate": {
    "type": "CartMandate",
    "contents": { /* ... */ },
    "merchant_signature": {
      "algorithm": "ECDSA",
      "value": "MEUCIQDx8yZ...",
      "public_key": "LS0tLS1CRU...",
      "signed_at": "2025-10-23T12:35:00Z",
      "key_id": "merchant"
    },
    "merchant_authorization": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9..."
  },
  "merchant_signature": { /* 上記と同じ */ },
  "merchant_authorization": "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**実装**: `service.py:106-196`

### 2. 署名プロセス詳細

```python
# service.py:106-196
@self.app.post("/sign/cart")
async def sign_cart_mandate(sign_request: Dict[str, Any]):
    cart_mandate = sign_request["cart_mandate"]

    # ===== Step 1: バリデーション =====
    self._validate_cart_mandate(cart_mandate)
    # - merchant_idが自店舗か確認
    # - 必須フィールドの存在確認
    # - 価格計算の妥当性確認

    # ===== Step 2: 在庫確認 =====
    await self._check_inventory(cart_mandate)
    # - 各商品の在庫が十分か確認
    # - 在庫不足の場合はHTTPException(400)

    # ===== Step 3: 署名 =====
    cart_id = cart_mandate["contents"]["id"]

    if self.auto_sign_mode:
        # 自動署名モード
        signature = await self._sign_cart_mandate(cart_mandate)
        signed_cart_mandate = cart_mandate.copy()
        signed_cart_mandate["merchant_signature"] = signature.model_dump()

        # ===== Step 4: Merchant Authorization JWT生成 =====
        merchant_authorization_jwt = self._generate_merchant_authorization_jwt(
            cart_mandate,
            self.merchant_id
        )
        signed_cart_mandate["merchant_authorization"] = merchant_authorization_jwt

        # データベースに保存
        async with self.db_manager.get_session() as db_session:
            existing_mandate = await MandateCRUD.get_by_id(db_session, cart_id)

            if existing_mandate:
                await MandateCRUD.update_status(
                    db_session,
                    cart_id,
                    "signed",
                    signed_cart_mandate
                )
            else:
                await MandateCRUD.create(db_session, {
                    "id": cart_id,
                    "type": "Cart",
                    "status": "signed",
                    "payload": signed_cart_mandate,
                    "issuer": self.agent_id
                })

        return {
            "signed_cart_mandate": signed_cart_mandate,
            "merchant_signature": signed_cart_mandate["merchant_signature"],
            "merchant_authorization": merchant_authorization_jwt
        }
    else:
        # 手動署名モード: 承認待ちとして保存
        # ... (実装は service.py:198-224 参照)
```

### 3. Merchant Authorization JWT

**AP2仕様準拠**: Cart Mandateには`merchant_authorization`フィールドが必要です。

**JWT構造**:

```json
{
  "header": {
    "alg": "ES256",
    "typ": "JWT",
    "kid": "did:ap2:merchant#key-1"
  },
  "payload": {
    "iss": "did:ap2:merchant:mugibo_merchant",
    "sub": "cart_abc123",
    "iat": 1729680000,
    "exp": 1729683600,
    "cart_hash": "sha256ハッシュ（RFC 8785正規化）",
    "merchant_name": "むぎぼーショップ",
    "total_amount": {
      "value": "2678",
      "currency": "JPY"
    }
  },
  "signature": "ECDSA署名"
}
```

**実装**: `service.py` の `_generate_merchant_authorization_jwt()` メソッド

```python
# service.py:300-350
def _generate_merchant_authorization_jwt(
    self,
    cart_mandate: Dict[str, Any],
    merchant_id: str
) -> str:
    """
    Merchant Authorization JWTを生成

    AP2仕様準拠:
    - JWT形式（ES256アルゴリズム）
    - cart_hash: RFC 8785正規化されたCartのSHA-256ハッシュ
    - 有効期限: 1時間
    """
    from v2.common.crypto import compute_mandate_hash
    from v2.common.jwt_utils import MerchantAuthorizationJWT

    # Cart Mandateのハッシュを計算
    cart_hash = compute_mandate_hash(cart_mandate, hash_format='hex')

    # JWTペイロード
    jwt_payload = {
        "iss": merchant_id,
        "sub": cart_mandate["contents"]["id"],
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        "cart_hash": cart_hash,
        "merchant_name": self.merchant_name,
        "total_amount": cart_mandate["contents"]["total"]
    }

    # ECDSA署名でJWT生成
    jwt_token = MerchantAuthorizationJWT.generate(
        jwt_payload,
        self.key_manager,
        key_id="merchant"
    )

    return jwt_token
```

### 4. 在庫管理

**エンドポイント**:
- `GET /inventory/{sku}`: 特定商品の在庫照会
- `POST /inventory/{sku}`: 在庫更新

**在庫確認ロジック**:

```python
# service.py:250-290
async def _check_inventory(self, cart_mandate: Dict[str, Any]):
    """
    Cart Mandateの在庫を確認

    Raises:
        HTTPException(400): 在庫不足の場合
    """
    items = cart_mandate["contents"]["items"]

    async with self.db_manager.get_session() as session:
        for item in items:
            product_id = item["product_id"]
            quantity = item["quantity"]

            # データベースから商品を取得
            product = await ProductCRUD.get_by_id(session, product_id)

            if not product:
                raise HTTPException(
                    status_code=400,
                    detail=f"Product not found: {product_id}"
                )

            if product.inventory_count < quantity:
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient inventory for {product.name}: "
                           f"requested={quantity}, available={product.inventory_count}"
                )
```

---

## エンドポイント一覧

### Cart Mandate署名

| エンドポイント | メソッド | 説明 | 実装 |
|--------------|---------|------|------|
| `/sign/cart` | POST | Cart Mandateに署名 | `service.py:106` |
| `/sign/approve/{cart_id}` | POST | 手動承認（手動モード） | `service.py:226` |
| `/sign/reject/{cart_id}` | POST | 手動拒否（手動モード） | `service.py:250` |

### 在庫管理

| エンドポイント | メソッド | 説明 | 実装 |
|--------------|---------|------|------|
| `/inventory/{sku}` | GET | 在庫照会 | `service.py:274` |
| `/inventory/{sku}` | POST | 在庫更新 | `service.py:290` |

### 設定

| エンドポイント | メソッド | 説明 | 実装 |
|--------------|---------|------|------|
| `/settings/auto-sign` | GET | 署名モード取得 | `service.py:320` |
| `/settings/auto-sign` | POST | 署名モード設定 | `service.py:330` |

### A2A通信

| エンドポイント | メソッド | 説明 | 実装 |
|--------------|---------|------|------|
| `/a2a/message` | POST | A2Aメッセージ受信 | `base_agent.py:185` |
| `/.well-known/agent-card.json` | GET | AgentCard取得 | `base_agent.py:268` |

### ヘルスチェック

| エンドポイント | メソッド | 説明 | 実装 |
|--------------|---------|------|------|
| `/` | GET | ヘルスチェック | `base_agent.py:175` |
| `/health` | GET | Docker向けヘルスチェック | `base_agent.py:263` |

---

## 実装詳細

### クラス構造

```python
# service.py:32-82
class MerchantService(BaseAgent):
    """
    Merchant Service実装

    継承元: BaseAgent (v2/common/base_agent.py)
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:merchant",  # Agentではない！
            agent_name="Merchant",
            passphrase=AgentPassphraseManager.get_passphrase("merchant"),
            keys_directory="./keys"
        )

        # データベースマネージャー
        self.db_manager = DatabaseManager(
            database_url=os.getenv("DATABASE_URL")
        )

        # このMerchantの情報
        self.merchant_id = "did:ap2:merchant:mugibo_merchant"
        self.merchant_name = "むぎぼーショップ"

        # 署名モード設定（メモリ内管理、本番環境ではDBに保存）
        self.auto_sign_mode = True  # デフォルトは自動署名
```

### A2Aメッセージハンドラー

```python
# service.py:92-99
def register_a2a_handlers(self):
    """
    Merchantが受信するA2Aメッセージ
    """
    self.a2a_handler.register_handler(
        "ap2.mandates.CartMandate",
        self.handle_cart_mandate_sign_request
    )
```

### バリデーションロジック

```python
# service.py の _validate_cart_mandate() メソッド
def _validate_cart_mandate(self, cart_mandate: Dict[str, Any]):
    """
    Cart Mandateの妥当性を検証

    検証項目:
    1. merchant_idが自店舗か
    2. 必須フィールドの存在
    3. 価格計算の妥当性
    """
    contents = cart_mandate.get("contents", {})

    # 1. merchant_id検証
    merchant_id = contents.get("merchant_id")
    if merchant_id != self.merchant_id:
        raise HTTPException(
            status_code=400,
            detail=f"merchant_id mismatch: expected={self.merchant_id}, got={merchant_id}"
        )

    # 2. 必須フィールド検証
    required_fields = ["id", "items", "total", "shipping_address"]
    for field in required_fields:
        if field not in contents:
            raise HTTPException(
                status_code=400,
                detail=f"Missing required field: {field}"
            )

    # 3. 価格計算検証（簡易版）
    items = contents["items"]
    calculated_subtotal = sum(
        int(item["total_price"]["value"])
        for item in items
    )

    stated_subtotal = int(contents["subtotal"]["value"])

    if calculated_subtotal != stated_subtotal:
        raise HTTPException(
            status_code=400,
            detail=f"Subtotal mismatch: calculated={calculated_subtotal}, stated={stated_subtotal}"
        )
```

---

## セキュリティ

### 1. 署名鍵管理

**Merchantのみが署名鍵を保持**:

```
v2/keys/
├── merchant_private.pem         # ECDSA秘密鍵（AES-256暗号化）
├── merchant_public.pem          # ECDSA公開鍵
├── merchant_ed25519_private.pem # Ed25519秘密鍵（A2A通信用）
└── merchant_ed25519_public.pem  # Ed25519公開鍵
```

**鍵の用途**:
- **ECDSA（P-256）**: Cart Mandate署名、JWT署名
- **Ed25519**: A2Aメッセージ署名

### 2. ECDSA署名プロセス

```python
# service.py の _sign_cart_mandate() メソッド
async def _sign_cart_mandate(self, cart_mandate: Dict[str, Any]) -> Signature:
    """
    Cart MandateにECDSA署名

    署名対象:
    - cart_mandate全体（merchant_signature、merchant_authorizationを除く）
    - RFC 8785正規化されたJSON
    """
    # SignatureManagerを使用（v2/common/crypto.py）
    signature = self.signature_manager.sign_mandate(
        cart_mandate,
        key_id="merchant"  # ECDSA鍵を使用
    )

    logger.info(
        f"[Merchant] Signed Cart Mandate: cart_id={cart_mandate['contents']['id']}, "
        f"algorithm={signature.algorithm}"
    )

    return signature
```

### 3. JWT署名

**Merchant Authorization JWTの署名**:

```python
# v2/common/jwt_utils.py の MerchantAuthorizationJWT クラス
class MerchantAuthorizationJWT:
    @staticmethod
    def generate(
        payload: Dict[str, Any],
        key_manager: KeyManager,
        key_id: str
    ) -> str:
        """
        ES256アルゴリズムでJWT生成

        1. ヘッダー作成（alg=ES256, kid=...）
        2. ペイロードをJSON正規化
        3. ECDSA署名
        4. JWT形式にエンコード
        """
        # ECDSA秘密鍵を取得
        private_key = key_manager.get_private_key(key_id, algorithm="ECDSA")

        # JWTヘッダー
        header = {
            "alg": "ES256",
            "typ": "JWT",
            "kid": f"did:ap2:merchant#key-1"
        }

        # ペイロードとヘッダーをBase64URL エンコード
        header_b64 = base64url_encode(json.dumps(header))
        payload_b64 = base64url_encode(json.dumps(payload))

        # 署名対象データ
        signing_input = f"{header_b64}.{payload_b64}"

        # ECDSA署名
        signature_bytes = private_key.sign(
            signing_input.encode('utf-8'),
            ec.ECDSA(hashes.SHA256())
        )

        # Base64URL エンコード
        signature_b64 = base64url_encode(signature_bytes)

        # JWT形式
        jwt_token = f"{signing_input}.{signature_b64}"

        return jwt_token
```

---

## 署名モード

### 1. 自動署名モード（デフォルト）

**特徴**:
- Cart Mandate受信後、即座に署名
- 人間の介入なし
- デモ環境・開発環境向け

**設定**:

```python
self.auto_sign_mode = True  # デフォルト
```

### 2. 手動署名モード

**特徴**:
- Cart Mandateを承認待ちとして保存
- Merchant Dashboard（Frontend）で手動承認
- 本番環境向け

**設定**:

```bash
# 環境変数で設定（将来実装予定）
export MERCHANT_AUTO_SIGN_MODE=false
```

**手動承認フロー**:

1. Cart Mandate受信
2. `pending_merchant_signature`ステータスでDB保存
3. Merchant DashboardでCart内容を確認
4. 承認: `POST /sign/approve/{cart_id}`
5. 拒否: `POST /sign/reject/{cart_id}`

---

## 開発者向け情報

### ローカル開発

```bash
# 仮想環境のアクティベート
source v2/.venv/bin/activate

# 依存関係インストール
cd v2
uv sync

# 環境変数設定
export AP2_MERCHANT_PASSPHRASE="your_passphrase"
export DATABASE_URL="sqlite+aiosqlite:///./data/merchant.db"

# サーバー起動
uvicorn services.merchant.main:app --host 0.0.0.0 --port 8002 --reload
```

### Docker開発

```bash
# Merchant単体でビルド＆起動
cd v2
docker compose up --build merchant

# ログ確認
docker compose logs -f merchant
```

### テスト

```bash
# ヘルスチェック
curl http://localhost:8002/

# Cart Mandate署名（A2A通信経由）
curl -X POST http://localhost:8002/a2a/message \
  -H "Content-Type: application/json" \
  -d @sample_cart_mandate.json

# 在庫照会
curl http://localhost:8002/inventory/MUGIBO-CAL-2025
```

### 環境変数

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `AP2_MERCHANT_PASSPHRASE` | 秘密鍵のパスフレーズ | *必須* |
| `DATABASE_URL` | データベースURL | `sqlite+aiosqlite:///...` |
| `MERCHANT_AUTO_SIGN_MODE` | 自動署名モード | `true` |
| `LOG_LEVEL` | ログレベル | `INFO` |

### 主要ファイル

| ファイル | 行数 | 説明 |
|---------|------|------|
| `service.py` | ~600 | MerchantServiceクラス実装 |
| `main.py` | ~30 | FastAPIエントリーポイント |
| `Dockerfile` | ~40 | Dockerイメージ定義 |

---

## 関連ドキュメント

- [メインREADME](../../../README.md) - プロジェクト全体の概要
- [Merchant Agent README](../merchant_agent/README.md) - Merchant Agentとの違い
- [Shopping Agent README](../shopping_agent/README.md)
- [Payment Processor README](../payment_processor/README.md)
- [AP2仕様書](https://ap2-protocol.org/specification/)

---

**作成日**: 2025-10-23
**バージョン**: v2.0.0
**メンテナー**: AP2 Development Team
