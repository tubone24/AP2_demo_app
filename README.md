# AP2 (Agent Payments Protocol) デモアプリケーション v2

このアプリケーションは、[AP2プロトコル](https://ap2-protocol.org/)の完全なマイクロサービス実装です。AIエージェント間の安全な決済処理を、エンドツーエンドで体験できます。

![demo](./v2/docs/images/demo.gif)

## 目次

- [概要](#概要)
- [アーキテクチャ](#アーキテクチャ)
- [主要フロー](#主要フロー)
- [セットアップ](#セットアップ)
- [使い方](#使い方)
- [技術スタック](#技術スタック)
- [開発者向け情報](#開発者向け情報)

---

## 概要

### AP2とは？

**AP2 (Agent Payments Protocol)** は、AIエージェントが安全に決済を実行するためのオープンプロトコルです。Googleと60以上の組織によって開発され、以下の特徴があります：

- **エージェント間通信 (A2A)**: 署名付きメッセージによる安全な通信
- **3種類のMandate**: IntentMandate（購買意図）、CartMandate（カート）、PaymentMandate（決済）
- **WebAuthn/Passkey**: ハードウェアベースの認証
- **リスク評価**: 不正検知とリスクスコアリング
- **VDC (Verifiable Digital Credentials)**: 検証可能なデジタル資格情報

### v2アプリの特徴

このv2実装は、AP2仕様を100%準拠した実装で、以下を提供します：

✅ **6つのマイクロサービス**: Shopping Agent、Merchant Agent、Merchant、Credential Provider、Payment Processor、Frontend
✅ **完全なA2A通信**: ECDSA/Ed25519署名、Nonce検証、DID解決
✅ **WebAuthn/Passkey対応**: FIDO2準拠の署名検証
✅ **SSE/Streaming Chat**: リアルタイムな対話型UI
✅ **Docker Compose**: ワンコマンドで全サービス起動
✅ **統一ロギング**: JSON/テキスト形式、機密データマスキング

---

## アーキテクチャ

### システム構成図

```mermaid
graph TB
    subgraph "Frontend (Port 3000)"
        UI[Next.js UI<br/>Chat + Merchant Dashboard]
    end

    subgraph "Backend Services"
        SA[Shopping Agent<br/>Port 8000]
        MA[Merchant Agent<br/>Port 8001]
        M[Merchant<br/>Port 8002]
        CP[Credential Provider<br/>Port 8003]
        PP[Payment Processor<br/>Port 8004]
    end

    subgraph "Data Layer"
        DB1[(Shopping Agent DB<br/>SQLite)]
        DB2[(Merchant Agent DB<br/>SQLite)]
        DB3[(Credential Provider DB<br/>SQLite)]
        DB4[(Payment Processor DB<br/>SQLite)]
    end

    subgraph "Security"
        KEYS[Keys Storage<br/>ECDSA + Ed25519<br/>AES-256 Encrypted]
        DID[DID Documents<br/>JSON]
    end

    UI -->|SSE/Stream| SA
    UI -->|REST API| M

    SA -->|A2A Message| MA
    SA -->|A2A Message| CP
    SA -->|A2A Message| M
    MA -->|A2A Message| PP

    SA -.->|Read/Write| DB1
    MA -.->|Read/Write| DB2
    CP -.->|Read/Write| DB3
    PP -.->|Read/Write| DB4

    SA -.->|Load Keys| KEYS
    MA -.->|Load Keys| KEYS
    M -.->|Load Keys| KEYS
    CP -.->|Load Keys| KEYS
    PP -.->|Load Keys| KEYS

    SA -.->|Resolve DID| DID
    MA -.->|Resolve DID| DID

    style UI fill:#e1f5ff
    style SA fill:#fff4e6
    style MA fill:#fff4e6
    style M fill:#fff4e6
    style CP fill:#e8f5e9
    style PP fill:#e8f5e9
```

### マイクロサービス一覧

| サービス | ポート | 役割 | 主要エンドポイント |
|---------|--------|------|-------------------|
| **Frontend** | 3000 | ユーザーインターフェース | `/`, `/chat`, `/merchant` |
| **Shopping Agent** | 8000 | ユーザー代理エージェント | `/chat/stream`, `/create-intent`, `/create-payment` |
| **Merchant Agent** | 8001 | 商品検索・Cart作成 | `/products`, `/create-cart` |
| **Merchant** | 8002 | Cart署名・在庫管理 | `/sign/cart`, `/inventory/{sku}` |
| **Credential Provider** | 8003 | WebAuthn検証・トークン発行 | `/verify/attestation`, `/payment-methods` |
| **Payment Processor** | 8004 | 決済処理・トランザクション管理 | `/process`, `/transactions/{id}` |

---

## 主要フロー

### 1. 購買フロー全体

```mermaid
sequenceDiagram
    participant User as ユーザー<br/>(Browser)
    participant UI as Frontend<br/>(Next.js)
    participant SA as Shopping Agent<br/>:8000
    participant MA as Merchant Agent<br/>:8001
    participant M as Merchant<br/>:8002
    participant CP as Credential Provider<br/>:8003
    participant PP as Payment Processor<br/>:8004

    Note over User,PP: Phase 1: 購買意図の確立

    User->>UI: 1. チャット開始<br/>"ランニングシューズが欲しい"
    UI->>+SA: POST /chat/stream<br/>{user_input: "..."}

    SA->>SA: 2. セッション作成
    SA-->>UI: SSE: "何をお探しですか？"

    User->>UI: 3. 条件を入力<br/>"ナイキで15000円以下"
    UI->>SA: POST /chat/stream

    SA->>SA: 4. Intent Mandateを作成<br/>(max_amount: ¥15,000)
    SA->>SA: 5. ECDSA署名
    SA->>DB: Intent保存

    Note over User,PP: Phase 2: 商品検索とCart作成

    SA->>+MA: 6. A2A: 商品検索リクエスト<br/>POST /a2a/message
    MA->>MA: 7. 署名検証
    MA->>DB: 8. 商品検索 (Nike, ≤¥15,000)
    MA-->>-SA: 9. A2A: 商品リスト返却

    SA-->>UI: 10. SSE: 商品カルーセル表示
    UI-->>User: 11. 商品表示

    User->>UI: 12. 商品選択 (SKU: nike_001)
    UI->>SA: POST /chat/stream<br/>{selected_sku: "nike_001"}

    SA->>+MA: 13. A2A: Cart作成リクエスト<br/>POST /a2a/message
    MA->>MA: 14. Cart Mandate作成<br/>(未署名)
    MA-->>-SA: 15. A2A: Cart Mandate返却

    Note over User,PP: Phase 3: Cart署名とユーザー承認

    SA->>+M: 16. A2A: Cart署名リクエスト<br/>POST /a2a/message
    M->>M: 17. 在庫確認
    M->>M: 18. Merchant署名 (ECDSA)
    M-->>-SA: 19. A2A: 署名済みCart返却

    SA-->>UI: 20. SSE: 購入確認プロンプト
    UI-->>User: 21. "¥14,800で購入しますか？"

    User->>UI: 22. 購入確認 + Passkey署名
    UI->>UI: 23. WebAuthn署名生成
    UI->>SA: 24. {attestation, cart_mandate}

    SA->>+CP: 25. A2A: WebAuthn検証<br/>POST /a2a/message
    CP->>CP: 26. FIDO2署名検証
    CP->>CP: 27. Credential Token発行
    CP-->>-SA: 28. A2A: {verified: true, token}

    Note over User,PP: Phase 4: 決済処理

    SA->>SA: 29. Payment Mandate作成<br/>+ リスク評価
    SA->>SA: 30. Shopping Agent署名

    SA->>+MA: 31. A2A: Payment処理依頼<br/>POST /a2a/message
    MA->>+PP: 32. A2A: Payment転送<br/>POST /a2a/message

    PP->>PP: 33. 署名検証 (3層)
    PP->>PP: 34. リスク評価
    PP->>PP: 35. Authorize
    PP->>PP: 36. Capture
    PP->>DB: 37. Transaction保存

    PP-->>-MA: 38. A2A: 決済結果
    MA-->>-SA: 39. A2A: 決済結果転送

    SA->>DB: 40. Transaction保存
    SA-->>UI: 41. SSE: "決済完了！"
    UI-->>User: 42. 領収書表示
```

### 2. A2A通信の詳細

```mermaid
sequenceDiagram
    participant SA as Shopping Agent
    participant MA as Merchant Agent

    Note over SA,MA: A2A Message構造

    SA->>SA: 1. メッセージ作成<br/>{header, dataPart}
    SA->>SA: 2. Nonce生成 (UUID)
    SA->>SA: 3. Timestamp追加 (ISO 8601)
    SA->>SA: 4. ECDSA/Ed25519署名<br/>(RFC8785正規化)
    SA->>SA: 5. Proof構造追加<br/>{algorithm, kid, publicKey, signature}

    SA->>+MA: POST /a2a/message<br/>{header: {proof, nonce, ...}, dataPart}

    MA->>MA: 6. Nonce検証<br/>(再利用チェック)
    MA->>MA: 7. Timestamp検証<br/>(±300秒)
    MA->>MA: 8. Algorithm検証<br/>(ECDSA/Ed25519のみ)
    MA->>MA: 9. KID検証<br/>(DID形式)
    MA->>MA: 10. DID解決<br/>(公開鍵取得)
    MA->>MA: 11. 署名検証<br/>(RFC8785正規化 + ECDSA/Ed25519)

    alt 署名が有効
        MA->>MA: 12. ハンドラー実行
        MA->>MA: 13. レスポンス作成
        MA->>MA: 14. レスポンス署名
        MA-->>-SA: 200 OK + 署名済みレスポンス
    else 署名が無効
        MA-->>SA: 400 Bad Request<br/>{error: "invalid_signature"}
    end
```

### 3. WebAuthn/Passkey署名フロー

```mermaid
sequenceDiagram
    participant User as ユーザー
    participant UI as Frontend
    participant SA as Shopping Agent
    participant CP as Credential Provider

    Note over User,CP: WebAuthn/Passkey署名 (Step 21-22)

    SA->>SA: 1. Challenge生成<br/>(32バイトランダム)
    SA->>DB: 2. Challenge保存 (TTL: 5分)
    SA-->>UI: 3. Challenge返却

    UI-->>User: 4. "指紋/顔認証で承認してください"
    User->>User: 5. 生体認証 (TouchID/FaceID)

    UI->>UI: 6. navigator.credentials.get({<br/>  publicKey: {<br/>    challenge,<br/>    rpId: "localhost",<br/>    userVerification: "required"<br/>  }<br/>})

    UI->>UI: 7. Attestation取得<br/>{authenticatorData, signature, ...}

    UI->>SA: 8. POST {attestation, cart_mandate}

    SA->>+CP: 9. A2A: WebAuthn検証<br/>POST /verify/attestation

    CP->>CP: 10. Challenge検証<br/>(DB照合 + 有効期限)
    CP->>CP: 11. RP ID検証<br/>("localhost")
    CP->>CP: 12. User Verification検証<br/>(UV flag)
    CP->>CP: 13. Counter検証<br/>(リプレイ攻撃対策)
    CP->>CP: 14. COSE公開鍵で署名検証

    alt 検証成功
        CP->>CP: 15. Credential Token発行<br/>(cred_token_xxx)
        CP->>DB: 16. Counter更新
        CP-->>-SA: 17. {verified: true, token}
        SA-->>UI: 18. "署名検証完了"
    else 検証失敗
        CP-->>SA: {verified: false, error}
        SA-->>UI: 400 Bad Request
    end
```

### 4. リスク評価フロー

```mermaid
graph TD
    A[Payment Mandate作成] --> B{金額チェック}
    B -->|> ¥50,000| C[高額フラグ: +30点]
    B -->|≤ ¥50,000| D[通常: +0点]

    C --> E{Intent制約チェック}
    D --> E

    E -->|制約超過| F[制約違反フラグ: +40点]
    E -->|制約内| G[適合: +0点]

    F --> H{取引タイプ}
    G --> H

    H -->|CNP取引| I[CNPフラグ: +20点]
    H -->|CP取引| J[対面: +0点]

    I --> K{支払い方法}
    J --> K

    K -->|カード| L[カードリスク: +10点]
    K -->|Passkey| M[低リスク: +0点]

    L --> N[合計スコア計算]
    M --> N

    N --> O{スコア判定}

    O -->|0-30点| P[承認<br/>GREEN]
    O -->|31-60点| Q[要レビュー<br/>YELLOW]
    O -->|61-100点| R[拒否<br/>RED]

    style P fill:#c8e6c9
    style Q fill:#fff9c4
    style R fill:#ffcdd2
```

---

## セットアップ

### 前提条件

- Docker & Docker Compose
- Python 3.10+ (ローカル開発時)
- Node.js 18+ (フロントエンド開発時)

### クイックスタート（推奨）

```bash
# 1. リポジトリをクローン
git clone <repository-url>
cd ap2

# 2. 鍵とDIDドキュメントを生成（初回のみ）
cd v2
docker compose run --rm init-keys

# 3. 全サービスを起動
docker compose up --build

# 4. ブラウザでアクセス
open http://localhost:3000
```

### 起動確認

```bash
# 各サービスのヘルスチェック
curl http://localhost:8000/  # Shopping Agent
curl http://localhost:8001/  # Merchant Agent
curl http://localhost:8002/  # Merchant
curl http://localhost:8003/  # Credential Provider
curl http://localhost:8004/  # Payment Processor

# すべて以下のようなレスポンスが返ればOK
{
  "agent_id": "did:ap2:agent:shopping_agent",
  "agent_name": "Shopping Agent",
  "status": "running",
  "version": "2.0.0"
}
```

### ログ確認

```bash
# 全サービスのログを表示
docker compose logs -f

# 特定サービスのログ
docker compose logs -f shopping_agent

# デバッグモードで起動（詳細ログ）
LOG_LEVEL=DEBUG docker compose up
```

---

## 使い方

### 1. Chat UIで購買体験

1. http://localhost:3000/chat にアクセス
2. "ランニングシューズが欲しい" と入力
3. 条件を指定（ブランド、予算など）
4. 商品カルーセルから選択
5. 配送先を入力
6. Passkey署名（ブラウザの生体認証）
7. 決済完了 → 領収書表示

### 2. Merchant Dashboardで在庫管理

1. http://localhost:3000/merchant にアクセス
2. 商品一覧を確認
3. 在庫数を編集
4. 新規商品を追加

### 3. API直接呼び出し（開発者向け）

```bash
# IntentMandate作成
curl -X POST http://localhost:8000/create-intent \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user_demo_001",
    "max_amount": {"currency": "JPY", "value": "15000"},
    "allowed_merchants": ["did:ap2:merchant:sneaker_shop"],
    "allowed_categories": ["shoes"]
  }'

# 商品検索
curl "http://localhost:8001/products?query=nike&limit=5"

# A2Aメッセージ送信
curl -X POST http://localhost:8000/a2a/message \
  -H "Content-Type: application/json" \
  -d @sample_a2a_message.json
```

---

## 技術スタック

### バックエンド

| 技術 | バージョン | 用途 |
|------|-----------|------|
| **FastAPI** | 0.115.0 | RESTful API フレームワーク |
| **SQLAlchemy** | 2.0.35 | ORM（データベース操作） |
| **aiosqlite** | 0.20.0 | 非同期SQLiteドライバ |
| **cryptography** | 43.0.0 | ECDSA署名 |
| **fido2** | 1.1.3 | WebAuthn検証 |
| **sse-starlette** | 2.1.0 | Server-Sent Events |
| **httpx** | 0.27.0 | 非同期HTTPクライアント |
| **rfc8785** | 0.1.3 | JSON正規化（署名用） |

### フロントエンド

| 技術 | 用途 |
|------|------|
| **Next.js 15** | フルスタックフレームワーク（App Router） |
| **TypeScript** | 型安全性 |
| **TailwindCSS** | スタイリング |
| **shadcn/ui** | UIコンポーネント |

### インフラ

- **Docker Compose** - サービスオーケストレーション
- **SQLite** - データベース（開発環境）
- **Docker Volumes** - データ永続化

---

## 開発者向け情報

### ディレクトリ構造

```
v2/
├── common/                    # 共通モジュール
│   ├── models.py              # Pydanticモデル（A2Aメッセージ、API型）
│   ├── a2a_handler.py         # A2Aメッセージ処理・署名検証
│   ├── base_agent.py          # 全エージェントの基底クラス
│   ├── crypto.py              # 暗号化（ECDSA、Ed25519、AES-256）
│   ├── database.py            # SQLAlchemyモデル + CRUD
│   ├── risk_assessment.py     # リスク評価エンジン
│   ├── nonce_manager.py       # Nonce管理（リプレイ攻撃対策）
│   ├── did_resolver.py        # DID解決
│   ├── logger.py              # 統一ロギング
│   └── user_authorization.py  # User Authorization VP作成
├── services/                  # マイクロサービス
│   ├── shopping_agent/
│   │   ├── agent.py           # ShoppingAgentビジネスロジック
│   │   ├── main.py            # FastAPIエントリーポイント
│   │   └── Dockerfile
│   ├── merchant_agent/
│   ├── merchant/
│   ├── credential_provider/
│   └── payment_processor/
├── scripts/
│   ├── init_keys.py           # 鍵生成・DID作成
│   └── init_db.py             # データベース初期化
├── frontend/                  # Next.jsアプリ
│   ├── app/
│   ├── components/
│   └── lib/
├── data/                      # SQLiteデータベース格納
├── keys/                      # 暗号鍵格納（Docker Volume）
├── docker-compose.yml         # サービス定義
└── pyproject.toml             # Python依存関係
```

### クラス図（主要コンポーネント）

```mermaid
classDiagram
    class BaseAgent {
        <<abstract>>
        +agent_id: str
        +agent_name: str
        +key_manager: KeyManager
        +signature_manager: SignatureManager
        +a2a_handler: A2AMessageHandler
        +app: FastAPI
        +register_a2a_handlers()*
        +register_endpoints()*
        +get_ap2_roles()* list~str~
    }

    class ShoppingAgent {
        +db_manager: DatabaseManager
        +http_client: AsyncClient
        +credential_providers: list
        +chat_stream(request) EventSourceResponse
        +create_intent_mandate(request) IntentMandate
        +create_payment_mandate(request) PaymentMandate
        -_search_products_via_merchant_agent()
        -_process_payment_via_merchant_agent()
    }

    class MerchantAgent {
        +db_manager: DatabaseManager
        +search_products(query, limit) list~Product~
        +create_cart_mandate(items) CartMandate
        +handle_payment_processing(payment) dict
    }

    class Merchant {
        +db_manager: DatabaseManager
        +sign_cart_mandate(cart) CartMandate
        +check_inventory(sku) dict
        +update_inventory(sku, quantity) bool
    }

    class CredentialProvider {
        +db_manager: DatabaseManager
        +attestation_manager: AttestationManager
        +verify_webauthn_signature(attestation) dict
        +issue_credential_token(user_id) str
        +get_payment_methods(user_id) list
    }

    class PaymentProcessor {
        +db_manager: DatabaseManager
        +process_payment(payment_mandate) dict
        +authorize_transaction(payment) str
        +capture_transaction(txn_id) bool
        +refund_transaction(txn_id) str
    }

    class A2AMessageHandler {
        +agent_id: str
        +key_manager: KeyManager
        +signature_manager: SignatureManager
        +nonce_manager: NonceManager
        +did_resolver: DIDResolver
        +verify_message_signature(message) bool
        +handle_message(message) dict
        +create_response_message(data) A2AMessage
    }

    class KeyManager {
        +keys_directory: str
        +generate_key_pair(key_id, algorithm) tuple
        +load_private_key_encrypted(key_id, passphrase) PrivateKey
        +save_private_key_encrypted(key_id, key, passphrase)
        +get_public_key_pem(key_id, algorithm) str
    }

    class SignatureManager {
        +key_manager: KeyManager
        +sign_data(data, key_id, algorithm) Signature
        +verify_signature(data, signature, public_key) bool
    }

    class NonceManager {
        -_used_nonces: dict
        -_lock: asyncio.Lock
        +is_valid_nonce(nonce) bool
        +get_stats() dict
        +clear_all()
    }

    BaseAgent <|-- ShoppingAgent
    BaseAgent <|-- MerchantAgent
    BaseAgent <|-- Merchant
    BaseAgent <|-- CredentialProvider
    BaseAgent <|-- PaymentProcessor

    BaseAgent *-- A2AMessageHandler
    BaseAgent *-- KeyManager
    BaseAgent *-- SignatureManager

    A2AMessageHandler *-- NonceManager
    A2AMessageHandler *-- KeyManager
    A2AMessageHandler *-- SignatureManager

    SignatureManager *-- KeyManager
```

### 主要なデータモデル

```mermaid
classDiagram
    class A2AMessage {
        +header: MessageHeader
        +dataPart: DataPart
    }

    class MessageHeader {
        +message_id: str
        +sender: str (DID)
        +recipient: str (DID)
        +timestamp: str (ISO 8601)
        +nonce: str (UUID)
        +proof: Proof
        +schema_version: str
    }

    class Proof {
        +algorithm: str (ECDSA/Ed25519)
        +kid: str (DID#key-1)
        +publicKey: str (base64)
        +signature: str (base64)
    }

    class DataPart {
        +type: str (@type)
        +id: str
        +payload: dict
    }

    class IntentMandate {
        +user_id: str
        +max_amount: Amount
        +allowed_merchants: list~str~
        +allowed_categories: list~str~
        +expiry: str
        +user_signature: Signature
    }

    class CartMandate {
        +merchant_id: str
        +items: list~CartItem~
        +total_amount: Amount
        +shipping_address: Address
        +merchant_signature: Signature
        +user_signature: Signature
    }

    class PaymentMandate {
        +cart_mandate: CartMandate
        +intent_mandate: IntentMandate
        +credential_provider_id: str
        +risk_score: int
        +fraud_indicators: list~str~
        +shopping_agent_signature: Signature
    }

    A2AMessage *-- MessageHeader
    A2AMessage *-- DataPart
    MessageHeader *-- Proof

    DataPart ..> IntentMandate : payload
    DataPart ..> CartMandate : payload
    DataPart ..> PaymentMandate : payload
```

### 環境変数

```bash
# ロギング設定
LOG_LEVEL=INFO                    # DEBUG/INFO/WARNING/ERROR/CRITICAL
LOG_FORMAT=text                   # text/json

# データベース
DATABASE_URL=sqlite+aiosqlite:////app/v2/data/shopping_agent.db

# 鍵管理
AP2_KEYS_DIRECTORY=/app/v2/keys
AP2_SHOPPING_AGENT_PASSPHRASE=your_passphrase_here
AP2_MERCHANT_AGENT_PASSPHRASE=your_passphrase_here
AP2_MERCHANT_PASSPHRASE=your_passphrase_here
AP2_CREDENTIAL_PROVIDER_PASSPHRASE=your_passphrase_here
AP2_PAYMENT_PROCESSOR_PASSPHRASE=your_passphrase_here

# サービスエンドポイント（Docker Compose内部）
MERCHANT_AGENT_URL=http://merchant_agent:8001
MERCHANT_URL=http://merchant:8002
PAYMENT_PROCESSOR_URL=http://payment_processor:8004
CREDENTIAL_PROVIDER_URL=http://credential_provider:8003
```

### トラブルシューティング

#### 鍵が見つからないエラー

```bash
# 鍵を再生成
docker compose run --rm init-keys

# または手動で
docker compose exec shopping_agent python /app/v2/scripts/init_keys.py
```

#### データベースエラー

```bash
# データベースをリセット
docker compose down -v
docker compose up --build
```

#### ポート競合

```bash
# 使用中のポートを確認
lsof -ti:8000 | xargs kill -9
```

### テスト

```bash
# 単体テスト（準備中）
pytest v2/tests/

# A2A通信テスト
python v2/tests/test_a2a_communication.py

# WebAuthn検証テスト
python v2/tests/test_webauthn.py
```

---

## AP2仕様準拠状況

| フェーズ | 準拠率 | 状態 |
|---------|--------|------|
| **Phase 1: Intent確立** | 100% | ✅ 完全実装 |
| **Phase 2: Cart構築** | 100% | ✅ 完全実装 |
| **Phase 3: 処理順序** | 100% | ✅ Merchant Agent経由 |
| **Phase 4: User Authorization** | 100% | ✅ WebAuthn/Passkey |
| **Phase 5: 決済実行** | 100% | ✅ リスク評価含む |
| **A2A通信** | 100% | ✅ 署名検証・Nonce・DID |

詳細は[AP2_COMPLIANCE_REPORT.md](./v2/AP2_COMPLIANCE_REPORT.md)を参照してください。

---

## ライセンス

このプロジェクトはAP2プロトコルのデモ実装です。

---

## 参考資料

- [AP2公式サイト](https://ap2-protocol.org/)
- [AP2仕様書](https://ap2-protocol.org/specification/)
- [Google AP2サンプル](https://github.com/google-agentic-commerce/AP2)
- [A2A拡張仕様](./v2/refs/AP2-main/docs/a2a-extension.md)

---

**作成日**: 2025-10-21
**バージョン**: v2.0.0
**ステータス**: 本番準備完了 ✅
