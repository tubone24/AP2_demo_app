# Payment Network

**AP2 Protocol - 決済ネットワークスタブサービス**

Payment Networkは、実際の決済ネットワーク（Visa、Mastercard等）のスタブとして動作し、Agent Tokenの発行とトークン検証を行います。

## 📋 目次

- [概要](#概要)
- [役割と責務](#役割と責務)
- [主要機能](#主要機能)
- [エンドポイント一覧](#エンドポイント一覧)
- [Agent Token管理](#agent-token管理)
- [セキュリティ](#セキュリティ)
- [開発者向け情報](#開発者向け情報)

---

## 概要

### AP2での役割

- **AP2 Role**: `payment-network`
- **Port**: `8005`
- **Network Name**: `DemoPaymentNetwork`（本番環境では Visa、Mastercard等）

### 主要な責務

1. **Agent Token発行**: Credential Providerからのトークン化呼び出しを受付（AP2 Step 23）
2. **トークン検証**: Agent Tokenの有効性を検証
3. **ネットワーク情報提供**: サポートする支払い方法、機能の情報提供

---

## 役割と責務

### 1. AP2仕様におけるPayment Network

**AP2 Step 23**: Credential Provider → Payment Network のトークン化呼び出し

```
┌───────────────────┐      ┌─────────────────┐
│ Credential        │      │ Payment         │
│ Provider          │ Step │ Network         │
│                   │  23  │                 │
│ - WebAuthn検証    │─────>│ - Agent Token   │
│ - Payment Method  │      │   発行          │
│   トークン管理     │      │ - トークン検証   │
└───────────────────┘      └─────────────────┘
```

**Agent Token vs Payment Method Token**:

| トークン | 発行者 | 用途 | 有効期限 |
|---------|-------|------|---------|
| **Payment Method Token** | Credential Provider | 支払い方法の一時的な参照 | 15分 |
| **Agent Token** | Payment Network | 決済ネットワークが発行したトークン | 1時間 |

### 2. スタブ実装の範囲

このサービスは**デモ環境用のスタブ**です。実際の本番環境では、以下のような実装が必要です：

**本番環境での実装例**:
- **Visa Token Service**: Visa決済ネットワークとの統合
- **Mastercard Digital Enablement Service (MDES)**: Mastercard決済ネットワークとの統合
- **PCI DSS準拠**: カード情報の暗号化、トークン化
- **3D Secure**: 追加認証プロトコル
- **不正検知**: ネットワークレベルの不正検知システム

---

## 主要機能

### 1. Agent Token発行 (network.py:122-213)

**エンドポイント**: `POST /network/tokenize`

**AP2 Step 23実装**: Credential Providerからのトークン化呼び出しを受付

**リクエスト**:

```json
{
  "payment_mandate": {
    "id": "pm_001",
    "payer_id": "user_demo_001",
    "amount": {
      "value": "8068.00",
      "currency": "JPY"
    }
  },
  "attestation": {
    "challenge": "...",
    "clientDataJSON": "...",
    "authenticatorData": "...",
    "signature": "..."
  },
  "payment_method_token": "tok_a1b2c3d4_x9y8z7w6",
  "transaction_context": {
    "credential_provider_id": "did:ap2:agent:credential_provider",
    "timestamp": "2025-10-23T12:00:00Z"
  }
}
```

**レスポンス**:

```json
{
  "agent_token": "agent_tok_demopaymentnetwork_a1b2c3d4_x9y8z7w6v5u4t3s2r1q0",
  "expires_at": "2025-10-23T13:00:00Z",
  "network_name": "DemoPaymentNetwork",
  "token_type": "agent_token"
}
```

**処理フロー**:

```python
# network.py:122-213
@self.app.post("/network/tokenize", response_model=TokenizeResponse)
async def tokenize_payment(request: TokenizeRequest):
    """
    Agent Token発行（AP2 Step 23）

    1. PaymentMandate検証
    2. 支払い方法トークン検証
    3. Agent Token生成（暗号学的に安全）
    4. トークンストアに保存
    5. Agent Tokenを返却
    """
    payment_mandate = request.payment_mandate
    payment_method_token = request.payment_method_token

    # PaymentMandate検証（スタブ実装）
    if not payment_mandate.get("id"):
        raise HTTPException(status_code=400, detail="Missing payment_mandate.id")

    # 支払い方法トークン検証（スタブ実装）
    if not payment_method_token.startswith("tok_"):
        raise HTTPException(status_code=400, detail="Invalid payment_method_token format")

    # Agent Token生成（暗号学的に安全）
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=1)  # 1時間有効

    # secrets.token_urlsafe()を使用（cryptographically strong random）
    random_bytes = secrets.token_urlsafe(32)  # 32バイト = 256ビット
    agent_token = f"agent_tok_{self.network_name.lower()}_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"

    # トークンストアに保存
    self.agent_token_store[agent_token] = {
        "payment_mandate_id": payment_mandate.get("id"),
        "payment_method_token": payment_method_token,
        "payer_id": payment_mandate.get("payer_id"),
        "amount": payment_mandate.get("amount"),
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "network_name": self.network_name,
        "attestation_verified": request.attestation is not None
    }

    return TokenizeResponse(
        agent_token=agent_token,
        expires_at=expires_at.isoformat().replace('+00:00', 'Z'),
        network_name=self.network_name,
        token_type="agent_token"
    )
```

### 2. Agent Token検証 (network.py:214-284)

**エンドポイント**: `POST /network/verify-token`

**リクエスト**:

```json
{
  "agent_token": "agent_tok_demopaymentnetwork_a1b2c3d4_x9y8z7w6v5u4t3s2r1q0"
}
```

**レスポンス（成功）**:

```json
{
  "valid": true,
  "token_info": {
    "payment_mandate_id": "pm_001",
    "payer_id": "user_demo_001",
    "amount": {
      "value": "8068.00",
      "currency": "JPY"
    },
    "network_name": "DemoPaymentNetwork",
    "issued_at": "2025-10-23T12:00:00Z",
    "expires_at": "2025-10-23T13:00:00Z"
  }
}
```

**レスポンス（失敗）**:

```json
{
  "valid": false,
  "error": "Agent Token not found"
}
```

または

```json
{
  "valid": false,
  "error": "Agent Token expired"
}
```

**処理フロー**:

```python
# network.py:214-284
@self.app.post("/network/verify-token", response_model=VerifyTokenResponse)
async def verify_token(request: VerifyTokenRequest):
    """
    Agent Token検証

    1. Agent Tokenをトークンストアから取得
    2. 有効期限を確認
    3. トークン情報を返却
    """
    agent_token = request.agent_token

    # トークンストアから取得
    token_data = self.agent_token_store.get(agent_token)
    if not token_data:
        return VerifyTokenResponse(valid=False, error="Agent Token not found")

    # 有効期限確認
    expires_at = datetime.fromisoformat(token_data["expires_at"])
    if datetime.now(timezone.utc) > expires_at:
        # 期限切れトークンを削除
        del self.agent_token_store[agent_token]
        return VerifyTokenResponse(valid=False, error="Agent Token expired")

    return VerifyTokenResponse(
        valid=True,
        token_info={
            "payment_mandate_id": token_data.get("payment_mandate_id"),
            "payer_id": token_data.get("payer_id"),
            "amount": token_data.get("amount"),
            "network_name": token_data.get("network_name"),
            "issued_at": token_data.get("issued_at"),
            "expires_at": token_data.get("expires_at")
        }
    )
```

### 3. ネットワーク情報取得 (network.py:286-305)

**エンドポイント**: `GET /network/info`

**レスポンス**:

```json
{
  "network_name": "DemoPaymentNetwork",
  "supported_payment_methods": ["card", "digital_wallet"],
  "tokenization_enabled": true,
  "agent_transactions_supported": true,
  "timestamp": "2025-10-23T12:00:00Z"
}
```

---

## エンドポイント一覧

### トークン化

| Method | Path | 説明 | AP2 Step |
|--------|------|------|----------|
| POST | `/network/tokenize` | Agent Token発行 | 23 |
| POST | `/network/verify-token` | Agent Token検証 | N/A |

### 情報取得

| Method | Path | 説明 |
|--------|------|------|
| GET | `/network/info` | ネットワーク情報取得 |
| GET | `/health` | ヘルスチェック |

---

## Agent Token管理

### トークンストア構造

```python
# network.py:101
self.agent_token_store: Dict[str, Dict[str, Any]] = {}

# 例:
# {
#   "agent_tok_demopaymentnetwork_a1b2c3d4_x9y8z7w6": {
#     "payment_mandate_id": "pm_001",
#     "payment_method_token": "tok_a1b2c3d4_x9y8z7w6",
#     "payer_id": "user_demo_001",
#     "amount": {"value": "8068.00", "currency": "JPY"},
#     "issued_at": "2025-10-23T12:00:00Z",
#     "expires_at": "2025-10-23T13:00:00Z",
#     "network_name": "DemoPaymentNetwork",
#     "attestation_verified": true
#   }
# }
```

**トークンストアの注意点**:
- **デモ環境**: インメモリストア（再起動で消失）
- **本番環境**: Redis、DynamoDB等の永続化KVストアを使用
- **有効期限**: 1時間（デフォルト）
- **自動削除**: 検証時に期限切れトークンを削除

---

## セキュリティ

### 1. 暗号学的に安全なトークン生成

```python
import secrets

# secrets.token_urlsafe()を使用（cryptographically strong random）
random_bytes = secrets.token_urlsafe(32)  # 32バイト = 256ビット
agent_token = f"agent_tok_{self.network_name.lower()}_{uuid.uuid4().hex[:8]}_{random_bytes[:24]}"
```

**`secrets` モジュールの重要性**:
- OS提供の暗号学的に安全な乱数生成器を使用
- `random` モジュールより安全（予測不可能）
- トークンの長さ: 約70文字（十分な エントロピー）

### 2. トークン有効期限

```python
expires_at = now + timedelta(hours=1)  # 1時間有効
```

**有効期限の理由**:
- トークン漏洩時の影響を最小化
- 長期間の再利用を防止
- 期限切れトークンは自動削除

### 3. トークン検証の3ステップ

1. **存在確認**: `token_store.get(agent_token)`
2. **有効期限確認**: `datetime.now(timezone.utc) > expires_at`
3. **トークン情報返却**: `token_info`

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
export PAYMENT_NETWORK_NAME="DemoPaymentNetwork"

# サーバー起動
uvicorn services.payment_network.main:app --host 0.0.0.0 --port 8005 --reload
```

### Docker開発

```bash
# Payment Network単体でビルド＆起動
cd v2
docker compose up --build payment_network

# ログ確認
docker compose logs -f payment_network
```

### テスト

```bash
# ヘルスチェック
curl http://localhost:8005/health

# ネットワーク情報取得
curl http://localhost:8005/network/info

# Agent Token発行
curl -X POST http://localhost:8005/network/tokenize \
  -H "Content-Type: application/json" \
  -d '{
    "payment_mandate": {
      "id": "pm_001",
      "payer_id": "user_demo_001",
      "amount": {"value": "8068.00", "currency": "JPY"}
    },
    "payment_method_token": "tok_test_12345",
    "transaction_context": {
      "credential_provider_id": "did:ap2:agent:credential_provider",
      "timestamp": "2025-10-23T12:00:00Z"
    }
  }'

# Agent Token検証
curl -X POST http://localhost:8005/network/verify-token \
  -H "Content-Type: application/json" \
  -d '{
    "agent_token": "agent_tok_demopaymentnetwork_..."
  }'
```

### 環境変数

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `PAYMENT_NETWORK_NAME` | ネットワーク名 | `DemoPaymentNetwork` |
| `LOG_LEVEL` | ログレベル | `INFO` |

### 主要ファイル

| ファイル | 行数 | 説明 |
|---------|------|------|
| `network.py` | ~306 | PaymentNetworkServiceクラス実装 |
| `main.py` | ~30 | FastAPIエントリーポイント |
| `Dockerfile` | ~30 | Dockerイメージ定義 |

---

## 本番環境への移行

このスタブサービスを本番環境に移行する場合、以下の実装が必要です：

### 1. 実際の決済ネットワーク統合

**Visa Token Service統合例**:

```python
import visa_token_service

class VisaPaymentNetwork(PaymentNetworkService):
    def __init__(self):
        super().__init__(network_name="Visa")
        self.visa_client = visa_token_service.Client(
            api_key=os.getenv("VISA_API_KEY"),
            environment="production"
        )

    async def tokenize_payment(self, request: TokenizeRequest):
        # Visa Token Service API呼び出し
        response = await self.visa_client.tokenize(
            pan=request.payment_method_token,
            expiry_date=...,
            cvv=...
        )
        return TokenizeResponse(
            agent_token=response.token,
            expires_at=response.expiry,
            network_name="Visa"
        )
```

### 2. PCI DSS準拠

- カード情報の暗号化
- トークン化（PANをトークンに変換）
- セキュアなキー管理（HSM使用）
- 監査ログの記録

### 3. 不正検知システム統合

- ネットワークレベルの不正検知
- ベロシティチェック（取引頻度監視）
- 地理的異常検知
- カード有効性確認

### 4. 3D Secure統合

- 3D Secure 2.0対応
- ステップアップ認証
- リスクベース認証

---

## AP2シーケンスとコード対応

| AP2 Step | 説明 | ファイル | 行番号 | メソッド |
|----------|------|----------|--------|----------|
| Step 23 | Agent Token発行 (CP → Payment Network) | network.py | 122-213 | `tokenize_payment()` |
| N/A | Agent Token検証 | network.py | 214-284 | `verify_token()` |

---

## 関連ドキュメント

- [メインREADME](../../../README.md) - プロジェクト全体の概要
- [Credential Provider README](../credential_provider/README.md) - Agent Token発行の呼び出し元
- [AP2仕様書](https://ap2-protocol.org/specification/)

---

**作成日**: 2025-10-23
**バージョン**: v2.0.0
**メンテナー**: AP2 Development Team
