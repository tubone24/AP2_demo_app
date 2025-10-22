# AP2 Shopping Agent - AI統合実装ガイド（完全版）

## 概要

このドキュメントは、AP2（Agent Payments Protocol）準拠のShopping AgentにLangGraph + MCPを統合し、AIエージェント化した実装の詳細を説明します。

## 実装方針

### 最優先事項: AP2仕様の完全準拠

**重要**: すべての実装はAP2仕様（refs/AP2-main/docs/specification.md）に完全準拠しています。

- 既存の`IntentMandate`型（`v2/common/mandate_types.py`）を使用
- A2A通信基盤を維持
- 署名フロー（Passkey署名）は変更なし
- Human-Presentフローの実装

### AI統合の目的

従来のShopping Agentは固定文言で動作していましたが、AI統合により以下が可能になります：

1. **自然言語理解**: ユーザーの購買意図を自然言語から抽出
2. **対話的情報収集**: ユーザーとの対話で必須情報（インテント・最大金額）とオプション情報（カテゴリー・ブランド）を段階的に収集
3. **Intent Mandate生成**: LLMがユーザー入力を構造化データ化
4. **柔軟な対話**: 固定シナリオではなく、ユーザー意図に応じた応答

## アーキテクチャ

```
User Input (自然言語)
    ↓
[Shopping Agent - /chat/stream endpoint]
    ↓
[_create_intent_mandate method]
    ↓
[LangGraph Agent] ← 新規実装
    ├→ LLM (DMR endpoint): インテント抽出
    └→ Intent Extractor: 構造化データ生成
    ↓
[IntentMandate (Pydantic model)] ← AP2仕様準拠
    ├→ natural_language_description: LLM生成
    ├→ user_cart_confirmation_required: true
    ├→ intent_expiry: 自動生成（24時間後）
    └→ merchants, skus: LLM抽出（オプション）
    ↓
[Passkey署名フロー] ← 既存実装（変更なし）
    ↓
[Database保存 & A2A通信] ← 既存基盤（変更なし）
```

## 新規実装ファイル

### 1. `langgraph_conversation.py` - LangGraph対話エージェント（メイン）

**役割**: ユーザーとの対話で必須情報（インテント・最大金額）とオプション情報（カテゴリー・ブランド）を段階的に収集

**主要クラス**:
- `LangGraphConversationAgent`: 対話ベースの情報収集エージェント
  - `_build_graph()`: 対話フローの定義
  - `_extract_info_node()`: LLMでユーザー入力から情報抽出
  - `_check_completeness_node()`: 必須情報が揃ったか確認
  - `_generate_question_node()`: 不足情報を質問
  - `process_user_input()`: 外部呼び出しAPI

**対話フロー**:
```
初回: "何をお探しですか？"
↓ ユーザー入力（例: "赤いシューズが欲しい、3万円以内"）
↓ LLMで抽出
  - intent: "赤いシューズが欲しい"
  - max_amount: 30000
  - categories: []
  - brands: []
↓ 不足情報チェック
↓ すべて揃ったら: "購入条件が確認できました。配送先を入力してください。"
```

### 2. `langgraph_agent.py` - LangGraphエージェント（Intent Mandate生成用）

**役割**: 収集した情報からIntentMandate用データを最終生成（現在は未使用、将来的な拡張用）

**主要クラス**:
- `LangGraphIntentAgent`: LangGraphベースのインテント抽出
  - `_build_graph()`: LangGraphのフロー定義
  - `_extract_intent_node()`: LLMでインテント抽出
  - `_format_intent_node()`: IntentMandate形式に変換
  - `extract_intent_from_prompt()`: 外部呼び出しAPI

**AP2準拠のポイント**:
```python
# LLMプロンプトでAP2仕様のフィールドを明示
system_prompt = """
必須フィールド:
- natural_language_description: ユーザーの意図の自然言語説明（1-2文）
- user_cart_confirmation_required: カート確認が必要か（通常はtrue）

オプションフィールド:
- merchants: 許可されたMerchantのリスト
- skus: 特定のSKUリスト
- requires_refundability: 返金可能性が必要か
"""
```

### 2. `mcp_tools.py` - MCPツール

**役割**: LangGraphから呼び出し可能な補助ツール群

**提供ツール**:
- `validate_merchant`: Merchant検証
- `estimate_price_range`: 価格帯推定
- `suggest_skus`: SKU候補提案
- `calculate_intent_expiry`: 有効期限計算

**注**: 現在の実装ではMCPツールは独立した関数群として実装されていますが、将来的にLangGraphのツールチェーンに統合可能です。

### 3. `agent.py`の変更点

**変更箇所**:

1. **インポート追加**（行50-51）:
```python
# LangGraph統合（AI化）
from langgraph_agent import get_langgraph_agent
```

2. **`__init__`でLangGraphエージェント初期化**（行116-122）:
```python
# LangGraphエージェント（AIによるインテント抽出）
try:
    self.langgraph_agent = get_langgraph_agent()
    logger.info(f"[{self.agent_name}] LangGraph agent initialized successfully")
except Exception as e:
    logger.warning(f"[{self.agent_name}] LangGraph agent initialization failed (will use fallback): {e}")
    self.langgraph_agent = None
```

3. **`_create_intent_mandate`メソッドをAI対応版に置き換え**（行2471-2593）:
   - LangGraphでインテント抽出を試行
   - 失敗時は従来方式にフォールバック（`_create_intent_mandate_fallback`）
   - AP2仕様準拠のIntentMandate構造を維持

## 環境変数設定

### `.env`ファイルに以下を追加:

```bash
# AI Agent設定（LangGraph + LLM）
DMR_API_URL=http://host.docker.internal:11434/v1
DMR_MODEL=llama3.2
DMR_API_KEY=none
```

### 環境別の設定例:

#### ローカルOllama:
```bash
DMR_API_URL=http://host.docker.internal:11434/v1
DMR_MODEL=llama3.2
DMR_API_KEY=none
```

#### リモートLLM（OpenAI互換）:
```bash
DMR_API_URL=https://your-llm-endpoint.com/v1
DMR_MODEL=gpt-4
DMR_API_KEY=your_api_key_here
```

## 依存関係

### `pyproject.toml`に追加済み:

```toml
# AI Agent Integration
"langgraph>=1.0.1",
"langchain-core>=0.3.0",
"langchain-openai>=0.2.0",
"mcp>=1.0.0",
```

## 使用方法

### 1. 環境構築

```bash
cd v2
cp .env.example .env
# .envファイルでDMR_API_URL等を設定

# 依存関係インストール
uv sync
```

### 2. Ollamaのセットアップ（ローカルLLM使用の場合）

```bash
# Ollamaインストール（macOS）
brew install ollama

# モデルダウンロード
ollama pull llama3.2

# Ollamaサーバー起動
ollama serve
```

### 3. Docker Composeで起動

```bash
docker compose up --build
```

### 4. テスト

フロントエンド（http://localhost:3000）から以下のようなメッセージを送信:

- 「赤いバスケットボールシューズを3万円以内で購入したい」
- 「むぎぼーのグッズが欲しい」
- 「スマートフォンを5万円以内で探して」

LangGraphが自然言語を解析し、IntentMandateを生成します。

## AP2仕様準拠の確認ポイント

### ✅ IntentMandateの構造

refs/AP2-main/src/ap2/types/mandate.py:32-77 に準拠:

```python
{
  "natural_language_description": str,  # 必須
  "user_cart_confirmation_required": bool,  # 必須
  "merchants": Optional[List[str]],  # オプション
  "skus": Optional[List[str]],  # オプション
  "requires_refundability": Optional[bool],  # オプション
  "intent_expiry": str  # 必須（ISO 8601形式）
}
```

### ✅ 署名フロー

- IntentMandateはユーザーPasskey（WebAuthn）で署名
- サーバー側（Shopping Agent）は署名しない
- フロントエンドが`/intent/challenge`→`/intent/submit`を呼び出し

### ✅ A2A通信

- IntentMandateはA2Aメッセージとして`Merchant Agent`に送信
- 既存の`a2a_handler.create_response_message()`を使用

## フォールバック機能

LangGraphが利用できない場合（LLMエンドポイントエラー等）、自動的に従来の固定文言方式にフォールバックします。

```python
# フォールバック判定ログ例
[ShoppingAgent] LangGraph agent initialization failed (will use fallback): ...
[ShoppingAgent] IntentMandate created (fallback mode): id=intent_abc123
```

## トラブルシューティング

### LangGraphエージェントが初期化されない

**原因**: DMR endpoint（LLM）に接続できない

**確認**:
```bash
# Ollamaが起動しているか確認
curl http://localhost:11434/v1/models

# Docker内からアクセス可能か確認
docker compose exec shopping_agent curl http://host.docker.internal:11434/v1/models
```

**対処**:
- Ollamaサーバーが起動しているか確認
- `.env`の`DMR_API_URL`が正しいか確認
- フォールバックモードで動作するため、機能自体は使用可能

### IntentMandate生成エラー

**原因**: LLMの出力がJSON形式でない

**確認**:
```bash
# ログを確認
docker compose logs shopping_agent | grep "LLM raw output"
```

**対処**:
- LLMモデルを変更（`DMR_MODEL`）
- プロンプトを調整（`langgraph_agent.py`の`system_prompt`）

## 今後の拡張

### 1. MCPツールのLangGraph統合

現在のMCPツールをLangGraphのツールチェーンに統合:

```python
from langgraph.prebuilt import ToolNode

tools = [validate_merchant, estimate_price_range, suggest_skus]
tool_node = ToolNode(tools)
```

### 2. Human-Not-Presentフローへの対応

- Intent Mandateへのユーザー署名追加
- より厳格な制約条件のサポート

### 3. マルチターン対話

- LangGraphのステート管理を活用
- ユーザーとの対話で段階的にIntent Mandateを洗練

## 参照

- AP2公式仕様: refs/AP2-main/docs/specification.md
- AP2型定義: refs/AP2-main/src/ap2/types/mandate.py
- LangGraph公式: https://langgraph.com/
- MCP仕様: https://modelcontextprotocol.io/
