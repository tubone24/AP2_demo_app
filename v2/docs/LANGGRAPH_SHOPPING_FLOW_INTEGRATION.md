# LangGraph Shopping Flow 統合ガイド

## 概要

`_generate_fixed_response`関数（約2000行）をLangGraph StateGraphでリファクタリングした新実装が完成しました。

## 実装内容

### 新ファイル

**`v2/services/shopping_agent/langgraph_shopping_flow.py`** (1656行)
- 12ノード構成のLangGraph StateGraph実装
- AP2完全準拠のビジネスロジック
- 既存メソッドの再利用（`_create_intent_mandate`, `_search_products_via_merchant_agent`, etc.）

### 実装済みノード

1. **greeting_node** - セッションリセット、初回挨拶
2. **collect_intent_node** - LangGraph会話エージェントでIntent/金額/カテゴリー/ブランド収集
3. **collect_shipping_node** - 配送先住所入力（AP2 ContactAddress形式）
4. **fetch_carts_node** - Merchant AgentへのA2A通信でカート候補取得
5. **select_cart_node** - カート選択、Merchant署名の暗号学的検証
6. **select_credential_provider_node** - Credential Provider選択、支払い方法取得
7. **select_payment_method_node** - 支払い方法選択、トークン化、PaymentMandate作成
8. **step_up_auth_node** - Step-up認証（3DS 2.0）リダイレクト
9. **webauthn_auth_node** - WebAuthn/Passkey認証待機
10. **execute_payment_node** - Payment Processor経由で決済実行
11. **completed_node** - 完了メッセージ表示
12. **error_node** - エラーメッセージ表示、リセット案内

### Conditional Edges

各ノードから`next_step`フィールドを参照して動的にルーティング：

```python
workflow.add_conditional_edges(
    "select_payment_method",
    route_from_select_payment_method,
    {
        "step_up_auth": "step_up_auth",  # Step-up必要時
        "webauthn_auth": "webauthn_auth",  # 不要時
        "error": "error",
        END: END
    }
)
```

## 統合手順

### ステップ1: ShoppingAgentクラスへの組み込み

`v2/services/shopping_agent/agent.py`を編集：

```python
from services.shopping_agent.langgraph_shopping_flow import create_shopping_flow_graph

class ShoppingAgent(BaseAgent):
    def __init__(self, ...):
        # ... 既存の初期化 ...

        # LangGraphショッピングフローを作成
        self.shopping_flow_graph = create_shopping_flow_graph(self)

        logger.info(f"[{self.agent_name}] LangGraph shopping flow initialized")
```

### ステップ2: 新しいストリーミングメソッド追加

```python
async def _generate_fixed_response_langgraph(
    self,
    user_input: str,
    session: Dict[str, Any],
    session_id: str
) -> AsyncGenerator[StreamEvent, None]:
    """
    LangGraph版の応答生成（ストリーミング）

    既存の_generate_fixed_responseと同じインターフェースを維持しつつ、
    内部実装をLangGraph StateGraphに置き換え
    """
    # 初期状態
    initial_state = {
        "user_input": user_input,
        "session_id": session_id,
        "session": session,
        "events": [],
        "next_step": None,
        "error": None
    }

    # グラフ実行
    result = await self.shopping_flow_graph.ainvoke(initial_state)

    # イベントをストリーミング出力
    for event_dict in result["events"]:
        # agent_text_chunkは文字単位で遅延を挿入
        if event_dict.get("type") == "agent_text_chunk":
            yield StreamEvent(**event_dict)
            await asyncio.sleep(0.02)  # 20ms遅延
        else:
            yield StreamEvent(**event_dict)

    # セッション更新
    await self._update_session(session_id, result["session"])
```

### ステップ3: エンドポイントでの切り替え

環境変数`USE_LANGGRAPH_FLOW=true`で切り替え可能に：

```python
@self.app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """
    POST /chat/stream - ストリーミングチャットエンドポイント
    """
    import os
    use_langgraph = os.getenv("USE_LANGGRAPH_FLOW", "false").lower() == "true"

    if use_langgraph:
        # LangGraph版を使用
        response_generator = self._generate_fixed_response_langgraph(
            user_input,
            session,
            session_id
        )
    else:
        # 既存実装を使用
        response_generator = self._generate_fixed_response(
            user_input,
            session,
            session_id
        )

    async def event_generator():
        async for event in response_generator:
            yield f"data: {json.dumps(event.model_dump(), ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream"
    )
```

### ステップ4: 環境変数設定

`.env`ファイルに追加：

```bash
# LangGraph Shopping Flow（実験的機能）
USE_LANGGRAPH_FLOW=false  # trueにするとLangGraph版を使用
```

## AP2準拠の確認

### ✅ 署名フロー

- **Merchant署名検証**: `select_cart_node:687-730` - `SignatureManager.verify_mandate_signature`を使用
- **User署名（WebAuthn）**: `select_cart_node:742-746` - signature_request StreamEvent送信
- **IntentMandate/CartMandate/PaymentMandate構造**: 既存メソッドを再利用して一貫性を維持

### ✅ A2A通信

- **IntentMandate送信**: `fetch_carts_node:427-492` - `_search_products_via_merchant_agent`使用
- **CartCandidates受信**: `fetch_carts_node:523-565` - Artifact形式を正しく変換
- **PaymentMandate送信**: `execute_payment_node:1277-1332` - `_process_payment_via_merchant_agent`使用

### ✅ セキュリティ

- **WebAuthn/Passkey認証**: `select_payment_method_node:1055-1069` - challengeベースの認証
- **Step-up認証（3DS 2.0）**: `step_up_auth_node:1079-1207` - Credential Provider連携
- **トークン化**: `select_payment_method_node:962-1025` - `_tokenize_payment_method`使用

### ✅ リスク評価

- **PaymentMandate作成時に実行**: `select_payment_method_node:1044` - `_create_payment_mandate`内でリスク評価を実施
- **既存ロジックと同一**: `agent.py:4018-4050`のリスク評価ロジックをそのまま使用

## テスト計画

### 単体テスト

各ノード関数を個別にテスト：

```python
# tests/test_langgraph_shopping_flow.py

async def test_greeting_node():
    state = {
        "user_input": "こんにちは",
        "session_id": "test_session",
        "session": {"step": "initial"},
        "events": [],
        "next_step": None,
        "error": None
    }

    result = await greeting_node(state)

    assert result["next_step"] == "collect_intent"
    assert len(result["events"]) > 0
    assert result["events"][0]["type"] == "agent_text"
```

### 統合テスト

フルフローをエンドツーエンドでテスト：

```python
async def test_full_shopping_flow():
    """
    Intent収集 → カート取得 → カート選択 → 決済実行の全フロー
    """
    # テストデータ準備
    # グラフ実行
    # 各ステップの状態遷移を検証
    pass
```

### 比較テスト

既存実装とLangGraph実装の出力を比較：

```python
async def test_output_parity():
    """
    既存実装とLangGraph実装が同じStreamEventを出力することを確認
    """
    # 同じ入力で両方実行
    # イベントの順序と内容を比較
    pass
```

## メリット

### 1. 可読性向上

- 各ステップが独立した関数として明確に定義
- 条件分岐がConditional Edgesで可視化
- 2000行の関数 → 12個の100-200行の関数

### 2. 保守性向上

- ステップの追加・変更が容易
- バグの特定が迅速（ノード単位でデバッグ可能）
- ビジネスロジックの変更影響範囲が限定的

### 3. テスタビリティ向上

- 各ノードを個別にユニットテスト可能
- モックを使った依存関係の分離が容易
- エッジケースの網羅的なテストが可能

### 4. 可視化

- LangGraphの可視化ツールでフロー全体を確認可能
- デバッグ時にステート遷移を追跡可能
- ドキュメント生成が自動化可能

### 5. 並列実行（将来的な拡張）

- 独立したステップを並列実行可能
- パフォーマンス最適化の余地

## 制約事項

### 現在の実装

1. **外部API待機**: WebAuthn認証、Step-up認証は外部APIが呼ばれるまで`END`で終了
   - これは既存実装と同じ挙動
   - 外部APIが`POST /cart/submit-signature`などを呼び出すと新しいフローが開始される

2. **セッションデータ構造**: 既存のsession辞書をそのまま使用
   - 後方互換性のため変更なし
   - 将来的にStateGraphのキーに移行可能

3. **ストリーミング遅延**: `agent_text_chunk`の文字単位遅延は呼び出し側で実装
   - ノード内では遅延なしでイベントを蓄積
   - `_generate_fixed_response_langgraph`でストリーミング時に遅延挿入

## 次のステップ

1. ✅ **統合実装**: ShoppingAgentクラスにLangGraphフローを組み込む
2. **テスト実装**: 単体テスト、統合テスト、比較テストを作成
3. ✅ **本番検証**: `USE_LANGGRAPH_FLOW=true`で実環境テスト
4. **パフォーマンス測定**: 既存実装との比較
5. **ドキュメント更新**: ユーザーガイド、開発者ガイド

## 完全移行完了（2025-10-26）

新しいLangGraph StateGraph実装への完全移行が完了しました。

### 削除された旧実装

以下の古いLangGraph実装ファイルを削除しました：

1. `langgraph_agent.py` - Intent抽出用LangGraphエージェント
2. `langgraph_conversation.py` - 対話エージェント
3. `langgraph_shopping.py` - フルフローShopping Engine

### 変更内容

1. **`agent.py`の修正**:
   - 古いLangGraph初期化コードを削除
   - `self.langgraph_agent = None`
   - `self.conversation_agent = None`
   - `self.langgraph_shopping_agent = None`
   - 古いimport文を削除

2. **`.env.example`の更新**:
   - `USE_LANGGRAPH_FLOW=true`（標準実装）
   - コメント更新：新しいStateGraphが推奨・標準実装であることを明記

3. **Dockerイメージの再ビルド**:
   - 古いファイルを完全に削除
   - 新しい`langgraph_shopping_flow.py`のみが含まれる

### 確認事項

- ✅ コンテナログに「Old LangGraph implementations are deprecated」が表示
- ✅ 新しいStateGraphが正常に初期化（12ノード構成）
- ✅ 古いLangGraphの初期化メッセージが消えた
- ✅ コンテナ内に`langgraph_shopping_flow.py`のみが存在

### 追加修正（2025-10-26）

**問題**: `conversation_agent`への参照が`collect_intent_node`に残っており、エラーメッセージ「LangGraph会話エージェントが初期化されていません」が表示されていた。

**修正内容**:
1. `langgraph_shopping_flow.py`の`collect_intent_node`を簡略化
2. 古い`conversation_agent`への依存を完全に削除
3. シンプルなIntent収集ロジックに変更：
   - ユーザー入力からintentと金額制約を正規表現で抽出
   - `_create_intent_mandate`メソッドを呼び出し（AP2完全準拠、自動的にフォールバック処理が実行される）
   - IntentMandate作成後、すぐに配送先入力フォームを表示

**AP2準拠の維持**:
- `_create_intent_mandate`メソッドを使用してIntentMandateを作成
- フォールバック処理により、LLMなしでも動作
- natural_language_descriptionには金額制約を含めて保存

## 参考資料

- [設計書](./LANGGRAPH_SHOPPING_FLOW_DESIGN.md)
- [LangGraph公式ドキュメント](https://langchain-ai.github.io/langgraph/)
- [AP2仕様書](https://ap2-protocol.org/specification/)
