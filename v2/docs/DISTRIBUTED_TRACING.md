# AP2 分散トレーシング（OpenTelemetry + Jaeger）

## 概要

v2/のAP2デモアプリは、OpenTelemetryを使用したA2A通信の分散トレーシングに対応しています。これにより、マルチエージェント間の通信フローを可視化し、パフォーマンスボトルネックの特定やデバッグが容易になります。

参考記事: [OpenTelemetryでA2A通信を分散トレーシング](https://zenn.dev/kimitsu/articles/otel-and-a2a)

## アーキテクチャ

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│ Shopping Agent  │─────▶│ Merchant Agent  │─────▶│   Merchant      │
│   (8000)        │      │   (8001)        │      │   (8002)        │
└─────────────────┘      └─────────────────┘      └─────────────────┘
        │                        │                         │
        │                        │                         │
        │         OpenTelemetry OTLP (gRPC/HTTP)          │
        │                        │                         │
        └────────────────────────┼─────────────────────────┘
                                 │
                                 ▼
                        ┌─────────────────┐
                        │     Jaeger      │
                        │  (All-in-One)   │
                        │                 │
                        │  UI: 16686      │
                        │  OTLP: 4317/8   │
                        └─────────────────┘
```

### コンポーネント

1. **OpenTelemetry計装**
   - **httpx**: クライアント側の自動計装（A2A通信のみトレース）
   - **OTLP Exporter**: トレースデータをJaegerに送信
   - **URLフィルタリング**: インフラ通信（DMR、MeliSearch等）を除外

   **注意**: FastAPI計装は無効化されています（Langfuseとの共存のため）。
   サーバー側のHTTPエンドポイントはトレースされず、エージェント間のhttpxクライアント通信のみがトレースされます。

2. **Jaeger**
   - トレース収集・保存
   - Web UI（http://localhost:16686）でトレースを可視化

3. **Langfuse**
   - LLM呼び出しとLangGraphの実行をトレース
   - OpenTelemetryと共存（別々のトレーシングシステム）

## セットアップ

### 1. 依存関係のインストール

依存関係はすでに`pyproject.toml`に追加されています。

```bash
cd /Users/kagadminmac/project/ap2/v2

# uvを使用している場合
uv sync

# pipを使用している場合
pip install -e .
```

### 2. 環境変数の設定

`.env`ファイルを作成（または`.env.example`からコピー）:

```bash
cp .env.example .env
```

OpenTelemetry設定（`.env`）:

```bash
# OpenTelemetry分散トレーシングの有効化
OTEL_ENABLED=true

# OTLPエクスポーターのエンドポイント（Docker Compose環境）
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317

# 非セキュア接続の許可（開発環境）
OTEL_EXPORTER_OTLP_INSECURE=true
```

### 3. Docker Composeで起動

```bash
cd /Users/kagadminmac/project/ap2/v2

# すべてのサービス（Jaeger含む）を起動
docker compose up -d

# ログを確認
docker compose logs -f shopping_agent merchant_agent merchant
```

### 4. Jaeger UIにアクセス

ブラウザで以下のURLを開く:

```
http://localhost:16686
```

## 使い方

### トレースの確認

1. **サービス選択**: Jaeger UIで「Service」ドロップダウンから以下を選択
   - `shopping_agent`
   - `merchant_agent`
   - `merchant`
   - `credential_provider`
   - `payment_processor`

2. **トレース検索**: 「Find Traces」をクリック

3. **トレース詳細**: 個別のトレースをクリックして、スパンのツリー構造を確認

### サンプルフロー

以下のような分散トレースが確認できます（httpxクライアント通信のみ）:

```
Trace: A2A Communication Flow
│
├─ shopping_agent → merchant_agent
│  └─ httpx: POST http://merchant_agent:8001/a2a/message (IntentMandate)
│
├─ merchant_agent → merchant
│  └─ httpx: POST http://merchant:8002/a2a/message (CartMandate署名要求)
│
├─ shopping_agent → credential_provider
│  └─ httpx: POST http://credential_provider:8003/a2a/message (PaymentMandate検証)
│
└─ shopping_agent → payment_processor
   └─ httpx: POST http://payment_processor:8004/a2a/message (決済実行)
```

**注意**: FastAPI計装が無効化されているため、各エージェントのHTTPエンドポイント（`POST /a2a/message`等）はトレースに表示されません。
エージェント間のhttpxクライアント通信のみがJaegerに記録されます。

### フィルタリングされる通信

以下のインフラ通信はトレースから除外されます（Langfuseにも記録されません）:

- **DMR (Docker Model Runner)**: `http://host.docker.internal:12434/*` - LLM推論エンドポイント
- **MeliSearch**: `http://meilisearch:7700/*`, `http://localhost:7700/*` - 商品検索エンジン
- **localhost**: `http://127.0.0.1:*` - ローカル開発環境

## トラブルシューティング

### トレースが表示されない

1. **環境変数の確認**
   ```bash
   docker compose exec shopping_agent env | grep OTEL
   ```

   以下の値が設定されているか確認:
   - `OTEL_ENABLED=true`
   - `OTEL_SERVICE_NAME=shopping_agent`
   - `OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317`

2. **Jaegerの起動確認**
   ```bash
   docker compose ps jaeger
   ```

3. **ログの確認**
   ```bash
   docker compose logs shopping_agent | grep Telemetry
   ```

   以下のようなログが出力されているか確認:
   ```
   [Telemetry] Initializing OpenTelemetry:
     Service Name: shopping_agent
     OTLP Endpoint: http://jaeger:4317
   [Telemetry] OpenTelemetry initialized successfully
   [Telemetry] httpx client instrumented successfully (excluding: DMR, MeliSearch)
   ```

   **注意**: FastAPI計装はLangfuseとの共存のため無効化されているので、
   `FastAPI app instrumented successfully`のログは表示されません。

### 接続エラー

**エラー**: `Failed to export traces to Jaeger`

**解決策**:
1. Jaegerが起動しているか確認
   ```bash
   docker compose up -d jaeger
   ```

2. ネットワーク接続を確認
   ```bash
   docker compose exec shopping_agent ping jaeger
   ```

## トレーシングの無効化

開発時にトレーシングが不要な場合は、`.env`で無効化できます:

```bash
OTEL_ENABLED=false
```

または、特定のサービスのみ無効化:

```bash
# docker-compose.ymlで個別に設定
environment:
  - OTEL_ENABLED=false
```

## 実装詳細

### 計装ポイント

1. **httpx自動計装** (`common/base_agent.py`)
   ```python
   from common.telemetry import setup_telemetry, instrument_httpx_client

   # OpenTelemetryの初期化
   service_name = os.getenv("OTEL_SERVICE_NAME", agent_id.split(":")[-1])
   setup_telemetry(service_name)

   # httpxクライアントを計装（A2A通信のみ）
   instrument_httpx_client()
   ```

   **Langfuseとの共存**:
   - FastAPI計装は無効化（サーバー側のHTTPエンドポイントはトレースしない）
   - httpxクライアント計装のみ有効（エージェント間通信をトレース）
   - 既存のTracerProviderにOTLPエクスポーターを追加する方式

2. **URLフィルタリング** (`common/telemetry.py:instrument_httpx_client()`)
   ```python
   excluded_urls = ",".join([
       "http://host.docker.internal:12434/.*",  # DMR (LLM推論)
       "http://localhost:7700/.*",              # MeliSearch (localhost)
       "http://meilisearch:7700/.*",            # MeliSearch (Docker)
       "http://127.0.0.1:.*",                   # localhost
   ])

   HTTPXClientInstrumentor().instrument(
       excluded_urls=excluded_urls
   )
   ```

   インフラ通信をフィルタすることで、A2A通信のみがトレースに記録されます。

3. **カスタムスパン** (オプション)
   ```python
   from common.telemetry import get_tracer

   tracer = get_tracer(__name__)

   with tracer.start_as_current_span("custom_operation") as span:
       span.set_attribute("key", "value")
       # ビジネスロジック
   ```

### 設定モジュール (`common/telemetry.py`)

- `setup_telemetry()`: OpenTelemetryの初期化（既存TracerProviderへのOTLP追加も対応）
- `instrument_httpx_client()`: httpxクライアントの計装（URLフィルタリング付き）
- `get_tracer()`: カスタムスパン作成用トレーサー取得
- `is_telemetry_enabled()`: トレーシング有効/無効の判定

### Langfuseとの共存戦略

1. **TracerProvider共有**: LangChainが初期化したTracerProviderにOTLPエクスポーターを追加
2. **計装の分離**:
   - **Langfuse**: LLM呼び出し、LangGraphの実行をトレース
   - **Jaeger**: A2A通信（httpxクライアント）をトレース
3. **フィルタリング**: インフラ通信を除外してノイズを削減

## 参考資料

- [OpenTelemetry公式ドキュメント](https://opentelemetry.io/docs/languages/python/)
- [Jaeger公式ドキュメント](https://www.jaegertracing.io/docs/)
- [FastAPI計装ガイド](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html)
- [httpx計装ガイド](https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/httpx/httpx.html)
- [参考記事: OpenTelemetryでA2A通信を分散トレーシング](https://zenn.dev/kimitsu/articles/otel-and-a2a)

## 次のステップ

1. **本番環境への適用**: TLS有効化、OTLPエンドポイントの変更
2. **メトリクス追加**: OpenTelemetry Metricsの統合（リクエスト数、レイテンシ等）
3. **ログ統合**: OpenTelemetry Logsとの統合（構造化ログ）
4. **カスタム属性**: ビジネスロジック固有の属性追加（例: mandate_type, transaction_id）
5. **アラート設定**: Jaegerでの異常検知とアラート

## まとめ

本実装により、以下が実現されています：

- ✅ **A2A通信の可視化**: エージェント間のhttpx通信をJaegerでトレース
- ✅ **Langfuseとの共存**: LLMトレーシングと分散トレーシングの両立
- ✅ **ノイズ削減**: DMR、MeliSearchなどのインフラ通信をフィルタリング
- ✅ **開発効率向上**: 分散システムのデバッグが容易に

参考記事（https://zenn.dev/kimitsu/articles/otel-and-a2a）で紹介されている
A2A通信の分散トレーシングが、Langfuseとの共存を保ちながら実装されています。
