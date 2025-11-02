"""
v2/services/payment_network/test_network.py

Payment Network Serviceのテスト
"""

import sys
from pathlib import Path
import asyncio
import httpx

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))


async def test_payment_network():
    """決済ネットワークサービスの動作テスト"""

    base_url = "http://localhost:8005"

    async with httpx.AsyncClient() as client:
        # 1. ヘルスチェック
        print("\n=== 1. ヘルスチェック ===")
        response = await client.get(f"{base_url}/health")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        assert response.status_code == 200

        # 2. ネットワーク情報取得
        print("\n=== 2. ネットワーク情報取得 ===")
        response = await client.get(f"{base_url}/network/info")
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        assert response.status_code == 200

        # 3. Agent Token発行（トークン化呼び出し）
        print("\n=== 3. Agent Token発行 ===")
        tokenize_request = {
            "payment_mandate": {
                "id": "pm_test_001",
                "payer_id": "user_demo_001",
                "amount": {
                    "value": "10000.00",
                    "currency": "JPY"
                }
            },
            "attestation": {
                "type": "passkey",
                "verified": True
            },
            "payment_method_token": "tok_visa_4242",
            "transaction_context": {
                "test": True
            }
        }

        response = await client.post(
            f"{base_url}/network/tokenize",
            json=tokenize_request
        )
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {data}")
        assert response.status_code == 200
        assert "agent_token" in data

        agent_token = data["agent_token"]

        # 4. Agent Token検証
        print("\n=== 4. Agent Token検証 ===")
        verify_request = {
            "agent_token": agent_token
        }

        response = await client.post(
            f"{base_url}/network/verify-token",
            json=verify_request
        )
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {data}")
        assert response.status_code == 200
        assert data["valid"] is True
        assert data["token_info"]["payment_mandate_id"] == "pm_test_001"

        print("\n✅ すべてのテストが成功しました！")


if __name__ == "__main__":
    asyncio.run(test_payment_network())
