# Merchant Agent AI化設計書

**作成日**: 2025-10-22
**対象**: `/v2/services/merchant_agent/`
**目的**: Merchant AgentをLangGraph + MCP統合でAIエージェント化（AP2準拠）

---

## 📋 目次

1. [現状分析](#現状分析)
2. [AI化の目標](#ai化の目標)
3. [アーキテクチャ設計](#アーキテクチャ設計)
4. [LangGraph対話フロー](#langgraph対話フロー)
5. [MCP統合設計](#mcp統合設計)
6. [A2A通信強化](#a2a通信強化)
7. [実装計画](#実装計画)
8. [AP2準拠の保証](#ap2準拠の保証)

---

## 現状分析

### 現在のMerchant Agent実装

**ファイル**: `v2/services/merchant_agent/agent.py`

**主な機能**:
1. **商品検索** (`search_products()`) - データベースクエリベース
2. **CartMandate作成** (`create_cart_mandate()`) - 固定ロジック
3. **Merchant署名依頼** - A2A経由でMerchantサービスに送信

**課題**:
- ❌ **固定的なカート構築** - ユーザーのニーズに柔軟に対応できない
- ❌ **対話能力なし** - Shopping Agentからのリクエストをそのまま処理
- ❌ **最適化能力なし** - 複数カート候補の提案、代替商品の提案ができない
- ❌ **在庫状況の考慮不足** - 在庫切れ時の代替提案なし
- ❌ **価格最適化なし** - 予算内での最適な組み合わせ提案ができない

### Shopping Agentとの比較

| 項目 | Shopping Agent | Merchant Agent（現状） |
|------|----------------|----------------------|
| LangGraph統合 | ✅ 実装済み | ❌ 未実装 |
| LLM対話フロー | ✅ Intent収集 | ❌ なし |
| MCP統合 | ⏳ 予定 | ❌ 未実装 |
| A2A通信 | ✅ 送受信 | ✅ 送受信 |
| SSE Streaming | ✅ 対応 | ❌ 不要（B2B通信） |

---

## AI化の目標

### 🎯 主要目標

1. **インテリジェントなカート構築**
   - ユーザーのIntent（購買意図）を理解
   - 予算制約を考慮した最適な商品組み合わせ
   - 在庫状況に基づく代替案提案

2. **複数カート候補の提案**
   - 「エコノミープラン」「スタンダードプラン」「プレミアムプラン」
   - 価格帯別の選択肢
   - ブランド別の選択肢

3. **MCP統合による外部データ活用**
   - リアルタイム在庫確認（MCPサーバー経由）
   - 価格比較API統合
   - レビュー・評価データ取得

4. **A2A通信の高度化**
   - Shopping Agentとのネゴシエーション
   - Merchantへの署名リクエスト最適化
   - Payment Processorへのメタデータ提供

### 🚫 非目標（AP2準拠維持のため）

- ❌ CartMandateの構造変更（AP2仕様を厳守）
- ❌ 署名ロジックの変更（Merchantサービスが担当）
- ❌ 決済フローの変更（Payment Processorが担当）

---

## アーキテクチャ設計

### 全体構成

```
┌─────────────────────────────────────────────────────────┐
│               Merchant Agent (AI化後)                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  ┌───────────────────────────────────────────────────┐  │
│  │         LangGraph Conversation Engine             │  │
│  │  - Intent理解                                      │  │
│  │  - カート最適化                                    │  │
│  │  │  - 複数候補生成                                │  │
│  ├───────────────────────────────────────────────────┤  │
│  │         MCP Client                                 │  │
│  │  - 在庫確認MCPサーバー                             │  │
│  │  - 価格比較MCPサーバー                             │  │
│  │  - レビューMCPサーバー                             │  │
│  ├───────────────────────────────────────────────────┤  │
│  │         A2A Message Handler                        │  │
│  │  - Shopping Agent ← ProductSearchRequest          │  │
│  │  - Shopping Agent → CartOptions (複数候補)         │  │
│  │  - Merchant → CartSignatureRequest                │  │
│  ├───────────────────────────────────────────────────┤  │
│  │         Database Manager                           │  │
│  │  - 商品検索（SQLAlchemy）                          │  │
│  │  - キャッシュ管理                                  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         ↓ A2A                ↓ HTTP              ↓ MCP
    Shopping Agent        Merchant Service     MCP Servers
```

### 新規ファイル構成

```
v2/services/merchant_agent/
├── agent.py                     # 既存（A2A、HTTP API）
├── langgraph_merchant.py        # 🆕 LangGraphエンジン
├── mcp_client.py                # 🆕 MCP統合クライアント
├── cart_optimizer.py            # 🆕 カート最適化ロジック
├── tools/                       # 🆕 LangGraphツール
│   ├── __init__.py
│   ├── product_search_tool.py   # データベース検索ツール
│   ├── inventory_check_tool.py  # MCP在庫確認ツール
│   ├── price_compare_tool.py    # MCP価格比較ツール
│   └── cart_builder_tool.py     # カート構築ツール
├── main.py                      # 既存（FastAPIエントリーポイント）
└── Dockerfile                   # 既存
```

---

## LangGraph対話フロー

### ステートグラフ設計

```python
class MerchantAgentState(TypedDict):
    """Merchant Agentの状態管理"""

    # 入力情報（Shopping Agentから受信）
    intent_mandate: Dict[str, Any]  # IntentMandate（予算、カテゴリなど）
    user_preferences: Dict[str, Any]  # ユーザー嗜好

    # 検索結果
    available_products: List[Dict]  # データベース検索結果
    inventory_status: Dict[str, int]  # MCP在庫確認結果
    price_comparisons: List[Dict]  # MCP価格比較結果

    # 生成されたカート候補
    cart_candidates: List[Dict]  # 複数のCartMandate候補

    # LLM思考過程
    llm_reasoning: str

    # 最終出力
    selected_carts: List[Dict]  # Shopping Agentに返すカート候補（通常3つ）
```

### グラフフロー

```
START
  │
  ├─→ [1] analyze_intent
  │     └─ IntentMandateを解析
  │        - 購買意図（intent）
  │        - 最大金額（max_amount）
  │        - カテゴリー（categories）
  │        - ブランド（brands）
  │
  ├─→ [2] search_products
  │     └─ データベース検索
  │        - キーワードマッチ
  │        - カテゴリーフィルタ
  │        - ブランドフィルタ
  │        - 価格範囲フィルタ
  │
  ├─→ [3] check_inventory (MCP)
  │     └─ MCPサーバーで在庫確認
  │        - リアルタイム在庫数
  │        - 入荷予定
  │        - 代替品情報
  │
  ├─→ [4] optimize_cart (LLM)
  │     └─ LLMによるカート最適化
  │        - 予算内での最適組み合わせ
  │        - 複数プラン生成
  │          * エコノミー（最安）
  │          * スタンダード（バランス）
  │          * プレミアム（最高品質）
  │
  ├─→ [5] build_cart_mandates
  │     └─ AP2準拠のCartMandate構築
  │        - contents.payment_request.details
  │        - display_items（商品、税、送料）
  │        - shipping_address
  │
  ├─→ [6] rank_and_select
  │     └─ カート候補のランク付け
  │        - ユーザー嗜好マッチ度
  │        - 価格競争力
  │        - 在庫確実性
  │        - トップ3を選択
  │
  └─→ END
```

### ノード実装例

```python
# v2/services/merchant_agent/langgraph_merchant.py

from typing import Dict, Any, List
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END

class MerchantLangGraphAgent:
    """Merchant Agent用LangGraphエンジン"""

    def __init__(self, db_manager, mcp_client):
        self.db_manager = db_manager
        self.mcp_client = mcp_client
        self.llm = ChatOpenAI(
            base_url=os.getenv("DMR_API_URL"),
            model=os.getenv("DMR_MODEL"),
            temperature=0.5
        )
        self.graph = self._build_graph()

    def _build_graph(self):
        workflow = StateGraph(MerchantAgentState)

        # ノード登録
        workflow.add_node("analyze_intent", self._analyze_intent)
        workflow.add_node("search_products", self._search_products)
        workflow.add_node("check_inventory", self._check_inventory)
        workflow.add_node("optimize_cart", self._optimize_cart)
        workflow.add_node("build_cart_mandates", self._build_cart_mandates)
        workflow.add_node("rank_and_select", self._rank_and_select)

        # フロー定義
        workflow.set_entry_point("analyze_intent")
        workflow.add_edge("analyze_intent", "search_products")
        workflow.add_edge("search_products", "check_inventory")
        workflow.add_edge("check_inventory", "optimize_cart")
        workflow.add_edge("optimize_cart", "build_cart_mandates")
        workflow.add_edge("build_cart_mandates", "rank_and_select")
        workflow.add_edge("rank_and_select", END)

        return workflow.compile()

    async def _analyze_intent(self, state: MerchantAgentState):
        """IntentMandateを解析"""
        intent_mandate = state["intent_mandate"]

        # LLMで購買意図を解析
        prompt = f"""
        以下のIntent Mandateから、ユーザーの具体的なニーズを抽出してください。

        Intent: {intent_mandate.get('intent')}
        Max Amount: ¥{intent_mandate.get('constraints', {}).get('max_amount', {}).get('value', 0):,}
        Categories: {intent_mandate.get('constraints', {}).get('categories', [])}
        Brands: {intent_mandate.get('constraints', {}).get('brands', [])}

        抽出項目:
        1. 商品カテゴリー（具体的に）
        2. 重視するポイント（価格、品質、ブランドなど）
        3. 予算の使い方（全額使うか、節約するか）
        """

        response = await self.llm.ainvoke(prompt)
        state["llm_reasoning"] = response.content
        state["user_preferences"] = self._parse_llm_response(response.content)

        return state

    async def _optimize_cart(self, state: MerchantAgentState):
        """LLMによるカート最適化 - 複数プラン生成"""
        available_products = state["available_products"]
        inventory_status = state["inventory_status"]
        max_amount = state["intent_mandate"]["constraints"]["max_amount"]["value"]

        # LLMプロンプト
        prompt = f"""
        以下の商品から、ユーザーの予算¥{max_amount:,}内で、3つの異なるカートプランを作成してください。

        利用可能な商品:
        {json.dumps(available_products, ensure_ascii=False, indent=2)}

        在庫状況:
        {json.dumps(inventory_status, ensure_ascii=False, indent=2)}

        プラン要件:
        1. エコノミープラン: 最もコストパフォーマンスが高い組み合わせ
        2. スタンダードプラン: バランスの取れた組み合わせ
        3. プレミアムプラン: 最高品質の組み合わせ

        各プランで以下を出力（JSON形式）:
        {{
          "plan_name": "プラン名",
          "items": [
            {{"product_id": "...", "quantity": 1, "reason": "選択理由"}}
          ],
          "total_price": 0,
          "selling_points": ["セールスポイント1", "..."]
        }}
        """

        response = await self.llm.ainvoke(prompt)
        cart_plans = self._parse_cart_plans(response.content)
        state["cart_candidates"] = cart_plans

        return state
```

---

## MCP統合設計

### MCP Servers概要

Merchant AgentはMCP (Model Context Protocol)を使って外部データソースと連携します。

#### 1. 在庫確認MCPサーバー

**目的**: リアルタイム在庫状況の取得

```python
# mcp_servers/inventory_server.py (別リポジトリまたは外部サービス)

from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("inventory-checker")

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="check_inventory",
            description="商品の在庫数をリアルタイムで確認",
            inputSchema={
                "type": "object",
                "properties": {
                    "product_id": {"type": "string"},
                    "merchant_id": {"type": "string"}
                }
            }
        )
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "check_inventory":
        # 実際の在庫確認ロジック（Merchant DBに問い合わせ）
        inventory = await get_inventory_from_merchant(
            arguments["product_id"],
            arguments["merchant_id"]
        )
        return [TextContent(
            type="text",
            text=json.dumps({
                "product_id": arguments["product_id"],
                "available": inventory.available_count,
                "reserved": inventory.reserved_count,
                "incoming": inventory.incoming_shipments
            })
        )]
```

#### 2. 価格比較MCPサーバー

**目的**: 競合他社との価格比較

```python
# mcp_servers/price_comparison_server.py

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "compare_prices":
        # 外部API（楽天、Amazonなど）から価格取得
        prices = await fetch_competitor_prices(arguments["product_name"])
        return [TextContent(
            type="text",
            text=json.dumps({
                "our_price": arguments["our_price"],
                "competitors": prices,
                "is_competitive": our_price <= min(prices)
            })
        )]
```

#### 3. レビュー・評価MCPサーバー

**目的**: 商品レビューと評価の取得

```python
# mcp_servers/review_server.py

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "get_reviews":
        reviews = await fetch_product_reviews(arguments["product_id"])
        return [TextContent(
            type="text",
            text=json.dumps({
                "average_rating": reviews.avg_rating,
                "review_count": reviews.count,
                "top_reviews": reviews.top_3
            })
        )]
```

### MCP Client実装

```python
# v2/services/merchant_agent/mcp_client.py

import asyncio
from mcp.client import Client
from typing import Dict, Any, List

class MerchantMCPClient:
    """Merchant Agent用MCPクライアント"""

    def __init__(self):
        self.inventory_client = None
        self.price_client = None
        self.review_client = None

    async def connect(self):
        """MCPサーバーに接続"""
        self.inventory_client = await Client.connect("stdio://inventory-server")
        self.price_client = await Client.connect("stdio://price-comparison-server")
        self.review_client = await Client.connect("stdio://review-server")

    async def check_inventory(self, product_id: str, merchant_id: str) -> Dict:
        """在庫確認"""
        result = await self.inventory_client.call_tool(
            "check_inventory",
            {"product_id": product_id, "merchant_id": merchant_id}
        )
        return json.loads(result[0].text)

    async def compare_prices(self, product_name: str, our_price: float) -> Dict:
        """価格比較"""
        result = await self.price_client.call_tool(
            "compare_prices",
            {"product_name": product_name, "our_price": our_price}
        )
        return json.loads(result[0].text)

    async def get_reviews(self, product_id: str) -> Dict:
        """レビュー取得"""
        result = await self.review_client.call_tool(
            "get_reviews",
            {"product_id": product_id}
        )
        return json.loads(result[0].text)
```

---

## A2A通信強化

### 現在のA2Aフロー

```
Shopping Agent → Merchant Agent: ap2/ProductSearchRequest
Merchant Agent → Shopping Agent: ap2/ProductList
```

### AI化後のA2Aフロー（拡張）

```
1. Shopping Agent → Merchant Agent: ap2/ProductSearchRequest
   {
     "intent_mandate": {...},
     "user_id": "...",
     "session_id": "..."
   }

2. Merchant Agent → Shopping Agent: ap2/CartOptions (新規)
   {
     "cart_candidates": [
       {
         "cart_mandate": {...},  // AP2準拠CartMandate
         "plan_name": "エコノミープラン",
         "selling_points": ["最安値", "送料無料"],
         "total_price": {"value": 10000, "currency": "JPY"}
       },
       {...},  // スタンダードプラン
       {...}   // プレミアムプラン
     ],
     "llm_reasoning": "LLMの思考過程（オプション）"
   }

3. Shopping Agent → Merchant Agent: ap2/CartSelectionRequest
   {
     "selected_cart_id": "cart_abc123",
     "user_id": "..."
   }

4. Merchant Agent → Merchant: ap2/CartSignatureRequest
   {
     "cart_mandate": {...}  // 署名依頼
   }

5. Merchant → Merchant Agent: ap2/SignedCartMandate
   {
     "cart_mandate": {...},  // merchant_authorization付き
     "signature": "..."
   }

6. Merchant Agent → Shopping Agent: ap2/SignedCartMandate
   {
     "cart_mandate": {...}  // ユーザーに署名を促す
   }
```

### 新規A2Aメッセージタイプ定義

```python
# v2/common/models.py に追加

class CartOptions(BaseModel):
    """複数カート候補を返す（Merchant Agent → Shopping Agent）"""
    cart_candidates: List[Dict[str, Any]]
    llm_reasoning: Optional[str] = None

class CartSelectionRequest(BaseModel):
    """ユーザーが選択したカートID（Shopping Agent → Merchant Agent）"""
    selected_cart_id: str
    user_id: str
```

---

## 実装計画

### Phase 1: LangGraph統合（Week 1）

**目標**: 基本的なLLM対話フローを実装

**タスク**:
1. ✅ `langgraph_merchant.py`作成
2. ✅ `MerchantAgentState`定義
3. ✅ 6ノードのグラフフロー実装
   - analyze_intent
   - search_products
   - check_inventory (仮実装: DBのみ)
   - optimize_cart
   - build_cart_mandates
   - rank_and_select
4. ✅ `agent.py`にLangGraphエンジン統合
5. ✅ A2Aハンドラー更新（ProductSearchRequest → CartOptions）

**検証**:
- Shopping AgentからのProductSearchRequestで3つのカート候補が返る
- AP2準拠のCartMandate構造を維持

---

### Phase 2: MCP統合（Week 2）

**目標**: MCPサーバーとの連携を実装

**タスク**:
1. ✅ `mcp_client.py`作成
2. ✅ 在庫確認MCPサーバー実装（または外部サービス接続）
3. ✅ 価格比較MCPサーバー実装
4. ✅ `check_inventory`ノードをMCP対応に変更
5. ✅ `optimize_cart`ノードに価格比較データ統合

**検証**:
- MCP経由でリアルタイム在庫数が取得できる
- 価格競争力がカート候補に反映される

---

### Phase 3: A2A通信高度化（Week 3）

**目標**: Shopping Agentとのインタラクションを高度化

**タスク**:
1. ✅ `ap2/CartOptions`メッセージタイプ定義
2. ✅ `ap2/CartSelectionRequest`メッセージタイプ定義
3. ✅ Shopping Agent側のハンドラー更新（カート候補受信）
4. ✅ Merchant Agent側のハンドラー更新（カート選択受信）
5. ✅ フロントエンドのカート候補UI改善（LLM思考過程表示）

**検証**:
- ユーザーが3つのカート候補から選択できる
- 選択後の署名フローが正常動作

---

### Phase 4: 最適化とテスト（Week 4）

**目標**: パフォーマンス最適化とエンドツーエンドテスト

**タスク**:
1. ✅ LLMプロンプトの最適化
2. ✅ キャッシュ戦略実装（商品検索、在庫確認）
3. ✅ エラーハンドリング強化
4. ✅ ロギング・モニタリング追加
5. ✅ E2Eテストシナリオ作成

**検証**:
- レスポンスタイム < 5秒
- 在庫切れ時の代替提案が動作
- AP2準拠が維持されている

---

## AP2準拠の保証

### 絶対に変更してはいけない項目

1. **CartMandate構造**
   ```typescript
   {
     "contents": {
       "id": "cart_...",
       "payment_request": {
         "details": {
           "display_items": [...],  // refund_period必須
           "total": {"amount": {...}}
         },
         "shipping_address": {
           "address_line": [...]  // 配列形式
         }
       }
     },
     "merchant_authorization": "...",  // Merchant署名
     "_metadata": {...}
   }
   ```

2. **Mandate Chain**
   - IntentMandate → CartMandate → PaymentMandate
   - 各Mandateの署名検証フロー

3. **A2A署名検証**
   - ECDSA署名の検証
   - タイムスタンプチェック

### AI化で強化される項目（AP2準拠を維持）

1. **カート内容の最適化**
   - 商品選択ロジックが柔軟になるが、構造は同じ

2. **display_itemsの構築**
   - LLMが最適な組み合わせを選ぶが、AP2形式は厳守

3. **複数カート候補**
   - AP2仕様にはない拡張だが、各カートは完全にAP2準拠

### 検証方法

```python
# tests/test_merchant_agent_ap2_compliance.py

async def test_cart_mandate_structure():
    """生成されたCartMandateがAP2準拠か検証"""
    # LangGraphでカート生成
    carts = await merchant_agent.create_cart_candidates(intent_mandate)

    for cart in carts:
        # 必須フィールド検証
        assert "contents" in cart
        assert "payment_request" in cart["contents"]
        assert "details" in cart["contents"]["payment_request"]

        # display_items検証
        for item in cart["contents"]["payment_request"]["details"]["display_items"]:
            assert "label" in item
            assert "amount" in item
            assert "value" in item["amount"]
            assert "currency" in item["amount"]
            assert "refund_period" in item  # AP2必須

        # shipping_address検証
        address = cart["contents"]["payment_request"]["shipping_address"]
        assert isinstance(address["address_line"], list)  # 配列形式

        # _metadata検証（merchant_id必須）
        assert "_metadata" in cart
        assert "merchant_id" in cart["_metadata"]

async def test_mandate_chain():
    """Mandate Chainが正しく繋がるか検証"""
    # IntentMandate → CartMandate → PaymentMandate
    intent = await shopping_agent.create_intent_mandate(...)
    carts = await merchant_agent.create_cart_candidates(intent)
    cart = carts[0]
    payment = await shopping_agent.create_payment_mandate(cart, intent)

    # Payment Processorで検証
    result = await payment_processor.validate_mandate_chain(
        intent, cart, payment
    )
    assert result["valid"] == True
```

---

## まとめ

### AI化のメリット

1. **ユーザー体験の向上**
   - 予算内での最適な商品提案
   - 複数プランから選択可能
   - 在庫切れ時の代替案

2. **ビジネス価値の向上**
   - コンバージョン率向上（最適化されたカート）
   - 顧客満足度向上（ニーズに合った提案）
   - 在庫効率化（リアルタイム在庫連携）

3. **技術的な拡張性**
   - MCP統合で外部データ活用
   - LangGraphで柔軟なフロー制御
   - A2A通信でエージェント間協調

### AP2準拠の維持

- ✅ CartMandate構造は完全にAP2準拠
- ✅ Mandate Chainの検証フロー維持
- ✅ 署名・暗号化ロジックは変更なし
- ✅ 既存のShopping Agent、Payment Processorと完全互換

### 次のステップ

1. このドキュメントをレビュー
2. Phase 1の実装開始承認
3. LangGraph統合の詳細設計
4. MCPサーバーの選定または開発

---

**質問・フィードバック歓迎！**
