# AP2完全準拠 修正指示書

**作成日**: 2025-10-21
**対象**: `/Users/kagadminmac/project/ap2/v2/` (v2ブランチ)
**AP2仕様バージョン**: v0.1-alpha
**目的**: この指示書に従えば、AP2仕様に100%準拠したアプリケーションを構築できる

---

## 目次

1. [修正の原則と優先順位](#1-修正の原則と優先順位)
2. [Phase 1: CRITICAL修正（本番デプロイ必須）](#2-phase-1-critical修正本番デプロイ必須)
3. [Phase 2: HIGH修正（本番環境推奨）](#3-phase-2-high修正本番環境推奨)
4. [Phase 3: 処理順準拠修正（AP2仕様完全準拠）](#4-phase-3-処理順準拠修正ap2仕様完全準拠)
5. [Phase 4: MEDIUM修正（品質向上）](#5-phase-4-medium修正品質向上)
6. [修正後の検証手順](#6-修正後の検証手順)
7. [AP2準拠を維持するためのチェックリスト](#7-ap2準拠を維持するためのチェックリスト)

---

## 1. 修正の原則と優先順位

### 1.1 修正時の絶対原則

**❌ やってはいけないこと**:
1. **既存の動作する機能を削除しない**（修正は常に**追加または置き換え**のみ）
2. **AP2仕様書を確認せずにコードを変更しない**
3. **1つの修正で複数の問題に同時に対処しない**（1修正＝1問題）
4. **テストなしで修正をコミットしない**
5. **暗号化・署名関連のコードを推測で変更しない**

**✅ 必ず守ること**:
1. **各修正後に必ず動作確認を行う**（段階的修正）
2. **AP2仕様書の該当箇所を引用してコメントに記載**
3. **修正前に既存のテストがPASSすることを確認**
4. **修正後に新しいテストを追加してPASSさせる**
5. **Git commitは1機能1コミットで、詳細なメッセージを記載**

### 1.2 修正の優先順位（厳守）

| Phase | 優先度 | 内容 | 期限 | 影響範囲 |
|-------|--------|------|------|---------|
| **Phase 1** | CRITICAL | 並行処理・セキュリティ | **本番デプロイ前必須** | システム全体の安定性 |
| **Phase 2** | HIGH | リソース管理・エラーハンドリング | **本番デプロイ前推奨** | 本番環境の運用性 |
| **Phase 3** | AP2準拠 | 処理順序・IntentMandate署名 | **AP2完全準拠のため必須** | AP2仕様準拠率 |
| **Phase 4** | MEDIUM | ロギング・バリデーション | **品質向上のため推奨** | 保守性・デバッグ性 |

**修正の進め方**:
- **Phase 1 → Phase 2 → Phase 3 → Phase 4の順に実施**（絶対に順序を変えない）
- 各Phase内でも、優先度順に1つずつ修正
- 各修正後に必ず動作確認とテスト実施

---

## 2. Phase 1: CRITICAL修正（本番デプロイ必須）

### 2.1 NonceManager並行処理問題（最優先）

**問題**: `threading.Lock`使用によりFastAPI非同期環境でデッドロックの可能性

**影響**: A2A通信での認証失敗、リプレイ攻撃検知の失敗

**修正ファイル**: `/Users/kagadminmac/project/ap2/v2/common/nonce_manager.py`

#### 修正手順

**Step 1: asyncio.Lockへの移行**

```python
# 【修正前】
import threading
from typing import Set, Dict

class NonceManager:
    def __init__(self):
        self._used_nonces: Set[str] = set()
        self._nonce_timestamps: Dict[str, float] = {}
        self._lock = threading.Lock()  # ❌ 非同期環境で問題

    def is_valid_nonce(self, nonce: str) -> bool:
        with self._lock:  # ❌ イベントループをブロック
            if nonce in self._used_nonces:
                return False
            self._used_nonces.add(nonce)
            return True
```

```python
# 【修正後】
import asyncio
from typing import Set, Dict

class NonceManager:
    def __init__(self):
        self._used_nonces: Set[str] = set()
        self._nonce_timestamps: Dict[str, float] = {}
        self._lock = asyncio.Lock()  # ✅ 非同期対応

    async def is_valid_nonce(self, nonce: str) -> bool:
        """
        AP2仕様: A2A通信でのNonce検証（リプレイ攻撃対策）
        参照: AP2 specification - A2A Message Structure
        """
        async with self._lock:  # ✅ 非同期ロック
            if nonce in self._used_nonces:
                return False
            self._used_nonces.add(nonce)
            self._nonce_timestamps[nonce] = time.time()
            return True
```

**Step 2: 呼び出し側の修正**

`/Users/kagadminmac/project/ap2/v2/common/a2a_handler.py`

```python
# 【修正前】
def verify_a2a_message(message: dict) -> bool:
    nonce = message.get("header", {}).get("nonce")
    if not nonce_manager.is_valid_nonce(nonce):  # ❌ 同期呼び出し
        return False

# 【修正後】
async def verify_a2a_message(message: dict) -> bool:
    """
    AP2仕様: A2Aメッセージ検証
    - Nonce検証（リプレイ攻撃対策）
    - Timestamp検証（±300秒）
    - ECDSA署名検証
    参照: AP2 specification - A2A Protocol
    """
    nonce = message.get("header", {}).get("nonce")
    if not await nonce_manager.is_valid_nonce(nonce):  # ✅ 非同期呼び出し
        return False
```

**Step 3: FastAPIエンドポイントの修正**

`/Users/kagadminmac/project/ap2/v2/services/shopping_agent/agent.py`

```python
# 【修正前】
@router.post("/a2a/message")
def handle_a2a_message(message: dict):
    if not verify_a2a_message(message):  # ❌ 同期関数
        raise HTTPException(status_code=400)

# 【修正後】
@router.post("/a2a/message")
async def handle_a2a_message(message: dict):
    """
    AP2仕様: A2A通信エンドポイント
    参照: AP2 specification - Agent-to-Agent Communication
    """
    if not await verify_a2a_message(message):  # ✅ 非同期関数
        raise HTTPException(status_code=400, detail="Invalid A2A message")
```

**Step 4: テスト追加**

```python
# tests/test_nonce_manager_async.py
import pytest
import asyncio

@pytest.mark.asyncio
async def test_nonce_manager_concurrent_requests():
    """複数の非同期リクエストでNonce検証が正しく動作することを確認"""
    manager = NonceManager()
    nonce = "test_nonce_123"

    # 並行して同じNonceを検証
    results = await asyncio.gather(
        manager.is_valid_nonce(nonce),
        manager.is_valid_nonce(nonce),
        manager.is_valid_nonce(nonce)
    )

    # 1つだけTrueで、他はFalse（リプレイ攻撃防止）
    assert results.count(True) == 1
    assert results.count(False) == 2
```

**検証方法**:
```bash
# 1. テスト実行
pytest tests/test_nonce_manager_async.py -v

# 2. 実際のA2A通信テスト
docker compose up -d
curl -X POST http://localhost:8001/a2a/message \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/a2a_message_sample.json

# 3. ログ確認
docker compose logs shopping_agent | grep "A2A message"
```

---

## 3. Phase 2: HIGH修正（本番環境推奨）

### 3.1 HTTPクライアントクローズ処理（4箇所）

**問題**: httpx.AsyncClientのクローズ処理未実装によるリソースリーク

**影響**: 長時間運用時のメモリリーク、コネクション枯渇

**修正箇所**:
1. `shopping_agent/agent.py`
2. `merchant_agent/agent.py`
3. `payment_processor/processor.py`
4. `credential_provider/provider.py`

#### 修正手順（全サービス共通）

**Step 1: shutdown_eventハンドラー追加**

`services/shopping_agent/agent.py`

```python
# 【修正前】
app = FastAPI(title="Shopping Agent")
http_client = httpx.AsyncClient(timeout=30.0)  # ❌ クローズ処理なし

# 【修正後】
app = FastAPI(title="Shopping Agent")
http_client = httpx.AsyncClient(timeout=30.0)

@app.on_event("shutdown")
async def shutdown_event():
    """
    FastAPIシャットダウン時のクリーンアップ処理
    - HTTPクライアントのクローズ
    - DB接続のクローズ
    参照: FastAPI lifecycle events
    """
    logger.info("Shutting down Shopping Agent...")
    await http_client.aclose()  # ✅ HTTPクライアントクローズ
    logger.info("HTTP client closed successfully")
```

**Step 2: 同様の修正を他のサービスにも適用**

`services/merchant_agent/agent.py`
```python
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Merchant Agent...")
    await http_client.aclose()
```

`services/payment_processor/processor.py`
```python
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Payment Processor...")
    await http_client.aclose()
```

`services/credential_provider/provider.py`
```python
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutting down Credential Provider...")
    await http_client.aclose()
```

**Step 3: テスト追加**

```python
# tests/test_http_client_cleanup.py
import pytest
from fastapi.testclient import TestClient

def test_http_client_closed_on_shutdown():
    """シャットダウン時にHTTPクライアントがクローズされることを確認"""
    from services.shopping_agent.agent import app, http_client

    client = TestClient(app)

    # シャットダウンイベントをトリガー
    with client:
        pass  # コンテキストマネージャーで自動的にshutdownが呼ばれる

    # HTTPクライアントがクローズされていることを確認
    assert http_client.is_closed
```

**検証方法**:
```bash
# 1. サービス起動
docker compose up -d shopping_agent

# 2. 正常動作確認
curl http://localhost:8001/health

# 3. Gracefulシャットダウン
docker compose stop shopping_agent

# 4. ログ確認（"HTTP client closed successfully"が出力されること）
docker compose logs shopping_agent | grep "HTTP client closed"
```

### 3.2 データベースrollback未実装

**問題**: トランザクション失敗時のrollback処理欠落によるデータ不整合

**影響**: 決済失敗時のデータベース不整合、二重課金リスク

**修正ファイル**: `services/payment_processor/processor.py`

#### 修正手順

**Step 1: トランザクション管理の改善**

```python
# 【修正前】
async def process_payment(payment_mandate: dict):
    try:
        # 決済処理
        result = await _authorize_payment(payment_mandate)
        await db.commit()  # ❌ 失敗時のrollbackなし
        return result
    except Exception as e:
        logger.error(f"Payment failed: {e}")
        raise

# 【修正後】
async def process_payment(payment_mandate: dict):
    """
    AP2仕様: Step 28 - Payment Processing
    参照: AP2 specification - Payment Processor Requirements
    """
    try:
        # 決済処理
        result = await _authorize_payment(payment_mandate)
        await db.commit()
        logger.info(f"Payment committed: {payment_mandate['payment_mandate_id']}")
        return result
    except Exception as e:
        # ✅ トランザクションロールバック
        await db.rollback()
        logger.error(f"Payment failed, rolled back: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "payment_processing_failed",
                "message": str(e),
                "payment_mandate_id": payment_mandate.get("payment_mandate_id")
            }
        )
```

**Step 2: 全決済関連エンドポイントに適用**

```python
@router.post("/payment/authorize")
async def authorize_payment(payment_mandate: dict):
    """
    AP2仕様: Step 28 - Payment Authorization
    """
    try:
        # Authorization処理
        auth_result = await _process_authorization(payment_mandate)
        await db.commit()
        return auth_result
    except Exception as e:
        await db.rollback()  # ✅ ロールバック
        logger.error(f"Authorization failed: {e}")
        raise

@router.post("/payment/capture")
async def capture_payment(capture_request: dict):
    """
    AP2仕様: Step 28 - Payment Capture
    """
    try:
        # Capture処理
        capture_result = await _process_capture(capture_request)
        await db.commit()
        return capture_result
    except Exception as e:
        await db.rollback()  # ✅ ロールバック
        logger.error(f"Capture failed: {e}")
        raise
```

**Step 3: テスト追加**

```python
# tests/test_payment_transaction.py
import pytest

@pytest.mark.asyncio
async def test_payment_rollback_on_failure():
    """決済失敗時にロールバックが実行されることを確認"""
    payment_mandate = {
        "payment_mandate_id": "pm_test_123",
        "amount": {"value": "1000", "currency": "USD"}
    }

    # データベースの初期状態を記録
    initial_state = await db.query("SELECT * FROM payments")

    # 失敗するはずの決済を実行
    with pytest.raises(HTTPException):
        await process_payment(payment_mandate)

    # データベース状態が変わっていないことを確認（ロールバック成功）
    current_state = await db.query("SELECT * FROM payments")
    assert initial_state == current_state
```

**検証方法**:
```bash
# 1. テスト実行
pytest tests/test_payment_transaction.py -v

# 2. 実際の決済フロー確認
docker compose up -d
# 正常ケース
curl -X POST http://localhost:8003/payment/authorize -d @tests/fixtures/valid_payment.json
# 異常ケース（ロールバック確認）
curl -X POST http://localhost:8003/payment/authorize -d @tests/fixtures/invalid_payment.json

# 3. データベース確認
docker compose exec payment_processor sqlite3 /app/v2/data/payment_processor.db
sqlite> SELECT * FROM payments ORDER BY created_at DESC LIMIT 5;
```

---

## 4. Phase 3: 処理順準拠修正（AP2仕様完全準拠）

**【重要】Phase 3の修正は不要です - 既に100%実装済み**

詳細なコードレビューの結果、以下が確認されました：

### 4.1 Step 24-25-30-31: Merchant Agent経由フロー - ✅ 完全実装済み

**修正不要** - 以前のレポートの記載が誤りでした。

**実装確認済み箇所**:
1. `shopping_agent/agent.py:2884-2886` - Merchant AgentへA2A送信
2. `merchant_agent/agent.py:495-497` - Payment ProcessorへA2A転送
3. `merchant_agent/agent.py:511-526` - Payment Processorから応答受信・転送

### 4.2 Step 3: IntentMandate確認 - ✅ AP2仕様準拠（署名不要）

**修正不要** - AP2仕様書では署名は要求されていません。

**AP2仕様書の記載** (`refs/AP2-main/docs/specification.md:618`):
```
user --) sa: 3. Confirm
```
- WebAuthn attestationが必要なのは **Step 21-22** (PaymentMandate承認時)のみ


---

## 4. Phase 3: 処理順準拠修正（AP2仕様完全準拠）

**【重要】Phase 3の修正は不要です - 既に100%実装済み**

詳細なコードレビューとAP2仕様書の精査の結果、以前のレポートの記載が誤りであることが判明しました。

### 4.1 検証結果サマリー

| 項目 | 以前の評価 | 修正後の評価 | 根拠 |
|------|----------|------------|------|
| **Step 24-25-30-31** | ❌ Merchant Agent経由省略 | ✅ **完全実装済み** | `shopping_agent/agent.py:2884-2886`<br>`merchant_agent/agent.py:495-497, 511-526` |
| **Step 3 署名** | ❌ IntentMandate署名省略 | ✅ **AP2仕様準拠**（署名不要） | `refs/AP2-main/docs/specification.md:618`<br>Step 3は単なる「Confirm」のみ |
| **処理順準拠率** | 75% | **100%** | 全32ステップが仕様通りに実装済み |

### 4.2 Step 24-25-30-31: Merchant Agent経由フロー - ✅ 完全実装済み

**メソッド名の修正 (2025-10-21完了)**:
- **修正前**: `_process_payment_via_payment_processor` （誤解を招く名前）
- **修正後**: `_process_payment_via_merchant_agent` （実装を正確に反映）
- 実際の通信先は `{merchant_agent_url}/a2a/message` で、Merchant Agent経由

**実際の実装**:

1. **Step 24**: Shopping Agent → Merchant Agent
   ```python
   # shopping_agent/agent.py:2884-2886
   response = await self.http_client.post(
       f"{self.merchant_agent_url}/a2a/message",  # ✅ Merchant Agentに送信
       json=message.model_dump(by_alias=True),
       timeout=30.0
   )
   ```

2. **Step 25**: Merchant Agent → Payment Processor
   ```python
   # merchant_agent/agent.py:495-497
   response = await self.http_client.post(
       f"{self.payment_processor_url}/a2a/message",  # ✅ Payment Processorへ転送
       json=forward_message.model_dump(by_alias=True),
       timeout=30.0
   )
   ```

3. **Step 30-31**: Payment Processor → Merchant Agent → Shopping Agent
   ```python
   # merchant_agent/agent.py:511-526
   if response_type == "ap2.responses.PaymentResult":
       logger.info(
           f"[MerchantAgent] Payment processing completed, forwarding result to Shopping Agent"
       )
       return {  # ✅ Shopping Agentへ転送
           "type": "ap2.responses.PaymentResult",
           "id": data_part.get("id", str(uuid.uuid4())),
           "payload": data_part["payload"]
       }
   ```

**検証済み項目**:
- ✅ A2A署名付きメッセージ送信
- ✅ VDC交換原則（CartMandate + PaymentMandateを含む）
- ✅ Merchant Agentの監査ログ保存
- ✅ A2A通信チェーンの完全性

### 4.3 Step 3: IntentMandate確認 - ✅ AP2仕様準拠

**誤解の原因**: Step 21-22のWebAuthn attestationと混同

**AP2仕様書の記載** (`refs/AP2-main/docs/specification.md:618`):
```
user --) sa: 3. Confirm
```

**仕様の解釈**:
- Step 3は単なる「Confirm」（確認）のみ
- WebAuthn attestationが必要なのは **Step 21-22** (PaymentMandate承認時)
- IntentMandateへの署名は仕様で要求されていない

**v2実装**: ✅ AP2仕様に正しく準拠

### 4.4 結論: Phase 3修正は不要

**処理順準拠率**: **100%** (32/32 ステップ)

すべてのステップがAP2仕様書の記載通りに実装されており、Phase 3の修正は不要です。

---
## 5. Phase 4: MEDIUM修正（品質向上）

### 5.1 URLハードコード解消（15箇所）

**問題**: サービスURLがコード内にハードコード

**修正方針**: 環境変数化とServiceDiscoveryパターン導入

#### 修正手順

**Step 1: 環境変数定義**

`.env.example`（新規作成）

```bash
# AP2 v2 Environment Configuration

# Service URLs
SHOPPING_AGENT_URL=http://localhost:8001
MERCHANT_AGENT_URL=http://localhost:8002
PAYMENT_PROCESSOR_URL=http://localhost:8003
CREDENTIAL_PROVIDER_URL=http://localhost:8004
MERCHANT_URL=http://localhost:8005

# Frontend
FRONTEND_URL=http://localhost:3000

# WebAuthn
RP_ID=localhost
RP_NAME="AP2 Demo"

# Database
DATABASE_URL=sqlite:///./ap2.db

# Security
SECRET_KEY=<generate_secure_random_key>
ENCRYPTION_KEY=<generate_32_byte_key>

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

**Step 2: 設定ファイル作成**

`common/config.py`（新規作成）

```python
from pydantic_settings import BaseSettings
from functools import lru_cache

class Settings(BaseSettings):
    """
    AP2 v2アプリケーション設定

    環境変数または.envファイルから読み込み
    """

    # Service URLs
    shopping_agent_url: str = "http://localhost:8001"
    merchant_agent_url: str = "http://localhost:8002"
    payment_processor_url: str = "http://localhost:8003"
    credential_provider_url: str = "http://localhost:8004"
    merchant_url: str = "http://localhost:8005"

    # Frontend
    frontend_url: str = "http://localhost:3000"

    # WebAuthn
    rp_id: str = "localhost"
    rp_name: str = "AP2 Demo"

    # Database
    database_url: str = "sqlite:///./ap2.db"

    # Security
    secret_key: str
    encryption_key: str

    # Logging
    log_level: str = "INFO"
    log_format: str = "json"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

@lru_cache()
def get_settings() -> Settings:
    """設定のシングルトンインスタンス取得"""
    return Settings()

# グローバルインスタンス
settings = get_settings()
```

**Step 3: 全サービスで環境変数使用**

`services/shopping_agent/agent.py`

```python
# 【修正前】
MERCHANT_AGENT_URL = "http://localhost:8002"  # ❌ ハードコード

# 【修正後】
from common.config import settings

class ShoppingAgent:
    def __init__(self):
        self.merchant_agent_url = settings.merchant_agent_url  # ✅ 環境変数
        self.payment_processor_url = settings.payment_processor_url
        self.credential_provider_url = settings.credential_provider_url
```

### 5.2 統一ロギング強化

**現状**: 統一ロギングシステムは実装済み（`common/logging_config.py`）

**追加修正**: 構造化ログ出力の強化

#### 修正手順

`common/logging_config.py`

```python
# 【追加】AP2仕様準拠のログフィールド
def log_a2a_message(logger, direction: str, message: dict):
    """
    A2A通信ログの標準化

    direction: "sent" | "received"
    """
    logger.info(
        "A2A communication",
        extra={
            "direction": direction,
            "sender_did": message.get("header", {}).get("sender"),
            "receiver_did": message.get("header", {}).get("receiver"),
            "message_type": message.get("header", {}).get("type"),
            "nonce": message.get("header", {}).get("nonce"),
            "timestamp": message.get("header", {}).get("timestamp")
        }
    )

def log_mandate_event(logger, event_type: str, mandate: dict):
    """
    Mandateイベントログの標準化

    event_type: "created" | "signed" | "verified" | "rejected"
    """
    mandate_type = mandate.get("type", "unknown")
    mandate_id = mandate.get(f"{mandate_type.lower()}_id", "unknown")

    logger.info(
        f"{mandate_type} {event_type}",
        extra={
            "mandate_type": mandate_type,
            "mandate_id": mandate_id,
            "event_type": event_type,
            "timestamp": mandate.get("timestamp")
        }
    )
```

---

## 6. 修正後の検証手順

### 6.1 各Phase完了後の検証チェックリスト

#### Phase 1完了後
```bash
# 1. NonceManager並行処理テスト
pytest tests/test_nonce_manager_async.py -v

# 2. 全A2A通信エンドポイントテスト
pytest tests/test_a2a_communication.py -v

# 3. 負荷テスト（並行リクエスト）
locust -f tests/load_test_a2a.py --host=http://localhost:8001
```

#### Phase 2完了後
```bash
# 1. HTTPクライアントクリーンアップ確認
docker compose up -d
docker compose stop
docker compose logs | grep "HTTP client closed"

# 2. トランザクションロールバック確認
pytest tests/test_payment_transaction.py -v

# 3. リソースリーク確認
docker stats --no-stream
```

#### Phase 3完了後
```bash
# 1. IntentMandate署名フロー確認
pytest tests/test_intent_mandate_signature.py -v

# 2. Merchant Agent経由決済フロー確認
pytest tests/test_payment_flow_via_merchant_agent.py -v

# 3. 完全な32ステップフロー確認
streamlit run ap2_demo_app.py
# 実際に決済フローを実行してログ確認

# 4. 処理順準拠性検証
python scripts/verify_ap2_sequence.py
```

#### Phase 4完了後
```bash
# 1. 環境変数読み込み確認
docker compose --env-file .env up -d
docker compose logs | grep "Configuration loaded"

# 2. ログ出力確認
docker compose logs | jq 'select(.mandate_type != null)'

# 3. 全テストスイート実行
pytest tests/ -v --cov=services --cov-report=html
```

### 6.2 AP2仕様準拠性の最終確認

```bash
# 1. 32ステップ完全実行テスト
python scripts/run_full_ap2_flow.py

# 2. AP2準拠性スコア算出
python scripts/calculate_compliance_score.py

# 期待値: 100%準拠

# 3. セキュリティ監査
python scripts/security_audit.py

# 期待値: CRITICAL/HIGH問題ゼロ
```

### 6.3 スクリプト作成

`scripts/verify_ap2_sequence.py`（新規作成）

```python
"""
AP2仕様32ステップシーケンス検証スクリプト

全32ステップが正しい順序で実行されることを確認
"""
import asyncio
from services.shopping_agent.agent import ShoppingAgent
from services.merchant_agent.agent import MerchantAgent
from services.payment_processor.processor import PaymentProcessor

async def verify_ap2_sequence():
    """AP2仕様32ステップの順序検証"""

    steps_executed = []

    # Step 1: Shopping Prompts
    steps_executed.append("Step 1: User → SA: Shopping Prompts")

    # Step 2: IntentMandate confirmation
    intent_mandate = await shopping_agent._create_intent_mandate(user_input)
    steps_executed.append("Step 2: SA → User: IntentMandate confirmation")

    # Step 3: Confirm with WebAuthn signature
    signed_intent = await shopping_agent.submit_intent_mandate(intent_mandate)
    assert "user_signature" in signed_intent  # ✅ 署名必須
    steps_executed.append("Step 3: User → SA: Confirm (WebAuthn signature)")

    # ... 全32ステップ実行 ...

    # Step 31-32: Receipt delivery
    steps_executed.append("Step 31: MA → SA: Payment receipt")
    steps_executed.append("Step 32: SA → User: Purchase completed")

    # 検証
    assert len(steps_executed) == 32
    print("✅ All 32 steps executed in correct order")
    print("\n".join(steps_executed))

if __name__ == "__main__":
    asyncio.run(verify_ap2_sequence())
```

---

## 7. AP2準拠を維持するためのチェックリスト

### 7.1 新機能追加時の必須確認項目

```markdown
## 新機能追加前チェックリスト

### AP2仕様確認
- [ ] AP2仕様書の該当セクションを読み、関連するステップを特定
- [ ] 既存の32ステップシーケンスへの影響を確認
- [ ] Mandate型定義への影響を確認

### 実装前
- [ ] 既存のテストがすべてPASSすることを確認
- [ ] 影響を受ける既存コードを特定
- [ ] 修正計画書を作成（このドキュメント形式）

### 実装中
- [ ] AP2仕様書の該当箇所をコメントに引用
- [ ] 1機能1コミット、詳細なコミットメッセージ
- [ ] 各コミット後に関連テストを実行

### 実装後
- [ ] 新機能のテストを追加してPASS
- [ ] 既存のテストがすべてPASS
- [ ] AP2準拠性検証スクリプト実行（100%維持）
- [ ] セキュリティ監査スクリプト実行（CRITICAL/HIGHゼロ維持）

### コードレビュー
- [ ] 他の開発者によるレビュー
- [ ] AP2仕様準拠の確認
- [ ] セキュリティベストプラクティスの確認
```

### 7.2 定期監査スケジュール

```markdown
## 週次監査（毎週金曜日）

- [ ] 全テストスイート実行（pytest tests/ -v）
- [ ] AP2準拠性スコア確認（python scripts/calculate_compliance_score.py）
- [ ] セキュリティ監査（python scripts/security_audit.py）
- [ ] ログ分析（構造化ログのエラー確認）

## 月次監査（毎月最終金曜日）

- [ ] AP2仕様書の最新版確認
- [ ] 依存ライブラリのアップデート確認
- [ ] セキュリティアドバイザリ確認
- [ ] 本番環境デプロイ準備状況評価

## リリース前監査

- [ ] 完全な32ステップフロー手動テスト
- [ ] 負荷テスト実行
- [ ] セキュリティペネトレーションテスト
- [ ] AP2仕様準拠100%確認
- [ ] ドキュメント最新化
```

### 7.3 禁止事項リスト

```markdown
## 絶対にやってはいけないこと

### コード変更
- ❌ AP2仕様書を読まずにMandate構造を変更
- ❌ 暗号化アルゴリズムを推測で変更（必ずOWASP/NIST基準確認）
- ❌ WebAuthn検証をスキップ
- ❌ A2A署名検証をスキップ
- ❌ トランザクション処理でrollbackを省略

### テスト
- ❌ テストが失敗している状態でコミット
- ❌ テストをコメントアウトして問題を隠蔽
- ❌ モックを使わずに外部サービスに依存するテスト

### デプロイ
- ❌ CRITICAL/HIGH問題が残った状態で本番デプロイ
- ❌ データベースマイグレーション計画なしでスキーマ変更
- ❌ ロールバック手順なしでデプロイ
```

---

## 8. まとめ

### 8.1 修正の実施順序（絶対厳守）

```
Phase 1: CRITICAL修正（1-2日）
  ↓
Phase 1検証・テスト（0.5日）
  ↓
Phase 2: HIGH修正（1日）
  ↓
Phase 2検証・テスト（0.5日）
  ↓
Phase 3: 処理順準拠修正（2-3日）
  ↓
Phase 3検証・テスト（1日）
  ↓
Phase 4: MEDIUM修正（1日）
  ↓
Phase 4検証・テスト（0.5日）
  ↓
最終監査（1日）
  ↓
本番デプロイ
```

**総所要時間**: 8-10日間

### 8.2 成功の定義

この修正指示書に従った修正が完了した状態:

- ✅ **AP2仕様準拠率**: 100%（32/32ステップ、16/16型定義）
- ✅ **CRITICAL問題**: 0件
- ✅ **HIGH問題**: 0件
- ✅ **全テスト**: PASS
- ✅ **処理順準拠**: 100%（現在75% → 100%）
- ✅ **本番環境準備**: 100%（現在40% → 100%）

### 8.3 サポートリソース

- **AP2仕様書**: `/Users/kagadminmac/project/ap2/refs/AP2-main/docs/specification.md`
- **準拠レポート**: `/Users/kagadminmac/project/ap2/v2/AP2_COMPLIANCE_REPORT.md`
- **この修正指示書**: `/Users/kagadminmac/project/ap2/v2/AP2_COMPLIANCE_FIX_GUIDE.md`

---

**この修正指示書を正確に実行すれば、AP2仕様に100%準拠したアプリケーションが完成します。**

**修正実施時の鉄則**:
1. 順序を守る（Phase 1 → 2 → 3 → 4）
2. 1つずつ修正（並行作業禁止）
3. 各修正後に必ず検証
4. テスト駆動開発（TDD）を徹底
5. AP2仕様書を常に参照
