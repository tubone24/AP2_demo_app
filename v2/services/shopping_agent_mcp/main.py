"""
v2/services/shopping_agent_mcp/main.py

Shopping Agent MCP Server - データアクセスツール提供（AP2準拠）

MCP仕様準拠：
- MCPサーバーは「ツール」のみを提供（LLM推論なし）
- LangGraph側でLLMを使った推論とツール呼び出しをオーケストレーション

提供ツール（データアクセス専用）:
- build_intent_mandate: AP2準拠IntentMandate構築
- request_cart_candidates: Merchant AgentにA2Aメッセージ送信してカート候補取得
- select_and_sign_cart: ユーザーがカートを選択し、署名
- assess_payment_risk: リスク評価実行
- build_payment_mandate: AP2準拠PaymentMandate構築
- execute_payment: Payment Processorに決済依頼
"""

import os
import sys
from pathlib import Path

# パス設定（最優先）
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import json
import uuid
import uvicorn
import httpx
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta

from common.mcp_server import MCPServer
from common.database import DatabaseManager
from common.logger import get_logger
from common.a2a_handler import A2AMessageHandler
from common.risk_assessment import RiskAssessmentEngine
from common.telemetry import setup_telemetry, instrument_fastapi_app
from services.shopping_agent_mcp.utils import MandateBuilders, A2AHelpers

logger = get_logger(__name__, service_name='shopping_agent_mcp')

# グローバル設定
AGENT_ID = os.getenv("AGENT_ID", "did:ap2:agent:shopping_agent")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/shopping_agent.db")
MERCHANT_AGENT_URL = os.getenv("MERCHANT_AGENT_URL", "http://merchant_agent:8001")
PAYMENT_PROCESSOR_URL = os.getenv("PAYMENT_PROCESSOR_URL", "http://payment_processor:8004")

# データベース初期化
db_manager = DatabaseManager(DATABASE_URL)

# HTTPクライアント（A2A通信用）
http_client = httpx.AsyncClient(timeout=600.0)

# A2Aハンドラー初期化（起動時に遅延初期化）
a2a_handler: Optional[A2AMessageHandler] = None

# KeyManager初期化（グローバル）
key_manager: Optional['KeyManager'] = None

# リスク評価エンジン初期化（起動時に遅延初期化）
risk_engine: Optional[RiskAssessmentEngine] = None

# MCPサーバー初期化
mcp = MCPServer(
    server_name="shopping_agent_mcp",
    version="1.0.0"
)


@mcp.tool(
    name="build_intent_mandate",
    description="AP2準拠IntentMandate構築",
    input_schema={
        "type": "object",
        "properties": {
            "intent_data": {
                "type": "object",
                "description": "LLMが抽出したインテントデータ"
            },
            "session_data": {
                "type": "object",
                "description": "セッションデータ（user_id, session_id等）"
            }
        },
        "required": ["intent_data", "session_data"]
    }
)
async def build_intent_mandate(params: Dict[str, Any]) -> Dict[str, Any]:
    """AP2準拠IntentMandate構築

    Args:
        params: {"intent_data": {...}, "session_data": {...}}

    Returns:
        {"intent_mandate": {...}}  # 未署名
    """
    intent_data = params["intent_data"]
    session_data = params["session_data"]

    try:
        # AP2準拠IntentMandate構築（ヘルパーメソッドに委譲）
        intent_mandate = MandateBuilders.build_intent_mandate_structure(intent_data, session_data)
        return {"intent_mandate": intent_mandate}

    except Exception as e:
        logger.error(f"[build_intent_mandate] Error: {e}", exc_info=True)
        return {"error": str(e)}


@mcp.tool(
    name="request_cart_candidates",
    description="Merchant AgentにA2Aメッセージ送信してカート候補取得",
    input_schema={
        "type": "object",
        "properties": {
            "intent_mandate": {
                "type": "object",
                "description": "IntentMandate"
            },
            "shipping_address": {
                "type": "object",
                "description": "配送先住所（AP2準拠ContactAddress）"
            }
        },
        "required": ["intent_mandate"]
    }
)
async def request_cart_candidates(params: Dict[str, Any]) -> Dict[str, Any]:
    """Merchant AgentにA2Aメッセージ送信してカート候補取得

    Args:
        params: {"intent_mandate": {...}, "shipping_address": {...}}

    Returns:
        {"cart_candidates": [...]}
    """
    global a2a_handler

    intent_mandate = params["intent_mandate"]
    shipping_address = params.get("shipping_address")

    try:
        # A2Aハンドラーがstartup時に初期化されていることを確認
        if a2a_handler is None:
            raise RuntimeError("A2AMessageHandler not initialized. Server startup may have failed.")

        # A2Aメッセージペイロード作成（ヘルパーメソッドに委譲）
        payload = A2AHelpers.build_cart_request_payload(intent_mandate, shipping_address)

        # A2Aメッセージ作成（署名付き）
        message = a2a_handler.create_response_message(
            recipient="did:ap2:agent:merchant_agent",
            data_type="ap2.mandates.IntentMandate",
            data_id=intent_mandate["id"],
            payload=payload,
            sign=True
        )

        logger.info(
            f"[request_cart_candidates] Sending A2A message to Merchant Agent: "
            f"message_id={message.header.message_id}, intent_id={intent_mandate['id']}"
        )

        # Merchant AgentにA2Aメッセージ送信
        response = await http_client.post(
            f"{MERCHANT_AGENT_URL}/a2a/message",
            json=message.model_dump(),
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()

        response_data = response.json()

        # AP2/A2A仕様準拠: A2AMessageから dataPart.payload.cart_candidates を抽出
        # A2AMessage構造: {"header": {...}, "dataPart": {"type": "...", "payload": {...}}}
        data_part = response_data.get("dataPart", {})
        payload = data_part.get("payload", {})
        cart_candidates = payload.get("cart_candidates", [])

        logger.info(f"[request_cart_candidates] Received {len(cart_candidates)} cart candidates from A2A response")
        return {"cart_candidates": cart_candidates}

    except httpx.HTTPError as e:
        logger.error(f"[request_cart_candidates] HTTP error: {e}", exc_info=True)
        return {"error": f"Failed to request cart candidates: {e}"}
    except Exception as e:
        logger.error(f"[request_cart_candidates] Error: {e}", exc_info=True)
        return {"error": str(e)}


@mcp.tool(
    name="select_and_sign_cart",
    description="ユーザーがカートを選択し、署名",
    input_schema={
        "type": "object",
        "properties": {
            "cart_mandate": {
                "type": "object",
                "description": "選択されたCartMandate"
            },
            "user_signature": {
                "type": "object",
                "description": "ユーザー署名（Passkey）"
            }
        },
        "required": ["cart_mandate", "user_signature"]
    }
)
async def select_and_sign_cart(params: Dict[str, Any]) -> Dict[str, Any]:
    """ユーザーがカートを選択し、署名

    Args:
        params: {"cart_mandate": {...}, "user_signature": {...}}

    Returns:
        {"signed_cart_mandate": {...}}
    """
    cart_mandate = params["cart_mandate"]
    user_signature = params["user_signature"]

    try:
        # CartMandateにユーザー署名を追加（ヘルパーメソッドに委譲）
        signed_cart_mandate = A2AHelpers.add_user_signature_to_cart(cart_mandate, user_signature)
        return {"signed_cart_mandate": signed_cart_mandate}

    except Exception as e:
        logger.error(f"[select_and_sign_cart] Error: {e}", exc_info=True)
        return {"error": str(e)}


@mcp.tool(
    name="assess_payment_risk",
    description="リスク評価実行",
    input_schema={
        "type": "object",
        "properties": {
            "cart_mandate": {
                "type": "object",
                "description": "署名済みCartMandate"
            },
            "intent_mandate": {
                "type": "object",
                "description": "IntentMandate"
            },
            "payment_method": {
                "type": "object",
                "description": "支払い方法"
            }
        },
        "required": ["cart_mandate", "intent_mandate", "payment_method"]
    }
)
async def assess_payment_risk(params: Dict[str, Any]) -> Dict[str, Any]:
    """リスク評価実行

    Args:
        params: {"cart_mandate": {...}, "intent_mandate": {...}, "payment_method": {...}}

    Returns:
        {"risk_assessment": {...}}
    """
    global risk_engine

    cart_mandate = params["cart_mandate"]
    intent_mandate = params["intent_mandate"]
    payment_method = params["payment_method"]

    try:
        # リスク評価エンジンがstartup時に初期化されていることを確認
        if risk_engine is None:
            raise RuntimeError("RiskAssessmentEngine not initialized. Server startup may have failed.")

        # PaymentMandateモック作成（リスク評価用）
        payment_mandate_mock = {
            "cart_mandate": cart_mandate,
            "intent_mandate": intent_mandate,
            "payment_method": payment_method
        }

        # リスク評価実行
        risk_result = await risk_engine.assess_payment_mandate(payment_mandate_mock)

        logger.info(
            f"[assess_payment_risk] Risk assessed: score={risk_result['risk_score']}, "
            f"recommendation={risk_result['recommendation']}"
        )
        return {"risk_assessment": risk_result}

    except Exception as e:
        logger.error(f"[assess_payment_risk] Error: {e}", exc_info=True)
        return {"error": str(e)}


@mcp.tool(
    name="build_payment_mandate",
    description="AP2準拠PaymentMandate構築",
    input_schema={
        "type": "object",
        "properties": {
            "cart_mandate": {
                "type": "object",
                "description": "署名済みCartMandate"
            },
            "payment_method": {
                "type": "object",
                "description": "支払い方法"
            },
            "risk_assessment": {
                "type": "object",
                "description": "リスク評価結果"
            }
        },
        "required": ["cart_mandate", "payment_method", "risk_assessment"]
    }
)
async def build_payment_mandate(params: Dict[str, Any]) -> Dict[str, Any]:
    """AP2準拠PaymentMandate構築

    Args:
        params: {"cart_mandate": {...}, "payment_method": {...}, "risk_assessment": {...}}

    Returns:
        {"payment_mandate": {...}}
    """
    cart_mandate = params["cart_mandate"]
    payment_method = params["payment_method"]
    risk_assessment = params["risk_assessment"]

    try:
        # AP2準拠PaymentMandate構築（ヘルパーメソッドに委譲）
        payment_mandate = MandateBuilders.build_payment_mandate_structure(
            cart_mandate, payment_method, risk_assessment
        )
        return {"payment_mandate": payment_mandate}

    except Exception as e:
        logger.error(f"[build_payment_mandate] Error: {e}", exc_info=True)
        return {"error": str(e)}


@mcp.tool(
    name="execute_payment",
    description="Payment Processorに決済依頼",
    input_schema={
        "type": "object",
        "properties": {
            "payment_mandate": {
                "type": "object",
                "description": "PaymentMandate"
            }
        },
        "required": ["payment_mandate"]
    }
)
async def execute_payment(params: Dict[str, Any]) -> Dict[str, Any]:
    """Payment Processorに決済依頼

    Args:
        params: {"payment_mandate": {...}}

    Returns:
        {"payment_result": {...}}
    """
    payment_mandate = params["payment_mandate"]

    try:
        # Payment Processorに決済依頼
        response = await http_client.post(
            f"{PAYMENT_PROCESSOR_URL}/authorize",
            json=payment_mandate,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()

        payment_result = response.json()

        logger.info(
            f"[execute_payment] Payment executed: "
            f"status={payment_result.get('status')}, "
            f"transaction_id={payment_result.get('transaction_id')}"
        )
        return {"payment_result": payment_result}

    except httpx.HTTPError as e:
        logger.error(f"[execute_payment] HTTP error: {e}", exc_info=True)
        return {"error": f"Payment execution failed: {e}"}
    except Exception as e:
        logger.error(f"[execute_payment] Error: {e}", exc_info=True)
        return {"error": str(e)}


# Lifespan イベントハンドラー
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan イベントハンドラー（起動・シャットダウン処理）"""
    global a2a_handler, key_manager, risk_engine

    # Startup処理
    try:
        logger.info("[Shopping Agent MCP] Starting up...")

        # 1. データベース初期化
        await db_manager.init_db()
        logger.info("[Shopping Agent MCP] Database initialized")

        # 2. KeyManager初期化（グローバル）
        from common.crypto import KeyManager, SignatureManager
        keys_directory = os.getenv("AP2_KEYS_DIRECTORY", "/app/v2/keys")
        key_manager = KeyManager(keys_directory=keys_directory)
        passphrase = os.getenv("AP2_SHOPPING_AGENT_PASSPHRASE", "")
        logger.info(f"[Startup] KeyManager initialized with keys_directory={keys_directory}")

        # DIDからkey_idを抽出
        key_id = AGENT_ID.split(":")[-1]
        logger.info(f"[Startup] Extracted key_id={key_id} from AGENT_ID={AGENT_ID}")

        # 3. 秘密鍵をロード（ED25519優先、ECDSAフォールバック）
        try:
            # ED25519鍵をロード
            private_key_ed25519 = key_manager.load_private_key_encrypted(key_id, passphrase, algorithm="ED25519")
            logger.info(f"[Startup] ED25519 private key loaded for {key_id}")
        except Exception as e:
            logger.warning(f"[Startup] Failed to load ED25519 key: {e}")
            private_key_ed25519 = None

        try:
            # ECDSA鍵をロード（フォールバック）
            private_key_ecdsa = key_manager.load_private_key_encrypted(key_id, passphrase, algorithm="ECDSA")
            logger.info(f"[Startup] ECDSA private key loaded for {key_id}")
        except Exception as e:
            logger.warning(f"[Startup] Failed to load ECDSA key: {e}")
            private_key_ecdsa = None

        if not private_key_ed25519 and not private_key_ecdsa:
            raise RuntimeError(f"No private keys found for {key_id}")

        # 4. SignatureManager初期化（KeyManagerと同じインスタンスを使用）
        signature_manager = SignatureManager(key_manager=key_manager)
        logger.info("[Startup] SignatureManager initialized")

        # 5. A2AMessageHandler初期化
        a2a_handler = A2AMessageHandler(
            agent_id=AGENT_ID,
            key_manager=key_manager,
            signature_manager=signature_manager
        )
        logger.info(f"[Startup] A2AMessageHandler initialized with key_id: {key_id}")

        # 6. RiskAssessmentEngine初期化
        risk_engine = RiskAssessmentEngine(db_manager=db_manager)
        logger.info("[Startup] RiskAssessmentEngine initialized")

        logger.info("[Shopping Agent MCP] Startup complete")

    except Exception as e:
        logger.error(f"[Shopping Agent MCP] Startup failed: {e}", exc_info=True)
        raise

    # yieldでリクエスト処理へ
    yield

    # Shutdown処理
    logger.info("[Shopping Agent MCP] Shutting down...")
    await http_client.aclose()
    logger.info("[Shopping Agent MCP] HTTP client closed")


# FastAPIアプリ（lifespan付き）
app = mcp.app
app.router.lifespan_context = lifespan

# OpenTelemetryセットアップ（Jaegerトレーシング）
service_name = os.getenv("OTEL_SERVICE_NAME", "shopping_agent_mcp")
setup_telemetry(service_name)

# FastAPI計装（AP2完全準拠：MCP通信の可視化）
instrument_fastapi_app(app)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8010,  # Shopping Agent MCP専用ポート
        reload=False,
        log_level="info"
    )
