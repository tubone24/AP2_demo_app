# AP2 (Agent Payments Protocol) サンプルコード

このリポジトリには、**Agent Payments Protocol (AP2)** の学習用サンプルコードが含まれています。

## 📚 AP2プロトコルとは？

AP2は、AIエージェントが安全に決済を行うためのオープンプロトコルです。Googleが60以上の組織と共同で開発しました。

### 主な特徴

- **Verifiable Credentials (VCs)**: 暗号署名された改ざん不可能な認証情報
- **3種類のMandate**: 
  - **Intent Mandate**: ユーザーがエージェントに与える購入権限
  - **Cart Mandate**: 特定のカート内容に対するユーザーの承認
  - **Payment Mandate**: 支払いネットワークに送信される情報
- **2つのシナリオ**:
  - **Human-Present**: ユーザーが立ち会ってリアルタイムで承認
  - **Human-Not-Present**: ユーザーが事前承認し、エージェントが自動実行

### アーキテクチャ

```
┌──────────────┐
│    User      │
│  (ユーザー)   │
└──────┬───────┘
       │
       ▼
┌──────────────────────┐
│  Shopping Agent      │
│ (購買アシスタント)    │
└──────┬───────────────┘
       │
       ├─────────────────────┐
       │                     │
       ▼                     ▼
┌──────────────┐      ┌──────────────────┐
│   Merchant   │      │   Credentials    │
│    Agent     │      │  Provider Agent  │
│ (販売者側)    │      │ (支払い情報管理) │
└──────┬───────┘      └──────────────────┘
       │
       ▼
┌──────────────────────┐
│  Payment Processor   │
│  (決済処理)           │
└──────────────────────┘
```

## 📁 ファイル構成

```
.
├── ap2_types.py                # Python型定義
├── ap2_crypto.py               # 暗号機能（鍵管理、署名）
├── secure_shopping_agent.py    # Shopping Agent実装（暗号統合版）
├── secure_merchant_agent.py    # Merchant Agent実装（暗号統合版）
├── complete_secure_flow.py     # 完全な統合デモ（暗号署名版）
├── ap2_demo_app.py             # Streamlitインタラクティブデモ ⭐NEW
├── run_demo.sh                 # デモアプリ起動スクリプト
├── ap2-types.ts                # TypeScript型定義
├── ap2-react-ui.tsx            # React UIサンプル
└── README.md                   # このファイル
```

## 🚀 クイックスタート

### 前提条件

- Python 3.10以上
- Node.js 16以上（TypeScript/Reactサンプル用）

### Python サンプルの実行

1. **依存関係のインストール**

```bash
# 必要なパッケージがあればインストール
pip install asyncio
```

2. **Shopping Agent単体の実行**

```bash
python shopping_agent.py
```

出力例:
```
=== Step 1: Intent Mandateの作成 ===
Intent Mandate作成: intent_abc123...
意図: 新しいランニングシューズを100ドル以下で購入したい
最大金額: USD 100.00

=== Step 2: 商品検索 ===
[My Shopping Assistant] 商品検索リクエストを送信
...
```

3. **Merchant Agent単体の実行**

```bash
python merchant_agent.py
```

出力例:
```
=== Step 1: 商品検索 ===
[Running Shoes Store] 商品検索を実行:
  意図: 新しいランニングシューズを100ドル以下で購入したい
  → 3件の商品が見つかりました

検索結果:
1. Nike Air Zoom Pegasus 40 (Nike)
   価格: USD 89.99
   説明: 軽量で快適なランニングシューズ...
```

4. **完全なフロー（End-to-End）の実行**

```bash
python complete_secure_flow.py
```

これにより、実際の暗号署名を使用したセキュアなフローを体験できます。

5. **🌟 Streamlitインタラクティブデモ（推奨）**

最もわかりやすく体験できる方法です！

```bash
# シェルスクリプトで起動
./run_demo.sh

# または直接Streamlitを起動
streamlit run ap2_demo_app.py
```

ブラウザが自動的に開き、以下の機能を体験できます：

- ✨ **ステップバイステップのUI**: 各ステップを視覚的に確認
- 🔐 **署名情報の表示**: 暗号署名の詳細を確認
- 📝 **インタラクティブな操作**: 実際にフォームを入力して体験
- ✅ **リアルタイム検証**: 各ステップでの署名検証を確認

**デモの流れ：**
1. 参加者の初期化（鍵生成）
2. 購買意図の表明（Intent Mandate）
3. 商品検索
4. カートの作成と承認（Cart Mandate）
5. 支払い情報の入力（Payment Mandate）
6. 支払い処理と完了

![Streamlitデモのスクリーンショット](https://via.placeholder.com/800x400?text=AP2+Streamlit+Demo)

## 📖 詳細な使用例

### 1. Intent Mandateの作成

```python
from shopping_agent import ShoppingAgent
from ap2_types import Amount

# Shopping Agentを初期化
agent = ShoppingAgent(
    agent_id="shopping_agent_001",
    agent_name="My Shopping Assistant"
)

# Intent Mandateを作成
intent_mandate = agent.create_intent_mandate(
    user_id="user_123",
    user_public_key="user_public_key",
    intent="新しいランニングシューズを購入したい",
    max_amount=Amount(value="100.00", currency="USD"),
    categories=["running"],
    brands=["Nike", "Adidas", "Asics"]
)

print(f"Intent Mandate ID: {intent_mandate.id}")
print(f"有効期限: {intent_mandate.expires_at}")
```

### 2. 商品検索とCart Mandateの作成

```python
from merchant_agent import MerchantAgent

# Merchant Agentを初期化
merchant = MerchantAgent(
    agent_id="merchant_agent_001",
    merchant_name="Running Shoes Store",
    merchant_id="merchant_123"
)

# 商品を検索
products = merchant.search_products(intent_mandate)

# Cart Mandateを作成
cart_mandates = merchant.create_cart_mandate(
    intent_mandate=intent_mandate,
    products=products[:3]  # 上位3商品
)

for cart in cart_mandates:
    print(f"Cart ID: {cart.id}")
    print(f"合計金額: {cart.total}")
```

### 3. 支払い処理

```python
# 支払い方法を取得
payment_methods = await agent.get_payment_methods(
    credentials_provider_agent_id="credentials_provider_001",
    user_id="user_123"
)

# 最初の支払い方法を選択
selected_payment = payment_methods[0]

# Payment Mandateを作成
payment_mandate = await agent.create_payment_mandate(
    cart_mandate=selected_cart,
    intent_mandate=intent_mandate,
    payment_method=selected_payment,
    user_id="user_123",
    user_public_key="user_public_key"
)

# 支払いを処理
result = await agent.process_payment(
    payment_mandate=payment_mandate,
    payment_processor_id="payment_processor_001"
)

print(f"トランザクションID: {result.id}")
print(f"ステータス: {result.status.value}")
```

## 🎨 TypeScript/React サンプル

### React UIコンポーネントの使用

```tsx
import { AP2ShoppingUI } from './ap2-react-ui';
import { AP2Client } from './ap2-react-ui';

function App() {
  const client = new AP2Client({
    shoppingAgentUrl: 'https://api.example.com/shopping-agent',
    merchantAgentUrl: 'https://api.example.com/merchant-agent',
    credentialsProviderUrl: 'https://api.example.com/credentials-provider'
  });

  return (
    <AP2ShoppingUI 
      userId="user_123" 
      client={client}
    />
  );
}
```

## 🔐 セキュリティの考慮事項

### 署名の検証

実際の実装では、以下の点に注意してください:

```python
def verify_signature(signature: Signature, data: str) -> bool:
    """
    署名を検証する（実装例）
    
    実際には:
    1. dataのハッシュを計算
    2. 公開鍵を使って署名を検証
    3. ECDSAなどの暗号アルゴリズムを使用
    """
    # 暗号ライブラリ（cryptography, ecdsa等）を使用
    pass
```

### Mandateの有効期限チェック

```python
from datetime import datetime

def is_mandate_valid(mandate: IntentMandate) -> bool:
    """Mandateが有効かチェック"""
    expires_at = datetime.fromisoformat(
        mandate.expires_at.replace('Z', '+00:00')
    )
    return datetime.now(expires_at.tzinfo) < expires_at
```

## 📊 フロー図

### Human-Present フロー

```
1. ユーザー → Shopping Agent: 購買意図を伝える
2. Shopping Agent: Intent Mandateを作成
3. ユーザー: Intent Mandateを承認
4. Shopping Agent → Merchant Agent: 商品を検索
5. Merchant Agent: Cart Mandateを作成
6. ユーザー: カートを選択
7. Shopping Agent → Credentials Provider: 支払い方法を取得
8. ユーザー: 支払い方法を選択
9. Shopping Agent: Payment Mandateを作成
10. ユーザー: 支払いを承認
11. Shopping Agent → Payment Processor: 支払いを処理
12. 完了: トランザクション成功
```

### Human-Not-Present フロー

```
1. ユーザー: 事前にIntent Mandateを承認（条件設定）
2. エージェント: 条件がトリガーされるまで待機
3. 条件満足: エージェントが自動的に処理開始
4. Shopping Agent → Merchant Agent: 商品を検索
5. Shopping Agent: 最適なカートを自動選択
6. Shopping Agent: Payment Mandateを作成
7. Shopping Agent → Payment Processor: 自動的に支払い
8. 完了: ユーザーに通知
```

## 🔧 カスタマイズ

### 独自のエージェントを作成

```python
from ap2_types import AgentIdentity, AgentType

class MyCustomAgent:
    def __init__(self, agent_id: str, agent_name: str):
        self.identity = AgentIdentity(
            id=agent_id,
            name=agent_name,
            type=AgentType.SHOPPING,  # または他のタイプ
            public_key="your_public_key"
        )
    
    async def custom_operation(self):
        # 独自の処理を実装
        pass
```

### 支払い方法の拡張

```python
from dataclasses import dataclass
from ap2_types import PaymentMethod

@dataclass
class CustomPaymentMethod:
    type: str
    provider: str
    token: str
    # 独自のフィールドを追加
```

## 📚 参考リンク

- [AP2公式サイト](https://ap2-protocol.org/)
- [GitHubリポジトリ](https://github.com/google-agentic-commerce/AP2)
- [Google Cloudブログ](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol)
- [A2Aプロトコル](https://a2a-protocol.org/)
- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)

## ⚠️ 注意事項

このサンプルコードは**学習用**です。本番環境で使用する場合は、以下の点に注意してください:

1. **暗号署名**: 実際の暗号ライブラリを使用して署名を実装
2. **セキュリティ**: 秘密鍵の安全な管理
3. **エラーハンドリング**: より堅牢なエラー処理
4. **認証**: 適切な認証・認可の実装
5. **テスト**: 包括的なユニットテスト・統合テスト
6. **コンプライアンス**: PCI DSSなどの決済業界標準への準拠

## 🤝 コントリビューション

改善提案やバグ報告は大歓迎です！

## 📄 ライセンス

このサンプルコードはMITライセンスの下で公開されています。

---

**Happy Learning! 🎉**

AP2プロトコルを使って、安全なAIエージェント決済システムを構築しましょう！
