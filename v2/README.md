# AP2 Demo App v2

AP2プロトコルのマイクロサービスアーキテクチャ実装版。FastAPI + Docker Compose + Next.jsで構築。

## 📁 ディレクトリ構造

```
v2/
├── common/                  # 共通モジュール
│   ├── models.py            # Pydanticモデル（A2Aメッセージ、API型）
│   ├── a2a_handler.py       # A2Aメッセージ処理・署名検証・ルーティング
│   ├── base_agent.py        # 全エージェントの基底クラス（POST /a2a/message実装）
│   ├── database.py          # SQLAlchemyモデル＋CRUD操作
│   └── seed_data.py         # サンプルデータ投入スクリプト
├── services/                # 各マイクロサービス
│   ├── shopping_agent/      # ✅ 実装済み
│   │   ├── agent.py         # ShoppingAgentビジネスロジック
│   │   ├── main.py          # FastAPIエントリーポイント
│   │   └── Dockerfile       # コンテナ定義
│   ├── merchant_agent/      # ✅ 実装済み
│   │   ├── agent.py         # 商品検索・CartMandate作成
│   │   ├── main.py
│   │   └── Dockerfile
│   ├── merchant/            # ✅ 実装済み
│   │   ├── service.py       # CartMandate署名
│   │   ├── main.py
│   │   └── Dockerfile
│   ├── credential_provider/ # ✅ 実装済み
│   │   ├── provider.py      # WebAuthn検証・トークン発行
│   │   ├── main.py
│   │   └── Dockerfile
│   └── payment_processor/   # ✅ 実装済み
│       ├── processor.py     # 決済処理・トランザクション管理
│       ├── main.py
│       └── Dockerfile
├── scripts/                 # ユーティリティスクリプト
│   └── init_db.py           # データベース初期化
├── data/                    # SQLiteデータベース格納ディレクトリ
├── pyproject.toml           # uv管理の依存関係定義
└── README.md                # このファイル
```

## ✅ 完成部分（Phase 1）

### 共通モジュール
- ✅ **models.py** - FastAPI用Pydanticモデル（A2Aメッセージ、API型）
- ✅ **a2a_handler.py** - A2Aメッセージ処理・署名検証・ルーティング
- ✅ **base_agent.py** - 全エージェントの基底クラス（POST /a2a/message実装）
- ✅ **database.py** - SQLiteスキーマ＋CRUD操作
- ✅ **seed_data.py** - サンプルデータ（商品8点、ユーザー2人）

### マイクロサービス（全5サービス完成！）
- ✅ **Shopping Agent** (Port 8000) - ユーザーとの対話、IntentMandate作成、SSE/Streaming対応
- ✅ **Merchant Agent** (Port 8001) - 商品検索、CartMandate作成（未署名）
- ✅ **Merchant** (Port 8002) - CartMandate署名・在庫検証
- ✅ **Credential Provider** (Port 8003) - WebAuthn検証・トークン発行
- ✅ **Payment Processor** (Port 8004) - 決済処理・トランザクション管理

### フロントエンド（完成！）
- ✅ **Next.js Frontend** (Port 3000) - Chat UI、Merchant管理画面
  - Chat UI: SSE/Streaming対応、商品カルーセル、Passkey署名
  - Merchant Dashboard: 在庫管理、商品一覧
  - TypeScript + TailwindCSS + shadcn/ui

### インフラ
- ✅ **Docker Compose** - 全6サービスのオーケストレーション

## 🛠️ セットアップ手順

### 🚀 クイックスタート（Docker Compose推奨）

最も簡単な方法は、Docker Composeを使用して全5サービスを一括起動することです。

```bash
# 1. データベース初期化（初回のみ）
python v2/scripts/init_db.py

# 2. 全サービスをビルド＆起動
cd v2/
docker compose up --build

# または、バックグラウンドで起動
docker compose up --build -d
```

**起動確認：**
```bash
# 各サービスのヘルスチェック
curl http://localhost:8000/  # Shopping Agent
curl http://localhost:8001/  # Merchant Agent
curl http://localhost:8002/  # Merchant
curl http://localhost:8003/  # Credential Provider
curl http://localhost:8004/  # Payment Processor

# フロントエンドにアクセス
open http://localhost:3000  # ホームページ
open http://localhost:3000/chat  # Chat UI
open http://localhost:3000/merchant  # Merchant管理画面
```

**ログ確認：**
```bash
# 全サービスのログを表示
docker compose logs -f

# 特定サービスのログを表示
docker compose logs -f shopping_agent
```

**停止：**
```bash
# 停止（コンテナは保持）
docker compose stop

# 停止＆削除
docker compose down

# ボリュームも含めて完全削除
docker compose down -v
```

---

### 📦 開発環境セットアップ（ローカル実行）

Docker Composeを使わず、各サービスを個別に実行する場合の手順です。

### 1. 依存関係のインストール（uv使用）

```bash
cd v2/

# uvがインストールされていない場合
pip install uv

# 依存関係をインストール
uv pip install -e .
```

### 2. データベース初期化とサンプルデータ投入

```bash
# プロジェクトルート（ap2/）から実行
cd /path/to/ap2

# データベース初期化＋サンプルデータ投入
python v2/common/seed_data.py
```

**出力例：**
```
============================================================
AP2 Demo v2 - サンプルデータ投入
============================================================

データベース初期化中...
✅ データベース初期化完了

============================================================
商品データ投入中...
============================================================
  ✅ 作成: ナイキ エアズーム ペガサス 40 (¥14,800)
  ✅ 作成: アディダス ウルトラブースト 22 (¥19,800)
  ...

✅ 商品データ投入完了 (8件)

============================================================
ユーザーデータ投入中...
============================================================
  ✅ 作成: 山田太郎 (yamada@example.com)
  ✅ 作成: 佐藤花子 (sato@example.com)

✅ ユーザーデータ投入完了 (2件)

============================================================
🎉 すべてのサンプルデータ投入が完了しました！
============================================================
```

### 3. Shopping Agent起動（スタンドアロン）

```bash
cd v2/services/shopping_agent/
python main.py
```

**起動確認：**
```bash
# ヘルスチェック
curl http://localhost:8000/

# 期待されるレスポンス:
{
  "agent_id": "did:ap2:agent:shopping_agent",
  "agent_name": "Shopping Agent",
  "status": "running",
  "version": "2.0.0"
}
```

### 4. Dockerビルド（準備中）

```bash
# Shopping AgentのDockerイメージをビルド
docker build -f v2/services/shopping_agent/Dockerfile -t ap2-shopping-agent:latest .

# 起動
docker run -p 8000:8000 ap2-shopping-agent:latest
```

## 📡 API エンドポイント

### 共通エンドポイント（全サービス）

すべてのサービスが以下のエンドポイントを持ちます：

- `GET /` - ヘルスチェック（agent_id, agent_name, status, versionを返す）
- `GET /health` - ヘルスチェック（Docker向け）
- `POST /a2a/message` - A2Aメッセージ受信（BaseAgentで自動実装）

---

### Shopping Agent (Port 8000)

ユーザーとの対話を担当するエージェント。

**固有エンドポイント：**

- `POST /chat/stream` - ユーザーとの対話（SSE Streaming）
  - リクエスト: `{ "user_input": "ランニングシューズが欲しい", "session_id"?: "..." }`
  - レスポンス: Server-Sent Events（JSON lines）
  ```
  data: {"type": "agent_text", "content": "こんにちは！"}
  data: {"type": "product_list", "products": [...]}
  data: {"type": "done"}
  ```

- `POST /create-intent` - IntentMandate作成
  - リクエスト: `{ "user_id": "user_demo_001", "max_amount": {...}, ... }`
  - レスポンス: IntentMandate（署名付き）

- `POST /create-payment` - PaymentMandate作成
  - リクエスト: `{ "cart_mandate": {...}, "intent_mandate": {...}, ... }`
  - レスポンス: PaymentMandate（リスクスコア付き）

- `GET /transactions/{transaction_id}` - トランザクション取得

---

### Merchant Agent (Port 8001)

商品検索とCartMandate作成を担当。

**固有エンドポイント：**

- `GET /products?query=...&limit=10` - 商品検索
  - レスポンス: `{ "products": [...], "total": N }`

- `POST /create-cart` - CartMandate作成（未署名）
  - リクエスト: `{ "items": [...], "merchant_id": "...", ... }`
  - レスポンス: CartMandate（merchant_signature = null）

---

### Merchant (Port 8002)

CartMandateの署名・在庫検証を担当。

**固有エンドポイント：**

- `POST /sign/cart` - CartMandate署名
  - リクエスト: `{ "cart_mandate": {...} }`
  - レスポンス: CartMandate（merchant_signature付き）

- `GET /inventory/{sku}` - 在庫確認
  - レスポンス: `{ "sku": "...", "available": N }`

---

### Credential Provider (Port 8003)

WebAuthn検証とトークン発行を担当。

**固有エンドポイント：**

- `POST /verify/attestation` - WebAuthn attestation検証
  - リクエスト: `{ "payment_mandate": {...}, "attestation": {...} }`
  - レスポンス: `{ "verified": true, "token": "cred_token_...", "details": {...} }`

- `GET /payment-methods?user_id=...` - 支払い方法一覧
  - レスポンス: `{ "user_id": "...", "payment_methods": [...] }`

- `POST /payment-methods` - 支払い方法追加
  - リクエスト: `{ "user_id": "...", "payment_method": {...} }`
  - レスポンス: 追加された支払い方法

---

### Payment Processor (Port 8004)

決済処理とトランザクション管理を担当。

**固有エンドポイント：**

- `POST /process` - 支払い処理実行
  - リクエスト: `{ "payment_mandate": {...}, "credential_token"?: "..." }`
  - レスポンス: `{ "transaction_id": "txn_...", "status": "captured", "receipt_url": "..." }`

- `GET /transactions/{transaction_id}` - トランザクション取得

- `POST /refund` - 返金処理
  - リクエスト: `{ "transaction_id": "txn_...", "reason": "..." }`
  - レスポンス: `{ "refund_id": "refund_...", "status": "refunded" }`

## 🧪 テスト方法

### 1. ヘルスチェック

```bash
curl http://localhost:8000/
```

### 2. チャット対話（SSE Streaming）

```bash
# curlでSSEをテスト
curl -N -H "Content-Type: application/json" \
  -d '{"user_input": "こんにちは"}' \
  http://localhost:8000/chat/stream
```

**期待される出力（SSE形式）：**
```
data: {"type":"agent_text","content":"こんにちは！AP2 Shopping Agentです。"}

data: {"type":"agent_text","content":"何をお探しですか？例えば「むぎぼーのグッズが欲しい」のように教えてください。"}

data: {"type":"done"}
```

### 3. A2Aメッセージテスト（Postman推奨）

```bash
# A2Aメッセージを送信（署名付き）
curl -X POST http://localhost:8000/a2a/message \
  -H "Content-Type: application/json" \
  -d '{
    "header": {
      "message_id": "test-123",
      "sender": "did:ap2:agent:merchant_agent",
      "recipient": "did:ap2:agent:shopping_agent",
      "timestamp": "2025-10-16T00:00:00Z",
      "schema_version": "0.2"
    },
    "dataPart": {
      "@type": "ap2/ProductList",
      "id": "prod-list-001",
      "payload": {
        "products": []
      }
    }
  }'
```

## 📚 技術スタック

### バックエンド
- **FastAPI** 0.115.0 - 高速なWebフレームワーク
- **SQLAlchemy** 2.0.35 - ORM
- **aiosqlite** 0.20.0 - 非同期SQLite
- **cryptography** 43.0.0 - 暗号署名（ECDSA）
- **fido2** 1.1.3 - WebAuthn検証
- **sse-starlette** 2.1.0 - Server-Sent Events
- **httpx** 0.27.0 - 非同期HTTPクライアント

### フロントエンド（Phase 2で実装予定）
- Next.js 15 (App Router)
- TypeScript
- TailwindCSS
- shadcn/ui

### インフラ
- Docker + Docker Compose
- SQLite（開発環境）

## 🔐 セキュリティ

### 鍵管理
- 各エージェントはECDSA鍵ペアを自動生成
- 秘密鍵はAES-256-CBCで暗号化して`./keys/`に保存
- パスフレーズは環境変数または`AgentPassphraseManager`から取得

### A2A署名検証
- 全A2Aメッセージは署名付き
- `a2a_handler.py`で自動的に署名検証
- 署名検証失敗時は400エラー

### ロギング設定

統一ロギングシステムを使用しており、環境変数で制御可能です。

**環境変数:**
```bash
# ログレベル（DEBUG/INFO/WARNING/ERROR/CRITICAL）
LOG_LEVEL=INFO  # デフォルト: INFO

# ログフォーマット（text/json）
LOG_FORMAT=text  # デフォルト: text
```

**ログレベルの説明:**
- `DEBUG`: 詳細なデバッグ情報（HTTPペイロード、A2Aメッセージ、署名操作等）
- `INFO`: 一般的な情報メッセージ（鍵生成、トランザクション開始等）
- `WARNING`: 警告メッセージ（チャレンジ失敗、タイムスタンプずれ等）
- `ERROR`: エラーメッセージ（検証失敗、データベースエラー等）
- `CRITICAL`: 致命的なエラー（サービス起動失敗等）

**フォーマットの説明:**
- `text`: 人間が読みやすい形式（開発環境向け）
  ```
  [2025-10-21 12:34:56] INFO     common.crypto                  | Generating new key pair: shopping_agent
  ```
- `json`: 構造化JSON形式（本番環境向け、ログ集約ツールと連携）
  ```json
  {"timestamp":"2025-10-21T12:34:56Z","level":"INFO","logger":"common.crypto","message":"Generating new key pair: shopping_agent"}
  ```

**使用例:**
```bash
# デバッグモードで起動（すべてのHTTPペイロードを表示）
LOG_LEVEL=DEBUG docker compose up

# 本番環境（JSON形式、WARNINGレベル以上のみ）
LOG_LEVEL=WARNING LOG_FORMAT=json docker compose up
```

**機能:**
- 機密データの自動マスキング（password, token, private_key等）
- HTTPリクエスト/レスポンスの自動ログ（DEBUGレベル）
- A2Aメッセージペイロードの自動ログ（DEBUGレベル）
- 暗号化操作の詳細ログ（署名、検証、鍵生成）
- サービス別ログタグ（shopping_agent, merchant等）

## 🚧 次のステップ

### Phase 1: バックエンド（✅ 完了！）
- ✅ Shopping Agent実装
- ✅ Merchant Agent実装
- ✅ Merchant実装
- ✅ Credential Provider実装
- ✅ Payment Processor実装
- ✅ Docker Compose統合

### Phase 2: フロントエンド（次）
- ⏳ Next.js プロジェクトセットアップ（TypeScript + TailwindCSS + shadcn/ui）
- ⏳ Chat UI（SSE/Streaming対応）
- ⏳ SignaturePromptModal（WebAuthn統合）
- ⏳ ProductCarousel コンポーネント
- ⏳ Merchant管理画面

### Phase 3: 拡張機能
- ⏳ LangGraph統合（LLM連携）
- ⏳ MCP（Model Context Protocol）ツール連携
- ⏳ Risk Assessment Engine強化
- ⏳ Kubernetes/ECS移行準備

## 📖 参考資料

- [demo_app_v2.md](../demo_app_v2.md) - v2要件書
- [CLAUDE.md](../CLAUDE.md) - プロジェクト概要
- [AP2 Official Spec](https://ap2-protocol.org/specification/)
- [Google AP2 Samples](./refs/AP2-main/)

## 🐛 トラブルシューティング

### データベースエラー
```bash
# データベースをリセット
rm v2/data/ap2.db

# 再初期化
python v2/common/seed_data.py
```

### 鍵生成エラー
```bash
# 鍵ディレクトリをリセット
rm -rf keys/

# サービスを再起動すると自動生成されます
```

### ポート競合
```bash
# ポート8000が使用中の場合
lsof -ti:8000 | xargs kill -9
```

## 📝 ライセンス

このプロジェクトはAP2プロトコルのデモ実装です。

---

**作成日**: 2025-10-16
**バージョン**: v2.0.0-alpha
**ステータス**: Phase 1 完了 ✅ → Phase 2 準備中
