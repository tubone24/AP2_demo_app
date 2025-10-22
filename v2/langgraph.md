## 要件整理

| 項目    | 内容                                                             |
|-------|----------------------------------------------------------------|
| 目的    | AP2上で動作するShopping Agent（SA）のように、LLMベースのAIエージェント化               |
| 実装方式  | LangGraphを利用し、DMRエンドポイント（OpenAI互換API）に接続してインテント抽出              |
| 通信    | Intent Mandate生成は **MCP経由（intent_mcp.py）**、他エンティティとは **A2A通信** |
| 暗号／署名 | 既存の `v2/common/crypt.py` と `v2/common/base_agent.py` を絶対に変更しない |
| 参考構造  | Shopping Agent と同一構造のDockerfileで統一                             |
| SAポート | 8000                                                           |

## 実装方針

### ディレクトリ案

```
v2/
├── common/
│   ├── base_agent.py
│   ├── crypt.py
│   └── ...
├── services/
│   ├── agent/
│   │   ├── Dockerfile
│   │   ├── main.py
│   │   ├── agent.py
│   │   ├── intent_mcp.py
│   │   └── __init__.py
│   └── shopping_agent/
│       ├── ...
├── pyproject.toml
└── README.md
```

### agent.py案

実際に今のSAのコードのインテントを抽出、そこからLangGraphを利用してIntent Mandateを生成する部分を考えています。
ただ、動く形になっているか不明なので、実際の実装を進めながら調整が必要です。

```python
import os
import json
import asyncio
from langgraph.graph import Graph
from langgraph.llms import OpenAI
from v2.common.base_agent import BaseAgent
from v2.common.crypt import sign_payload
from .intent_mcp import create_intent_mandate

# === LangGraph初期化 ===
LLM_ENDPOINT = os.getenv("DMR_API_URL", "http://localhost:12434/v1")
llm = OpenAI(api_base=LLM_ENDPOINT, model="gpt-4", api_key="none")

class IntentAgent(BaseAgent):
    """
    LangGraphとMCPを用いてユーザーの入力からIntent Mandateを生成し、
    A2A通信でMAへ送信するAIエージェント。
    """

    def __init__(self):
        super().__init__("SA_AI_AGENT")

    async def handle_user_input(self, message: str):
        """
        ユーザー入力をLangGraph経由で解釈 → Intent Mandateを生成 → MAへA2A送信
        """
        print(f"[DEBUG] User message received: {message}")

        # LangGraphで意図抽出
        response = llm.complete(
            prompt=f"ユーザーの要望をIntent Mandate化してください: {message}",
            temperature=0.3,
            max_tokens=256,
        )
        print(f"[DEBUG] LLM raw output: {response.text}")

        # Intent Mandate生成（MCP呼び出し）
        intent_mandate = await create_intent_mandate(response.text)
        print(f"[DEBUG] Intent Mandate created: {intent_mandate}")

        # A2A通信でMAへ送信
        signed_payload = sign_payload(intent_mandate)
        await self.a2a_send("MA", signed_payload)

        return "Intent Mandate sent to MA."
```

### intent_mcp.py（MCPサーバーとしてIntent Mandateを生成）

```
import json
import asyncio

# === Intent Mandate生成関数 ===
async def create_intent_mandate(intent_description: str) -> dict:
    """
    LLM出力をもとにIntent Mandateを生成する。
    MCP経由でLangGraphから呼び出される想定。
    """
    print("[MCP] Generating intent mandate...")

    # intent_descriptionを構造化（LLM出力がJSON風ならパース、それ以外はラップ）
    try:
        parsed = json.loads(intent_description)
    except json.JSONDecodeError:
        parsed = {"summary": intent_description.strip()}

    # Intent Mandate基本構造
    mandate = {
        "header": {
            "schema": "a2a://intentmandate/v0.1",
            "version": "0.1",
            "sender": "did:ap2:agent:sa_demo_001",
            "recipient": "did:ap2:agent:ma_main",
        },
        "dataPart": {
            "intent": parsed,
            "timestamp": asyncio.get_event_loop().time(),
        },
    }
    return mandate
```