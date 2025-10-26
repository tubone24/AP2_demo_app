# LangGraph Shopping Flow リファクタリング設計書

## 目的

`_generate_fixed_response`関数（約2000行）をLangGraphのベストプラクティスに従ってリファクタリングし、以下を実現：

1. **可読性向上**: 各会話ステップを独立したノードに分離
2. **保守性向上**: ステップの追加・変更が容易
3. **可視化**: LangGraphの可視化ツールでフロー全体を確認可能
4. **AP2完全準拠**: ビジネスロジック・署名フロー・A2A通信を一切変更しない

## 設計原則

### 優先順位

**最優先: AP2完全準拠**
- 署名フロー（Merchant署名→User署名）を完全維持
- A2A通信プロトコルを変更しない
- WebAuthn/Passkey認証フローを維持
- IntentMandate/CartMandate/PaymentMandateの構造を維持
- リスク評価の統合を維持

**第2優先: LangGraphベストプラクティス**
- StateGraphによる型安全な状態管理
- Conditional edgesによる明示的な遷移
- Single responsibilityの原則
- ノードの再利用性

### アーキテクチャ決定

1. **既存コードの再利用**: `_generate_fixed_response`のロジックを各ノードに移植
2. **段階的移行**: 新実装を`langgraph_shopping_flow.py`に作成し、フラグで切り替え可能に
3. **後方互換性**: セッションデータ構造を変更しない
4. **ストリーミング対応**: StreamEvent出力を維持

## 状態設計

### ShoppingFlowState TypedDict

```python
from typing import TypedDict, Annotated, List, Dict, Any, Optional
from langgraph.graph.message import add_messages

class ShoppingFlowState(TypedDict):
    """
    ショッピングフローの状態

    AP2完全準拠:
    - セッションデータ構造を変更しない
    - 既存のsession辞書と互換性を維持
    """
    # 入力
    user_input: str
    session_id: str

    # セッションデータ（既存構造を維持）
    session: Dict[str, Any]

    # 出力イベント（ストリーミング）
    events: Annotated[List[Dict[str, Any]], lambda x, y: x + y]

    # 内部制御
    next_step: Optional[str]  # 次のノード名
    error: Optional[str]  # エラーメッセージ
```

### セッションデータ構造（変更なし）

```python
session = {
    "step": str,  # 現在のステップ
    "user_id": str,
    "intent": str,
    "max_amount": int,
    "categories": List[str],
    "brands": List[str],
    "intent_mandate": Dict,
    "shipping_address": Dict,
    "cart_candidates": List[Dict],
    "selected_cart_mandate": Dict,
    "cart_mandate": Dict,
    "selected_credential_provider": Dict,
    "available_payment_methods": List[Dict],
    "selected_payment_method": Dict,
    "tokenized_payment_method": Dict,
    "payment_mandate": Dict,
    "webauthn_challenge": str,
    "attestation_token": str,
    # ... その他既存フィールド
}
```

## ノード設計

### 1. greeting_node
**責務**: 初回挨拶、セッションリセット処理
**入力**: initial ステップ
**出力**: イベント、次ステップ = "collect_intent"

### 2. collect_intent_node
**責務**: LangGraph会話エージェントでIntent/max_amount/categories/brands収集
**入力**: ask_intent, ask_max_amount, ask_categories, ask_brands, collecting_intent_info ステップ
**出力**:
- IntentMandate（session["intent_mandate"]に保存）
- 次ステップ = "collect_shipping"

### 3. collect_shipping_node
**責務**: 配送先住所入力フォーム表示・受信
**入力**: intent_complete_ask_shipping, shipping_address_input ステップ
**出力**:
- 配送先住所（session["shipping_address"]に保存）
- 次ステップ = "fetch_carts"

### 4. fetch_carts_node
**責務**: Merchant AgentにIntentMandateを送信してカート候補取得（A2A通信）
**入力**: shipping_address_input完了後
**出力**:
- カート候補リスト（session["cart_candidates"]に保存）
- cart_options StreamEvent
- 次ステップ = "select_cart"

**AP2準拠**: `_search_products_via_merchant_agent`メソッドを呼び出し

### 5. select_cart_node
**責務**: ユーザーのカート選択、Merchant署名検証
**入力**: cart_selection ステップ
**出力**:
- 選択されたCartMandate（session["cart_mandate"]に保存）
- signature_request StreamEvent
- 次ステップ = "cart_signature_pending"

**AP2準拠**: Merchant署名の暗号学的検証を実施

### 6. wait_cart_signature_node
**責務**: カート署名待機（WebAuthn）
**入力**: cart_signature_pending ステップ
**出力**: メッセージ表示のみ、ユーザー入力待ち
**注**: このノードは外部API（POST /cart/submit-signature）が呼ばれるまで待機

### 7. select_credential_provider_node
**責務**: Credential Provider選択、支払い方法取得
**入力**: select_credential_provider, select_credential_provider_for_payment ステップ
**出力**:
- Credential Provider情報（session["selected_credential_provider"]に保存）
- 支払い方法リスト（session["available_payment_methods"]に保存）
- 次ステップ = "select_payment_method"

### 8. select_payment_method_node
**責務**: 支払い方法選択、トークン化、Step-up判定、PaymentMandate作成
**入力**: select_payment_method ステップ
**出力**:
- トークン化された支払い方法（session["tokenized_payment_method"]に保存）
- 次ステップ = "step_up_auth"（Step-up必要時）または "webauthn_auth"（不要時）

**AP2準拠**:
- `_tokenize_payment_method`呼び出し
- `_create_payment_mandate`呼び出し
- Step-up要否判定

### 9. step_up_auth_node
**責務**: Step-up認証（3DS 2.0）リダイレクト、完了待機
**入力**: step-up-completed, stepup_authentication_required ステップ
**出力**:
- step_up_redirect StreamEvent（リダイレクト開始時）
- 次ステップ = "webauthn_auth"（認証完了後）

**AP2準拠**: Credential ProviderのStep-up APIと連携

### 10. webauthn_auth_node
**責務**: WebAuthn/Passkey認証リクエスト、待機
**入力**: webauthn_attestation_requested ステップ
**出力**:
- webauthn_request StreamEvent
- ユーザー入力待ち
**注**: このノードは外部API（POST /payment/submit-attestation）が呼ばれるまで待機

### 11. execute_payment_node
**責務**: Payment Processor経由で決済実行、結果表示
**入力**: WebAuthn認証完了後（外部API呼び出し後）
**出力**:
- 決済結果（transaction_id等）
- 領収書表示
- 次ステップ = "completed"

**AP2準拠**:
- `_process_payment_via_merchant_agent`呼び出し
- Merchant Agent → Payment ProcessorのA2A通信

### 12. completed_node
**責務**: 完了メッセージ表示、セッションリセット案内
**入力**: completed ステップ
**出力**: 完了メッセージ

### 13. error_node
**責務**: エラーメッセージ表示、リセット案内
**入力**: error ステップ
**出力**: エラーメッセージ

## 条件付きエッジ設計

### ルーティング関数

```python
def route_from_greeting(state: ShoppingFlowState) -> str:
    """挨拶ノードからのルーティング"""
    step = state["session"].get("step")
    if step == "initial":
        return "collect_intent"
    elif step == "error":
        return "error"
    return END

def route_from_intent_collection(state: ShoppingFlowState) -> str:
    """Intent収集ノードからのルーティング"""
    if state["session"].get("conversation_state", {}).get("is_complete"):
        return "collect_shipping"
    return END  # まだ情報が不足している場合は終了

def route_from_payment_method(state: ShoppingFlowState) -> str:
    """支払い方法選択ノードからのルーティング"""
    if state["session"].get("selected_payment_method", {}).get("requires_step_up"):
        return "step_up_auth"
    return "webauthn_auth"

def route_from_step_up(state: ShoppingFlowState) -> str:
    """Step-up認証ノードからのルーティング"""
    if state["session"].get("step") == "webauthn_attestation_requested":
        return "webauthn_auth"
    return END  # 認証待機中

# ... その他のルーティング関数
```

### エッジ定義

```python
workflow = StateGraph(ShoppingFlowState)

# ノード追加
workflow.add_node("greeting", greeting_node)
workflow.add_node("collect_intent", collect_intent_node)
workflow.add_node("collect_shipping", collect_shipping_node)
workflow.add_node("fetch_carts", fetch_carts_node)
workflow.add_node("select_cart", select_cart_node)
workflow.add_node("wait_cart_signature", wait_cart_signature_node)
workflow.add_node("select_credential_provider", select_credential_provider_node)
workflow.add_node("select_payment_method", select_payment_method_node)
workflow.add_node("step_up_auth", step_up_auth_node)
workflow.add_node("webauthn_auth", webauthn_auth_node)
workflow.add_node("execute_payment", execute_payment_node)
workflow.add_node("completed", completed_node)
workflow.add_node("error", error_node)

# 条件付きエッジ
workflow.add_conditional_edges("greeting", route_from_greeting, {
    "collect_intent": "collect_intent",
    "error": "error",
    END: END
})

workflow.add_conditional_edges("collect_intent", route_from_intent_collection, {
    "collect_shipping": "collect_shipping",
    END: END
})

workflow.add_edge("collect_shipping", "fetch_carts")
workflow.add_edge("fetch_carts", "select_cart")
workflow.add_edge("select_cart", "wait_cart_signature")

workflow.add_conditional_edges("select_payment_method", route_from_payment_method, {
    "step_up_auth": "step_up_auth",
    "webauthn_auth": "webauthn_auth"
})

workflow.add_conditional_edges("step_up_auth", route_from_step_up, {
    "webauthn_auth": "webauthn_auth",
    END: END
})

# ... その他のエッジ

# グラフをコンパイル
workflow.set_entry_point("greeting")
compiled_workflow = workflow.compile()
```

## ストリーミング対応

### StreamEventの蓄積と出力

各ノードは以下のパターンでStreamEventを生成：

```python
async def example_node(state: ShoppingFlowState) -> ShoppingFlowState:
    """ノード実装パターン"""
    session = state["session"]
    events = state.get("events", [])

    # イベント生成
    events.append({
        "type": "agent_text",
        "content": "メッセージ"
    })

    # ビジネスロジック実行
    # ...

    # 状態更新
    return {
        **state,
        "session": session,
        "events": events,
        "next_step": "次のステップ名"
    }
```

### 呼び出し側でのストリーミング

```python
async def _generate_fixed_response_langgraph(
    self,
    user_input: str,
    session: Dict[str, Any],
    session_id: str
) -> AsyncGenerator[StreamEvent, None]:
    """LangGraph版の応答生成（ストリーミング）"""

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
        yield StreamEvent(**event_dict)

    # セッション更新
    await self._update_session(session_id, result["session"])
```

## 移行計画

### フェーズ1: 基本実装（今回）

1. `langgraph_shopping_flow.py`を作成
2. StateGraph、ノード、エッジを実装
3. ユニットテスト作成

### フェーズ2: 統合テスト

1. 既存の`_generate_fixed_response`と並行稼働
2. フラグで切り替え可能に：`USE_LANGGRAPH_FLOW=True`
3. E2Eテストで両方の実装を検証

### フェーズ3: 本番切り替え

1. LangGraph版をデフォルトに
2. 既存実装を`_generate_fixed_response_legacy`にリネーム
3. ドキュメント更新

## AP2準拠の検証項目

### 署名フロー
- [ ] Merchant署名検証（`SignatureManager.verify_mandate_signature`）
- [ ] User署名（WebAuthn/Passkey）
- [ ] IntentMandate/CartMandate/PaymentMandateの構造

### A2A通信
- [ ] IntentMandate送信（Shopping Agent → Merchant Agent）
- [ ] CartCandidates受信（Artifact形式）
- [ ] PaymentMandate送信（Shopping Agent → Merchant Agent → Payment Processor）

### セキュリティ
- [ ] WebAuthn/Passkey認証フロー
- [ ] Step-up認証（3DS 2.0）
- [ ] トークン化された支払い方法

### リスク評価
- [ ] `RiskEngine.assess_payment_mandate`呼び出し
- [ ] fraud_indicatorsとrisk_scoreの計算

## メリット

1. **可読性**: 各ステップが独立した関数として明確
2. **保守性**: ステップの追加・変更が容易
3. **テスタビリティ**: 各ノードを個別にテスト可能
4. **可視化**: LangGraphの可視化ツールでフロー確認可能
5. **並列実行**: 将来的に独立したステップを並列実行可能
6. **型安全性**: TypedDictによる型チェック

## 参考資料

- [LangGraph StateGraph公式ドキュメント](https://langchain-ai.github.io/langgraph/concepts/low_level/)
- [LangGraph APIリファレンス](https://langchain-ai.github.io/langgraph/reference/graphs/)
- [AP2仕様書](https://ap2-protocol.org/specification/)
