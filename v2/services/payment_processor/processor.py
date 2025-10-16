"""
v2/services/payment_processor/processor.py

Payment Processor実装
- 決済処理（モック）
- トランザクション管理
- レシート生成
"""

import sys
import uuid
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import logging

from fastapi import HTTPException

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage, ProcessPaymentRequest, ProcessPaymentResponse
from v2.common.database import DatabaseManager, TransactionCRUD

logger = logging.getLogger(__name__)


class PaymentProcessorService(BaseAgent):
    """
    Payment Processor (MPP - Merchant Payment Processor)

    決済処理エンティティ
    - 支払い処理（モック）
    - トランザクション管理
    - レシート生成
    """

    def __init__(self):
        super().__init__(
            agent_id="did:ap2:agent:payment_processor",
            agent_name="Payment Processor",
            passphrase=AgentPassphraseManager.get_passphrase("payment_processor"),
            keys_directory="./keys"
        )

        # データベースマネージャー（絶対パスを使用）
        self.db_manager = DatabaseManager(database_url="sqlite+aiosqlite:////app/v2/data/ap2.db")

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Payment Processorが受信するA2Aメッセージ：
        - ap2/PaymentMandate: Shopping Agentからの支払い処理依頼
        """
        self.a2a_handler.register_handler("ap2/PaymentMandate", self.handle_payment_mandate)

    def register_endpoints(self):
        """
        Payment Processor固有エンドポイントの登録
        """

        @self.app.post("/process")
        async def process_payment(request: ProcessPaymentRequest):
            """
            POST /process - 支払い処理実行

            demo_app_v2.md:
            受注・支払い実行（モックでOK）

            リクエスト:
            {
              "payment_mandate": {...},
              "credential_token"?: "..."
            }

            レスポンス:
            {
              "transaction_id": "txn_xxx",
              "status": "authorized" | "captured" | "failed",
              "receipt_url"?: "...",
              "error"?: "..."
            }
            """
            try:
                payment_mandate = request.payment_mandate
                credential_token = request.credential_token

                # 1. PaymentMandateバリデーション
                self._validate_payment_mandate(payment_mandate)

                # 2. トランザクション作成
                transaction_id = f"txn_{uuid.uuid4().hex[:12]}"

                # 3. 決済処理（モック）
                result = await self._process_payment_mock(
                    transaction_id=transaction_id,
                    payment_mandate=payment_mandate,
                    credential_token=credential_token
                )

                # 4. トランザクション保存
                await self._save_transaction(
                    transaction_id=transaction_id,
                    payment_mandate=payment_mandate,
                    result=result
                )

                # 5. レスポンス生成
                if result["status"] == "captured":
                    # レシート生成（簡易版）
                    receipt_url = await self._generate_receipt(transaction_id, payment_mandate)

                    return ProcessPaymentResponse(
                        transaction_id=transaction_id,
                        status="captured",
                        receipt_url=receipt_url
                    )
                else:
                    return ProcessPaymentResponse(
                        transaction_id=transaction_id,
                        status="failed",
                        error=result.get("error", "Payment processing failed")
                    )

            except Exception as e:
                logger.error(f"[process_payment] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

        @self.app.get("/transactions/{transaction_id}")
        async def get_transaction(transaction_id: str):
            """
            GET /transactions/{id} - トランザクション取得
            """
            try:
                async with self.db_manager.get_session() as session:
                    transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                    if not transaction:
                        raise HTTPException(status_code=404, detail="Transaction not found")
                    return transaction.to_dict()

            except Exception as e:
                logger.error(f"[get_transaction] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

        @self.app.post("/refund")
        async def refund_transaction(refund_request: Dict[str, Any]):
            """
            POST /refund - 返金処理

            リクエスト:
            {
              "transaction_id": "txn_xxx",
              "amount"?: {...},  // 部分返金の場合
              "reason": "..."
            }
            """
            try:
                transaction_id = refund_request["transaction_id"]
                reason = refund_request.get("reason", "Customer requested refund")

                # トランザクション取得
                async with self.db_manager.get_session() as session:
                    transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                    if not transaction:
                        raise HTTPException(status_code=404, detail="Transaction not found")

                    # 返金処理（モック）
                    refund_id = f"refund_{uuid.uuid4().hex[:12]}"

                    # イベント追加
                    await TransactionCRUD.add_event(session, transaction_id, {
                        "type": "refund",
                        "refund_id": refund_id,
                        "reason": reason,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })

                return {
                    "refund_id": refund_id,
                    "transaction_id": transaction_id,
                    "status": "refunded",
                    "reason": reason
                }

            except Exception as e:
                logger.error(f"[refund_transaction] Error: {e}", exc_info=True)
                raise HTTPException(status_code=400, detail=str(e))

    # ========================================
    # A2Aメッセージハンドラー
    # ========================================

    async def handle_payment_mandate(self, message: A2AMessage) -> Dict[str, Any]:
        """PaymentMandateを受信（Shopping Agentから）"""
        logger.info("[PaymentProcessor] Received PaymentMandate")
        payment_mandate = message.dataPart.payload

        # 決済処理実行
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        result = await self._process_payment_mock(transaction_id, payment_mandate)

        # トランザクション保存
        await self._save_transaction(transaction_id, payment_mandate, result)

        # レスポンス
        if result["status"] == "captured":
            receipt_url = await self._generate_receipt(transaction_id, payment_mandate)

            return {
                "type": "ap2/PaymentResult",
                "id": str(uuid.uuid4()),
                "payload": {
                    "transaction_id": transaction_id,
                    "status": "captured",
                    "receipt_url": receipt_url
                }
            }
        else:
            return {
                "type": "ap2/Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "payment_failed",
                    "error_message": result.get("error", "Payment processing failed")
                }
            }

    # ========================================
    # 内部メソッド
    # ========================================

    def _validate_payment_mandate(self, payment_mandate: Dict[str, Any]):
        """PaymentMandateを検証"""
        required_fields = ["id", "amount", "payment_method", "payer_id", "payee_id"]
        for field in required_fields:
            if field not in payment_mandate:
                raise ValueError(f"Missing required field: {field}")

        logger.info(f"[PaymentProcessor] PaymentMandate validation passed: {payment_mandate['id']}")

    async def _process_payment_mock(
        self,
        transaction_id: str,
        payment_mandate: Dict[str, Any],
        credential_token: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        決済処理（モック）

        本番環境では実際の決済ゲートウェイ（Stripe, Square等）と統合
        """
        logger.info(f"[PaymentProcessor] Processing payment (mock): {transaction_id}")

        amount = payment_mandate.get("amount", {})
        payment_method = payment_mandate.get("payment_method", {})

        # モック処理：ランダムに成功/失敗を決定（実際は常に成功させる）
        import random
        success_rate = 0.95  # 95%成功

        if random.random() < success_rate:
            # 成功
            result = {
                "status": "captured",
                "transaction_id": transaction_id,
                "amount": amount,
                "payment_method": payment_method,
                "authorized_at": datetime.now(timezone.utc).isoformat(),
                "captured_at": datetime.now(timezone.utc).isoformat()
            }
            logger.info(f"[PaymentProcessor] Payment succeeded: {transaction_id}")
        else:
            # 失敗
            result = {
                "status": "failed",
                "transaction_id": transaction_id,
                "error": "Insufficient funds (mock error)"
            }
            logger.warning(f"[PaymentProcessor] Payment failed: {transaction_id}")

        return result

    async def _save_transaction(
        self,
        transaction_id: str,
        payment_mandate: Dict[str, Any],
        result: Dict[str, Any]
    ):
        """トランザクションをデータベースに保存"""
        async with self.db_manager.get_session() as session:
            await TransactionCRUD.create(session, {
                "id": transaction_id,
                "payment_id": payment_mandate.get("id"),
                "cart_id": payment_mandate.get("cart_mandate_id"),
                "intent_id": payment_mandate.get("intent_mandate_id"),
                "status": result["status"],
                "events": [
                    {
                        "type": "payment_processed",
                        "result": result,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                ]
            })

        logger.info(f"[PaymentProcessor] Transaction saved: {transaction_id}")

    async def _generate_receipt(
        self,
        transaction_id: str,
        payment_mandate: Dict[str, Any]
    ) -> str:
        """
        レシート生成

        簡易版：レシートURLを返す
        本番環境では既存のreceipt_generator.pyを使用してPDF生成
        """
        # レシートURL（モック）
        receipt_url = f"https://receipts.ap2-demo.com/{transaction_id}.pdf"

        logger.info(f"[PaymentProcessor] Generated receipt: {receipt_url}")

        return receipt_url
