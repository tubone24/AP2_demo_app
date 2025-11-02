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
from fastapi import HTTPException, Header

# 親ディレクトリを追加
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from v2.common.base_agent import BaseAgent, AgentPassphraseManager
from v2.common.models import A2AMessage, ProcessPaymentRequest, ProcessPaymentResponse
from v2.common.database import DatabaseManager, TransactionCRUD
from v2.common.user_authorization import verify_user_authorization_vp, compute_mandate_hash
from v2.common.auth import verify_access_token
from v2.common.logger import get_logger, log_a2a_message, log_database_operation, LoggingAsyncClient
from v2.common.telemetry import get_tracer, create_http_span, is_telemetry_enabled

# Payment Processor ユーティリティモジュール
from services.payment_processor.utils import JWTHelpers, MandateHelpers

logger = get_logger(__name__, service_name='payment_processor')
tracer = get_tracer(__name__)


# ========================================
# 定数定義
# ========================================

# HTTP Timeout設定（秒）
HTTP_CLIENT_TIMEOUT = 30.0  # HTTPクライアント全体のタイムアウト
SHORT_HTTP_TIMEOUT = 10.0  # 短い通信のタイムアウト

# AP2ステータス定数
STATUS_CAPTURED = "captured"
STATUS_FAILED = "failed"


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

        # データベースマネージャー（環境変数から読み込み、絶対パスを使用）
        import os
        database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:////app/v2/data/payment_processor.db")
        self.db_manager = DatabaseManager(database_url=database_url)

        # HTTPクライアント（Credential Providerとの通信用）
        # AP2完全準拠: LoggingAsyncClientで全HTTP通信をログ記録
        self.http_client = LoggingAsyncClient(
            logger=logger,
            timeout=HTTP_CLIENT_TIMEOUT
        )

        # Credential Providerエンドポイント（Docker Compose環境想定）
        self.credential_provider_url = "http://credential_provider:8003"

        # 領収書送信を有効化するかどうか（環境変数で制御可能）
        import os
        self.enable_receipt_notification = os.getenv("ENABLE_RECEIPT_NOTIFICATION", "true").lower() == "true"

        # ヘルパークラスの初期化
        self.jwt_helpers = JWTHelpers(key_manager=self.key_manager)
        self.mandate_helpers = MandateHelpers()

        # 起動イベントハンドラー登録
        @self.app.on_event("startup")
        async def startup_event():
            """起動時の初期化処理"""
            logger.info(f"[{self.agent_name}] Running startup tasks...")

            # データベース初期化
            await self.db_manager.init_db()
            logger.info(f"[{self.agent_name}] Database initialized")

        logger.info(f"[{self.agent_name}] Initialized")

    def get_ap2_roles(self) -> list[str]:
        """AP2でのロールを返す"""
        return ["payment-processor"]

    def get_agent_description(self) -> str:
        """エージェントの説明を返す"""
        return "Payment Processor for AP2 Protocol - handles payment processing, transaction management, and receipt generation"

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

        # ========================================
        # W3C DID仕様準拠: DIDドキュメント公開エンドポイント
        # ========================================

        @self.app.get("/.well-known/did.json")
        async def get_did_document():
            """
            GET /.well-known/did.json - DIDドキュメント取得

            W3C DID仕様準拠:
            - DIDドキュメントをHTTP経由で公開
            - リモート解決を可能にする（Docker内部DNS対応）
            - 公開鍵の検証に使用

            AP2プロトコル要件:
            - 各エージェントのDIDを公開し、相互運用性を向上
            - did:ap2:agent:payment_processor → http://payment_processor:8004/.well-known/did.json
            """
            import json
            from pathlib import Path

            # DIDドキュメントファイルパスを解決
            did_docs_dir = Path("/app/v2/data/did_documents")
            did_doc_file = did_docs_dir / "payment_processor_did.json"

            if not did_doc_file.exists():
                logger.error(f"[get_did_document] DID document not found: {did_doc_file}")
                raise HTTPException(
                    status_code=404,
                    detail="DID document not found"
                )

            # DIDドキュメントを読み込んで返却
            try:
                did_doc = json.loads(did_doc_file.read_text())
                logger.debug(f"[get_did_document] Returning DID document: {did_doc.get('id')}")
                return did_doc
            except Exception as e:
                logger.error(f"[get_did_document] Failed to read DID document: {e}")
                raise HTTPException(
                    status_code=500,
                    detail="Failed to read DID document"
                )

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
                cart_mandate = request.cart_mandate  # VDC交換：CartMandateを取得
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

                # ===== レスポンス生成 =====
                if result["status"] == STATUS_CAPTURED:
                    # レシート生成（PDF形式、VDC交換によりCartMandateを渡す）
                    receipt_url = await self._generate_receipt(transaction_id, payment_mandate, cart_mandate)

                    return ProcessPaymentResponse(
                        transaction_id=transaction_id,
                        status=STATUS_CAPTURED,
                        receipt_url=receipt_url
                    )
                else:
                    return ProcessPaymentResponse(
                        transaction_id=transaction_id,
                        status=STATUS_FAILED,
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
        async def get_receipt_pdf(
            transaction_id: str,
            authorization: str = Header(None)
        ):
            """
            GET /receipts/{transaction_id}.pdf - 領収書PDFダウンロード（AP2完全準拠）

            AP2セキュリティ要件：
            - JWT認証必須（Authorizationヘッダー: Bearer <JWT>）
            - トランザクション所有者のみアクセス可能
            - JWT内のuser_id（payer_id）とトランザクションのpayer_idが一致する必要あり

            Args:
                transaction_id: トランザクションID
                authorization: Authorizationヘッダー（Bearer JWT）

            Returns:
                FileResponse: 領収書PDFファイル

            Raises:
                HTTPException:
                    - 401: JWT認証失敗
                    - 403: トランザクション所有者でない
                    - 404: 領収書が見つからない
            """
            try:
                from fastapi.responses import FileResponse
                from common.database import ReceiptCRUD

                # 1. JWT認証（AP2完全準拠）
                if not authorization or not authorization.startswith("Bearer "):
                    raise HTTPException(
                        status_code=401,
                        detail="Missing or invalid Authorization header. Expected: Bearer <JWT>"
                    )

                jwt_token = authorization.replace("Bearer ", "")

                # 2. JWT検証（HTTP認証Layer 1のJWTを検証）
                token_data = verify_access_token(jwt_token)
                user_id_from_jwt = token_data.user_id

                if not user_id_from_jwt:
                    raise HTTPException(
                        status_code=401,
                        detail="Invalid JWT: missing user_id"
                    )

                logger.info(
                    f"[get_receipt_pdf] JWT verified for user_id: {user_id_from_jwt}, "
                    f"transaction_id: {transaction_id}"
                )

                # 3. 領収書の所有者検証（AP2完全準拠：セキュリティ）
                async with self.db_manager.get_session() as session:
                    receipt = await ReceiptCRUD.get_by_transaction_id(session, transaction_id)

                    if not receipt:
                        logger.warning(
                            f"[get_receipt_pdf] Receipt not found for transaction: {transaction_id}"
                        )
                        raise HTTPException(status_code=404, detail="Receipt not found")

                    # レシートのuser_idとJWT内のuser_idが一致するか確認
                    if receipt.user_id != user_id_from_jwt:
                        logger.warning(
                            f"[get_receipt_pdf] Access denied: JWT user_id={user_id_from_jwt}, "
                            f"receipt user_id={receipt.user_id}"
                        )
                        raise HTTPException(
                            status_code=403,
                            detail="Access denied: You do not own this receipt"
                        )

                # 4. 領収書ファイル取得
                receipts_dir = Path("/app/v2/data/receipts")
                receipt_file_path = receipts_dir / f"{transaction_id}.pdf"

                if not receipt_file_path.exists():
                    logger.warning(f"[get_receipt_pdf] Receipt file not found: {receipt_file_path}")
                    raise HTTPException(status_code=404, detail="Receipt file not found")

                logger.info(
                    f"[get_receipt_pdf] Access granted: user_id={user_id_from_jwt}, "
                    f"transaction_id={transaction_id}"
                )

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
        """
        PaymentMandateを受信（Shopping Agentから）

        AP2仕様準拠：
        - VDC交換の原則に従い、PaymentMandateとCartMandateを受信
        - CartMandateは領収書生成に必要
        """
        logger.info("[PaymentProcessor] Received PaymentMandate")
        payload = message.dataPart.payload

        # AP2完全準拠：VDC交換でPaymentMandateとCartMandateを取り出す
        # ペイロードは必ず {"payment_mandate": {...}, "cart_mandate": {...}} 形式
        if not isinstance(payload, dict):
            logger.error("[PaymentProcessor] Invalid payload format - must be dictionary")
            raise ValueError("Payload must be a dictionary containing payment_mandate and cart_mandate")

        payment_mandate = payload.get("payment_mandate")
        cart_mandate = payload.get("cart_mandate")

        if not payment_mandate:
            logger.error("[PaymentProcessor] Missing payment_mandate in payload")
            raise ValueError("Payload must contain 'payment_mandate' field")

        # AP2仕様準拠：PaymentMandate検証
        try:
            self._validate_payment_mandate(payment_mandate)
        except Exception as e:
            logger.error(f"[PaymentProcessor] PaymentMandate validation failed: {e}")
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "invalid_payment_mandate",
                    "error_message": str(e)
                }
            }

        # AP2仕様準拠：Mandate連鎖検証
        try:
            self._validate_mandate_chain(payment_mandate, cart_mandate)
        except Exception as e:
            logger.error(f"[PaymentProcessor] Mandate chain validation failed: {e}")
            return {
                "type": "ap2.errors.Error",
                "id": str(uuid.uuid4()),
                "payload": {
                    "error_code": "mandate_chain_broken",
                    "error_message": str(e)
                }
            }

        # 決済処理実行
        transaction_id = f"txn_{uuid.uuid4().hex[:12]}"
        result = await self._process_payment_mock(transaction_id, payment_mandate)

        # トランザクション保存
        await self._save_transaction(transaction_id, payment_mandate, result)

        # ===== レスポンス生成 =====
        if result["status"] == STATUS_CAPTURED:
            receipt_url = await self._generate_receipt(transaction_id, payment_mandate, cart_mandate)

            # AP2 Step 29: Credential Providerに領収書を送信
            if self.enable_receipt_notification:
                await self._send_receipt_to_credential_provider(
                    transaction_id=transaction_id,
                    receipt_url=receipt_url,
                    payer_id=payment_mandate.get("payer_id"),
                    payment_mandate=payment_mandate
                )

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

    def _base64url_decode(self, data: str) -> bytes:
        """Base64urlデコード（ヘルパーメソッドに委譲）"""
        return self.jwt_helpers.base64url_decode(data)

    def _parse_jwt_parts(self, jwt_string: str) -> tuple[Dict[str, Any], Dict[str, Any], str, str, str]:
        """JWTパース（ヘルパーメソッドに委譲）"""
        return self.jwt_helpers.parse_jwt_parts(jwt_string)

    def _validate_jwt_header(self, header: Dict[str, Any]) -> None:
        """JWTヘッダー検証（ヘルパーメソッドに委譲）"""
        self.jwt_helpers.validate_jwt_header(header)

    def _validate_jwt_payload(self, payload: Dict[str, Any], expected_audience: str = "did:ap2:agent:payment_processor") -> None:
        """JWTペイロード検証（ヘルパーメソッドに委譲）"""
        self.jwt_helpers.validate_jwt_payload(payload, expected_audience)

    def _validate_merchant_jwt_payload(self, payload: Dict[str, Any], expected_audience: str = "did:ap2:agent:payment_processor") -> None:
        """Merchant JWTペイロード検証（ヘルパーメソッドに委譲）"""
        self.jwt_helpers.validate_merchant_jwt_payload(payload, expected_audience)

    def _verify_jwt_signature(self, header: Dict[str, Any], header_b64: str, payload_b64: str, signature_b64: str) -> None:
        """JWT署名検証（ヘルパーメソッドに委譲）"""
        self.jwt_helpers.verify_jwt_signature(header, header_b64, payload_b64, signature_b64)

    def _validate_payment_mandate(self, payment_mandate: Dict[str, Any]):
        """PaymentMandate検証（ヘルパーメソッドに委譲）"""
        self.mandate_helpers.validate_payment_mandate(payment_mandate)

    def _verify_user_authorization_jwt(self, user_authorization_jwt: str) -> Dict[str, Any]:
        """
        user_authorization JWTを検証

        JWT構造（AP2仕様準拠）:
        - Header: { "alg": "ES256", "kid": "did:ap2:user:xxx#key-1", "typ": "JWT" }
        - Payload: transaction_dataを含むクレーム

        Args:
            user_authorization_jwt: JWT文字列

        Returns:
            Dict[str, Any]: デコードされたペイロード

        Raises:
            ValueError: JWT検証失敗時
        """
        try:
            # 1. JWTを分解してheader、payloadを取得
            header, payload, header_b64, payload_b64, signature_b64 = self._parse_jwt_parts(user_authorization_jwt)

            # 2. Header検証
            self._validate_jwt_header(header)

            # 3. Payload検証
            self._validate_jwt_payload(payload)

            # 4. 署名検証
            self._verify_jwt_signature(header, header_b64, payload_b64, signature_b64)

            # 5. 検証成功ログ
            transaction_data = payload.get("transaction_data", {})
            logger.info(
                f"[_verify_user_authorization_jwt] JWT validation passed: "
                f"iss={payload.get('iss')}, exp={payload.get('exp')}, "
                f"cart_hash={transaction_data.get('cart_mandate_hash', 'N/A')[:16]}..., "
                f"payment_hash={transaction_data.get('payment_mandate_hash', 'N/A')[:16]}..."
            )

            return payload

        except Exception as e:
            logger.error(f"[_verify_user_authorization_jwt] Verification failed: {e}", exc_info=True)
            raise ValueError(f"user_authorization JWT verification failed: {e}")
    def _verify_merchant_authorization_jwt(self, merchant_authorization_jwt: str) -> Dict[str, Any]:
        """
        merchant_authorization JWTを検証

        JWT構造（AP2仕様準拠）:
        - Header: { "alg": "ES256", "kid": "did:ap2:merchant:xxx#key-1", "typ": "JWT" }
        - Payload: {
            "iss": "did:ap2:merchant:xxx",
            "sub": "did:ap2:merchant:xxx",
            "aud": "did:ap2:agent:payment_processor",
            "iat": <timestamp>,
            "exp": <timestamp>,
            "jti": <unique_id>,
            "cart_hash": "<cart_contents_hash>"
          }
        - Signature: ECDSA署名

        検証項目：
        1. JWT形式の検証（header.payload.signature）
        2. Base64url デコード
        3. Header検証（alg, kid, typ）
        4. Payload検証（iss, sub, aud, iat, exp, jti, cart_hash）
        5. 署名検証（ES256: ECDSA with P-256 and SHA-256）

        Args:
            merchant_authorization_jwt: JWT文字列

        Returns:
            Dict[str, Any]: デコードされたペイロード

        Raises:
            ValueError: JWT検証失敗時
        """
        try:
            # 1. JWTを分解してheader、payloadを取得
            header, payload, header_b64, payload_b64, signature_b64 = self._parse_jwt_parts(merchant_authorization_jwt)

            # 2. Header検証
            self._validate_jwt_header(header)

            # 3. Payload検証（merchant特有）
            self._validate_merchant_jwt_payload(payload)

            # 4. 署名検証
            self._verify_jwt_signature(header, header_b64, payload_b64, signature_b64)

            # 5. 検証成功ログ
            cart_hash = payload.get("cart_hash", "")
            logger.info(
                f"[_verify_merchant_authorization_jwt] JWT validation passed: "
                f"iss={payload.get('iss')}, exp={payload.get('exp')}, "
                f"jti={payload.get('jti', '')[:16]}..., "
                f"cart_hash={cart_hash[:16]}..."
            )

            return payload

        except Exception as e:
            logger.error(f"[_verify_merchant_authorization_jwt] Verification failed: {e}", exc_info=True)
            raise ValueError(f"merchant_authorization JWT verification failed: {e}")

    def _validate_mandate_chain(
        self,
        payment_mandate: Dict[str, Any],
        cart_mandate: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        AP2仕様準拠のMandate連鎖検証

        AP2仕様では、以下の連鎖が必須：
        IntentMandate → CartMandate → PaymentMandate

        検証項目：
        1. PaymentMandateがCartMandateを正しく参照している
        2. CartMandateがIntentMandateを正しく参照している（オプション）
        3. 各Mandateのハッシュ整合性
        4. 署名検証（merchant_authorization、user_authorization）

        Args:
            payment_mandate: PaymentMandate
            cart_mandate: CartMandate（VDC交換で受け取る）

        Returns:
            bool: 検証成功時True

        Raises:
            ValueError: 検証失敗時
        """
        # 1. CartMandateは必須（AP2仕様）
        if not cart_mandate:
            raise ValueError(
                "AP2 specification violation: CartMandate is required for PaymentMandate validation. "
                "VDC exchange principle requires CartMandate to be provided by Shopping Agent."
            )

        # 2. PaymentMandateがCartMandateを正しく参照しているか
        cart_mandate_id_in_payment = payment_mandate.get("cart_mandate_id")
        # AP2準拠：CartMandate.contents.idから取得
        cart_mandate_id = cart_mandate.get("contents", {}).get("id")

        if cart_mandate_id_in_payment != cart_mandate_id:
            raise ValueError(
                f"AP2 specification violation: PaymentMandate references cart_mandate_id={cart_mandate_id_in_payment}, "
                f"but received CartMandate has id={cart_mandate_id}"
            )

        logger.info(
            f"[PaymentProcessor] Mandate chain validation: "
            f"PaymentMandate({payment_mandate.get('id')}) → "
            f"CartMandate({cart_mandate_id})"
        )

        # 3. user_authorization SD-JWT-VC検証（AP2仕様完全準拠）
        user_authorization = payment_mandate.get("user_authorization")
        if user_authorization:
            try:
                # CartMandateとPaymentMandateのハッシュを計算（AP2仕様準拠）
                cart_hash = compute_mandate_hash(cart_mandate)

                # PaymentMandateのハッシュ計算時はuser_authorizationを除外
                payment_mandate_for_hash = {k: v for k, v in payment_mandate.items() if k != "user_authorization"}
                payment_hash = compute_mandate_hash(payment_mandate_for_hash)

                logger.info(
                    f"[PaymentProcessor] Verifying SD-JWT-VC user_authorization: "
                    f"cart_hash={cart_hash[:16]}..., payment_hash={payment_hash[:16]}..."
                )

                # SD-JWT-VC形式のuser_authorizationを検証
                vp_result = verify_user_authorization_vp(
                    user_authorization=user_authorization,
                    expected_cart_hash=cart_hash,
                    expected_payment_hash=payment_hash,
                    expected_audience="did:ap2:agent:payment_processor"
                )

                logger.info(
                    f"[PaymentProcessor] ✓ SD-JWT-VC user_authorization verified: "
                    f"cart_hash_match=True, payment_hash_match=True, "
                    f"webauthn_signature_verified=True"
                )

                # WebAuthn署名の暗号学的検証は verify_user_authorization_vp() 内で完了
                # - VP内のIssuer JWTのcnf claimから公開鍵を抽出
                # - ECDSA署名検証（authenticatorData + SHA256(clientDataJSON)）

            except ValueError as e:
                logger.error(f"[PaymentProcessor] user_authorization SD-JWT-VC verification failed: {e}")
                raise ValueError(f"user_authorization SD-JWT-VC verification failed: {e}")
        else:
            logger.warning(
                "[PaymentProcessor] PaymentMandate does not have user_authorization. "
                "This is a spec violation, but continuing for demo purposes."
            )

        # 4. CartMandateのMerchant署名検証（merchant_authorization JWT）
        merchant_authorization = cart_mandate.get("merchant_authorization")
        if merchant_authorization:
            try:
                merchant_payload = self._verify_merchant_authorization_jwt(merchant_authorization)
                logger.info(
                    f"[PaymentProcessor] merchant_authorization JWT verified: "
                    f"iss={merchant_payload.get('iss')}"
                )

                # CartMandateハッシュの検証（JWTペイロード内のハッシュと実際のハッシュを比較）
                cart_hash_in_jwt = merchant_payload.get("cart_hash")
                if cart_hash_in_jwt:
                    logger.info(
                        f"[PaymentProcessor] CartMandate hash in merchant_authorization: "
                        f"{cart_hash_in_jwt[:16]}..."
                    )

                    # 実際のCartMandateハッシュを計算（RFC 8785準拠）
                    # compute_mandate_hashは既にグローバルにimportされている（v2.common.user_authorizationから）
                    actual_cart_hash = compute_mandate_hash(cart_mandate)

                    # ハッシュを比較
                    if actual_cart_hash != cart_hash_in_jwt:
                        raise ValueError(
                            f"CartMandate hash mismatch in merchant_authorization: "
                            f"JWT contains {cart_hash_in_jwt[:16]}..., "
                            f"but actual hash is {actual_cart_hash[:16]}..."
                        )

                    logger.info(
                        f"[PaymentProcessor] ✓ CartMandate hash verified (merchant_authorization): "
                        f"{actual_cart_hash[:16]}..."
                    )

            except ValueError as e:
                logger.error(f"[PaymentProcessor] merchant_authorization JWT verification failed: {e}")
                raise ValueError(f"merchant_authorization JWT verification failed: {e}")
        else:
            logger.warning(
                "[PaymentProcessor] CartMandate does not have merchant_authorization. "
                "This is acceptable for demo environments, but production requires merchant signature."
            )

        # 5. IntentMandateへの参照確認（オプション）
        intent_mandate_id_in_payment = payment_mandate.get("intent_mandate_id")
        intent_mandate_id_in_cart = cart_mandate.get("intent_mandate_id")

        if intent_mandate_id_in_payment and intent_mandate_id_in_cart:
            if intent_mandate_id_in_payment != intent_mandate_id_in_cart:
                raise ValueError(
                    f"AP2 specification violation: PaymentMandate references intent_mandate_id={intent_mandate_id_in_payment}, "
                    f"but CartMandate references intent_mandate_id={intent_mandate_id_in_cart}"
                )

            logger.info(
                f"[PaymentProcessor] Full mandate chain validated: "
                f"IntentMandate({intent_mandate_id_in_cart}) → "
                f"CartMandate({cart_mandate_id}) → "
                f"PaymentMandate({payment_mandate.get('id')})"
            )

        logger.info("[PaymentProcessor] Mandate chain validation passed")
        return True

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
            # OpenTelemetry 手動トレーシング: Credential Provider通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.credential_provider_url}/credentials/verify",
                **{
                    "credential_provider.operation": "verify_credential",
                    "credential_provider.payer_id": payer_id
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.credential_provider_url}/credentials/verify",
                    json={
                        "token": token,
                        "payer_id": payer_id,
                        "amount": amount
                    },
                    timeout=SHORT_HTTP_TIMEOUT
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)
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

    async def _send_receipt_to_credential_provider(
        self,
        transaction_id: str,
        receipt_url: str,
        payer_id: str,
        payment_mandate: Dict[str, Any]
    ):
        """
        Credential Providerに領収書を送信

        AP2 Step 29対応: Payment ProcessorがCredential Providerに領収書通知を送信

        Args:
            transaction_id: トランザクションID
            receipt_url: 領収書URL
            payer_id: 支払者ID
            payment_mandate: PaymentMandate
        """
        try:
            logger.info(
                f"[PaymentProcessor] Sending receipt notification to Credential Provider: "
                f"transaction_id={transaction_id}, payer_id={payer_id}"
            )

            # Credential ProviderにPOST /receiptsで領収書通知
            # OpenTelemetry 手動トレーシング: Credential Provider通信
            with create_http_span(
                tracer,
                "POST",
                f"{self.credential_provider_url}/receipts",
                **{
                    "credential_provider.operation": "send_receipt",
                    "credential_provider.transaction_id": transaction_id,
                    "credential_provider.payer_id": payer_id
                }
            ) as span:
                response = await self.http_client.post(
                    f"{self.credential_provider_url}/receipts",
                    json={
                        "transaction_id": transaction_id,
                        "receipt_url": receipt_url,
                        "payer_id": payer_id,
                        "amount": payment_mandate.get("amount"),
                        "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
                    },
                    timeout=SHORT_HTTP_TIMEOUT
                )
                response.raise_for_status()
                span.set_attribute("http.status_code", response.status_code)

            logger.info(
                f"[PaymentProcessor] Receipt notification sent successfully: "
                f"transaction_id={transaction_id}, status={response.status_code}"
            )

        except httpx.HTTPError as e:
            # 領収書送信失敗は致命的エラーではないので、ログのみ出力
            logger.warning(
                f"[PaymentProcessor] Failed to send receipt to Credential Provider: {e}. "
                f"Continuing with payment process."
            )
        except Exception as e:
            logger.warning(
                f"[PaymentProcessor] Unexpected error while sending receipt: {e}. "
                f"Continuing with payment process."
            )

    async def _generate_receipt(
        self,
        transaction_id: str,
        payment_mandate: Dict[str, Any],
        cart_mandate: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        レシート生成（実際のPDF生成）

        AP2仕様準拠：
        - VDC交換の原則に従い、CartMandateは引数として受け取る
        - データベースからではなく、暗号的に署名されたVDCを直接使用

        Args:
            transaction_id: トランザクションID
            payment_mandate: PaymentMandate（最小限のペイロード）
            cart_mandate: CartMandate（注文詳細、領収書生成に必要）

        Returns:
            str: 領収書PDF URL
        """
        try:
            # receipt_generatorをインポート
            from v2.common.receipt_generator import generate_receipt_pdf

            # トランザクション結果を取得（_process_payment_mockの結果から）
            async with self.db_manager.get_session() as session:
                transaction = await TransactionCRUD.get_by_id(session, transaction_id)
                if not transaction:
                    logger.error(f"[PaymentProcessor] Transaction not found for receipt generation: {transaction_id}")
                    raise ValueError(f"Transaction not found: {transaction_id}")

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

            # AP2仕様準拠：CartMandateは必須
            # VDC交換の原則：Shopping AgentからCartMandateを受け取る
            # CartMandateにはMerchant署名とIntent参照が含まれており、取引の正当性を保証する重要なデータ
            if not cart_mandate:
                error_msg = (
                    f"AP2 specification violation: CartMandate not provided. "
                    f"CartMandate with Merchant signature is required for all transactions. "
                    f"VDC exchange principle: CartMandate must be passed from Shopping Agent."
                )
                logger.error(f"[PaymentProcessor] {error_msg}")
                raise ValueError(error_msg)

            # トランザクション結果を整形（receipt_generator.generate_receipt_pdf用）
            transaction_result = {
                "id": transaction_id,
                "status": payment_result.get("status", "captured"),
                "authorized_at": payment_result.get("authorized_at", "N/A"),
                "captured_at": payment_result.get("captured_at", "N/A")
            }

            # ユーザー名を生成（AP2完全準拠：マイクロサービスの独立性を保つ）
            # AP2仕様: PaymentMandateにユーザー名は含まれない
            # 各サービスは独立したDBを持つため、payer_idから表示名を生成
            import os
            payer_id = payment_mandate.get("payer_id") or os.getenv("DEFAULT_USER_ID", "user_demo_001")
            user_name = f"User {payer_id[:8]}" if payer_id.startswith("usr_") else "Demo User"

            logger.info(f"[PaymentProcessor] Generated user name for receipt: {user_name} (payer_id: {payer_id})")

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

            # URLを生成（ブラウザからアクセス可能なlocalhost URL）
            # Docker環境ではホストマシンのlocalhostからポート8004でアクセス可能
            receipt_url = f"http://localhost:8004/receipts/{transaction_id}.pdf"

            # データベースにレシートレコードを保存（AP2完全準拠）
            try:
                from v2.common.database import ReceiptCRUD
                async with self.db_manager.get_session() as session:
                    receipt_data = {
                        "id": f"receipt_{transaction_id}",
                        "user_id": payer_id,
                        "transaction_id": transaction_id,
                        "receipt_url": receipt_url,
                        "amount_value": int(payment_result.get("amount", {}).get("value", 0) * 100),  # cents
                        "currency": payment_result.get("amount", {}).get("currency", "JPY")
                    }
                    await ReceiptCRUD.create(session, receipt_data)
                    logger.info(f"[PaymentProcessor] Receipt record saved to database: {transaction_id}")
            except Exception as db_error:
                logger.error(f"[PaymentProcessor] Failed to save receipt to database: {db_error}", exc_info=True)

            return receipt_url

        except Exception as e:
            logger.error(f"[_generate_receipt] Failed to generate PDF receipt: {e}", exc_info=True)
            # AP2完全準拠: 領収書生成失敗時は例外を再スロー
            raise ValueError(f"Receipt generation failed for transaction {transaction_id}: {str(e)}") from e
