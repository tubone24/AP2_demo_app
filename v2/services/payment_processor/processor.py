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

import httpx
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

        # HTTPクライアント（Credential Providerとの通信用）
        self.http_client = httpx.AsyncClient(timeout=30.0)

        # Credential Providerエンドポイント（Docker Compose環境想定）
        self.credential_provider_url = "http://credential_provider:8003"

        logger.info(f"[{self.agent_name}] Initialized")

    def register_a2a_handlers(self):
        """
        A2Aハンドラーの登録

        Payment Processorが受信するA2Aメッセージ：
        - ap2/PaymentMandate: Shopping Agentからの支払い処理依頼
        """
        self.a2a_handler.register_handler("ap2.mandates.PaymentMandate", self.handle_payment_mandate)

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
                    # レシート生成（PDF形式）
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

        @self.app.get("/receipts/{transaction_id}.pdf")
        async def get_receipt_pdf(transaction_id: str):
            """
            GET /receipts/{transaction_id}.pdf - 領収書PDFダウンロード

            領収書PDFファイルを返却する
            """
            try:
                from fastapi.responses import FileResponse

                receipts_dir = Path("/app/v2/data/receipts")
                receipt_file_path = receipts_dir / f"{transaction_id}.pdf"

                if not receipt_file_path.exists():
                    logger.warning(f"[get_receipt_pdf] Receipt not found: {receipt_file_path}")
                    raise HTTPException(status_code=404, detail="Receipt not found")

                return FileResponse(
                    path=str(receipt_file_path),
                    media_type="application/pdf",
                    filename=f"receipt_{transaction_id}.pdf"
                )

            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"[get_receipt_pdf] Error: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))

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
                "type": "ap2.responses.PaymentResult",
                "id": str(uuid.uuid4()),
                "payload": {
                    "transaction_id": transaction_id,
                    "status": "captured",
                    "receipt_url": receipt_url
                }
            }
        else:
            return {
                "type": "ap2.errors.Error",
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

        AP2仕様準拠（Step 26-27）：
        1. PaymentMandateからトークンを抽出
        2. Credential Providerにトークン検証・認証情報要求
        3. 検証成功後、決済処理を実行

        本番環境では実際の決済ゲートウェイ（Stripe, Square等）と統合
        """
        logger.info(f"[PaymentProcessor] Processing payment (mock): {transaction_id}")

        amount = payment_mandate.get("amount", {})
        payment_method = payment_mandate.get("payment_method", {})

        # AP2 Step 26-27: Credential Providerにトークン検証を依頼
        token = payment_method.get("token")
        if not token:
            logger.error(f"[PaymentProcessor] No token found in payment_method")
            return {
                "status": "failed",
                "transaction_id": transaction_id,
                "error": "No payment method token provided"
            }

        try:
            # Credential Providerにトークン検証・認証情報要求
            credential_info = await self._verify_credential_with_cp(
                token=token,
                payer_id=payment_mandate.get("payer_id"),
                amount=amount
            )

            logger.info(f"[PaymentProcessor] Credential verified: {credential_info.get('payment_method_id')}")

        except Exception as e:
            logger.error(f"[PaymentProcessor] Credential verification failed: {e}")
            return {
                "status": "failed",
                "transaction_id": transaction_id,
                "error": f"Credential verification failed: {str(e)}"
            }

        # AP2仕様準拠：リスクベース承認/拒否判定
        # PaymentMandateからリスク評価結果を取得
        risk_score = payment_mandate.get("risk_score", 0)
        fraud_indicators = payment_mandate.get("fraud_indicators", [])

        logger.info(f"[PaymentProcessor] Risk assessment: score={risk_score}, indicators={fraud_indicators}")

        # リスクスコアに基づく判定
        if risk_score > 80:
            # 高リスク：拒否
            logger.warning(f"[PaymentProcessor] Payment declined due to high risk score: {risk_score}")
            return {
                "status": "failed",
                "transaction_id": transaction_id,
                "error": f"Payment declined: High risk score ({risk_score})",
                "risk_score": risk_score,
                "fraud_indicators": fraud_indicators
            }
        elif risk_score > 50:
            # 中リスク：通常は要確認だが、デモ環境では承認
            logger.info(f"[PaymentProcessor] Medium risk detected ({risk_score}), proceeding with authorization (demo mode)")

        # 承認・キャプチャ処理
        # 本番環境では実際の決済ゲートウェイ（Stripe, Square等）と統合
        result = {
            "status": "captured",
            "transaction_id": transaction_id,
            "amount": amount,
            "payment_method": payment_method,
            "payer_id": payment_mandate.get("payer_id"),
            "payee_id": payment_mandate.get("payee_id"),
            "cart_mandate_id": payment_mandate.get("cart_mandate_id"),
            "intent_mandate_id": payment_mandate.get("intent_mandate_id"),
            "authorized_at": datetime.now(timezone.utc).isoformat(),
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "credential_verified": True,  # AP2 Step 26-27で検証済み
            "risk_score": risk_score,
            "fraud_indicators": fraud_indicators
        }
        logger.info(f"[PaymentProcessor] Payment succeeded: {transaction_id}, amount={amount}, risk_score={risk_score}")

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

    async def _verify_credential_with_cp(
        self,
        token: str,
        payer_id: str,
        amount: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Credential Providerにトークン検証・認証情報要求

        AP2仕様準拠（Step 26-27）：
        1. Payment ProcessorがトークンをCredential Providerに送信
        2. Credential Providerがトークンを検証
        3. Credential Providerが認証情報（支払い方法の詳細）を返却
        """
        logger.info(f"[PaymentProcessor] Verifying credential with Credential Provider: token={token[:20]}...")

        try:
            # Credential ProviderにPOST /credentials/verifyでトークン検証依頼
            response = await self.http_client.post(
                f"{self.credential_provider_url}/credentials/verify",
                json={
                    "token": token,
                    "payer_id": payer_id,
                    "amount": amount
                },
                timeout=10.0
            )
            response.raise_for_status()
            result = response.json()

            # 検証結果を取得
            if not result.get("verified"):
                raise ValueError(f"Credential verification failed: {result.get('error', 'Unknown error')}")

            credential_info = result.get("credential_info", {})
            if not credential_info:
                raise ValueError("Credential Provider did not return credential_info")

            logger.info(f"[PaymentProcessor] Credential verification succeeded: payment_method_id={credential_info.get('payment_method_id')}")
            return credential_info

        except httpx.HTTPError as e:
            logger.error(f"[_verify_credential_with_cp] HTTP error: {e}")
            raise ValueError(f"Failed to verify credential with Credential Provider: {e}")
        except Exception as e:
            logger.error(f"[_verify_credential_with_cp] Error: {e}", exc_info=True)
            raise

    async def _generate_receipt(
        self,
        transaction_id: str,
        payment_mandate: Dict[str, Any]
    ) -> str:
        """
        レシート生成（実際のPDF生成）

        v2/common/receipt_generator.pyを使用してPDF領収書を生成し、
        ファイルシステムに保存して、アクセス可能なURLを返す
        """
        try:
            # receipt_generatorをインポート
            from v2.common.receipt_generator import generate_receipt_pdf

            # トランザクション結果を取得（_process_payment_mockの結果から）
            async with self.db_manager.get_session() as session:
                transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                if not transaction:
                    logger.warning(f"[PaymentProcessor] Transaction not found for receipt generation: {transaction_id}")
                    # フォールバック: モックURL
                    return f"https://receipts.ap2-demo.com/{transaction_id}.pdf"

                transaction_dict = transaction.to_dict()

                # トランザクションイベントから決済結果を取得
                events = transaction_dict.get("events", [])
                payment_result = None
                for event in events:
                    if event.get("type") == "payment_processed":
                        payment_result = event.get("result", {})
                        break

                if not payment_result:
                    logger.warning(f"[PaymentProcessor] Payment result not found in transaction events")
                    return f"https://receipts.ap2-demo.com/{transaction_id}.pdf"

            # CartMandateを取得（payment_mandateにcart_mandate_idがある）
            cart_mandate_id = payment_mandate.get("cart_mandate_id")
            cart_mandate = None
            if cart_mandate_id:
                async with self.db_manager.get_session() as session:
                    from v2.common.database import MandateCRUD
                    import json
                    cart_mandate_record = await MandateCRUD.get_by_id(session, cart_mandate_id)
                    if cart_mandate_record:
                        # payloadがJSON文字列の場合はパース
                        if isinstance(cart_mandate_record.payload, str):
                            cart_mandate = json.loads(cart_mandate_record.payload)
                        else:
                            cart_mandate = cart_mandate_record.payload

            # CartMandateが取得できない場合は簡易版を作成
            if not cart_mandate:
                logger.warning(f"[PaymentProcessor] CartMandate not found, creating simplified version")
                amount = payment_mandate.get("amount", {})
                cart_mandate = {
                    "id": cart_mandate_id or "unknown",
                    "merchant_name": "Demo Merchant",
                    "merchant_id": payment_mandate.get("payee_id", "unknown"),
                    "items": [
                        {
                            "name": "商品",
                            "quantity": 1,
                            "unit_price": amount,
                            "total_price": amount
                        }
                    ],
                    "subtotal": amount,
                    "tax": {"value": "0", "currency": amount.get("currency", "JPY")},
                    "shipping": {
                        "cost": {"value": "0", "currency": amount.get("currency", "JPY")}
                    },
                    "total": amount
                }

            # トランザクション結果を整形（receipt_generator.generate_receipt_pdf用）
            transaction_result = {
                "id": transaction_id,
                "status": payment_result.get("status", "captured"),
                "authorized_at": payment_result.get("authorized_at", "N/A"),
                "captured_at": payment_result.get("captured_at", "N/A")
            }

            # ユーザー名を取得（AP2仕様準拠：payer_idからDBで取得）
            payer_id = payment_mandate.get("payer_id", "user_demo_001")
            user_name = "デモユーザー"  # フォールバック用デフォルト値

            try:
                from v2.common.database import UserCRUD
                async with self.db_manager.get_session() as session:
                    user = await UserCRUD.get_by_id(session, payer_id)
                    if user:
                        user_name = user.display_name
                        logger.info(f"[PaymentProcessor] Retrieved user name: {user_name} for payer_id: {payer_id}")
                    else:
                        logger.warning(f"[PaymentProcessor] User not found for payer_id: {payer_id}, using default name")
            except Exception as e:
                logger.warning(f"[PaymentProcessor] Failed to retrieve user name: {e}, using default name")

            # PDFを生成
            pdf_buffer = generate_receipt_pdf(
                transaction_result=transaction_result,
                cart_mandate=cart_mandate,
                payment_mandate=payment_mandate,
                user_name=user_name
            )

            # PDFをファイルシステムに保存
            import os
            receipts_dir = Path("/app/v2/data/receipts")
            receipts_dir.mkdir(parents=True, exist_ok=True)

            receipt_file_path = receipts_dir / f"{transaction_id}.pdf"
            with open(receipt_file_path, "wb") as f:
                f.write(pdf_buffer.getvalue())

            logger.info(f"[PaymentProcessor] Generated receipt PDF: {receipt_file_path}")

            # URLを生成（Docker環境でPayment Processorのエンドポイント経由でアクセス）
            receipt_url = f"http://payment_processor:8004/receipts/{transaction_id}.pdf"

            return receipt_url

        except Exception as e:
            logger.error(f"[_generate_receipt] Failed to generate PDF receipt: {e}", exc_info=True)
            # フォールバック: モックURL
            return f"https://receipts.ap2-demo.com/{transaction_id}.pdf"
