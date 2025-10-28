"""
v2/services/credential_provider/utils/receipt_helpers.py

レシート管理関連のヘルパーメソッド
"""

import logging
from typing import Dict, Any
from fastapi import HTTPException

from v2.common.database import ReceiptCRUD

logger = logging.getLogger(__name__)


class ReceiptHelpers:
    """レシート管理に関連するヘルパーメソッドを提供するクラス"""

    def __init__(self, db_manager):
        """
        Args:
            db_manager: データベースマネージャーのインスタンス
        """
        self.db_manager = db_manager

    async def receive_receipt(self, receipt_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        領収書受信

        AP2 Step 29対応: Payment Processorから領収書通知を受信

        Args:
            receipt_data: 領収書データ

        Returns:
            Dict: レスポンス

        Raises:
            HTTPException: 入力検証エラーまたは処理エラー
        """
        transaction_id = receipt_data.get("transaction_id")
        receipt_url = receipt_data.get("receipt_url")
        payer_id = receipt_data.get("payer_id")

        if not transaction_id or not receipt_url or not payer_id:
            raise HTTPException(
                status_code=400,
                detail="transaction_id, receipt_url, and payer_id are required"
            )

        # 領収書情報をDBに保存
        async with self.db_manager.get_session() as session:
            receipt = await ReceiptCRUD.create(session, {
                "user_id": payer_id,
                "transaction_id": transaction_id,
                "receipt_url": receipt_url,
                "amount": receipt_data.get("amount"),
                "payment_timestamp": receipt_data.get("timestamp")
            })

        logger.info(
            f"[CredentialProvider] Receipt received and stored to DB: "
            f"transaction_id={transaction_id}, payer_id={payer_id}, "
            f"receipt_url={receipt_url}"
        )

        return {
            "status": "received",
            "message": "Receipt stored successfully",
            "transaction_id": transaction_id
        }

    async def get_receipts(self, user_id: str) -> Dict[str, Any]:
        """
        ユーザーの領収書一覧取得

        Args:
            user_id: ユーザーID

        Returns:
            Dict: 領収書一覧

        Raises:
            HTTPException: 処理エラー
        """
        # DBから領収書を取得
        async with self.db_manager.get_session() as session:
            receipt_records = await ReceiptCRUD.get_by_user_id(session, user_id)
            receipts = [receipt.to_dict() for receipt in receipt_records]

        return {
            "user_id": user_id,
            "receipts": receipts,
            "total_count": len(receipts)
        }
