"""
v2/common/a2a_handler.py

A2Aメッセージの処理・署名検証・ルーティング
既存のap2_crypto.pyを再利用しつつ、FastAPI向けに最適化
"""

import sys
from pathlib import Path
from typing import Callable, Dict, Any, Optional
from datetime import datetime, timezone
import uuid
import logging

# v2の暗号化モジュールとモデルをインポート
from v2.common.crypto import SignatureManager, KeyManager
from v2.common.models import A2AMessage, A2AMessageHeader, A2ADataPart, A2ASignature, Signature

logger = logging.getLogger(__name__)


class A2AMessageHandler:
    """
    A2Aメッセージ処理クラス

    全エージェントで共通使用される：
    - メッセージの署名検証
    - メッセージのルーティング（@typeに基づく）
    - レスポンスメッセージの生成・署名
    """

    def __init__(
        self,
        agent_id: str,
        key_manager: KeyManager,
        signature_manager: SignatureManager
    ):
        """
        Args:
            agent_id: このエージェントのDID (e.g., "did:ap2:agent:shopping_agent")
            key_manager: 鍵管理インスタンス
            signature_manager: 署名管理インスタンス
        """
        self.agent_id = agent_id
        self.key_manager = key_manager
        self.signature_manager = signature_manager

        # @typeごとのハンドラーを登録
        self._handlers: Dict[str, Callable] = {}

    def register_handler(self, data_type: str, handler: Callable):
        """
        特定の@typeに対するハンドラーを登録

        Args:
            data_type: データタイプ (e.g., "ap2/IntentMandate")
            handler: 処理関数 (message: A2AMessage) -> Dict[str, Any]
        """
        self._handlers[data_type] = handler
        logger.info(f"[A2AHandler] Registered handler for @type: {data_type}")

    async def verify_message_signature(self, message: A2AMessage) -> bool:
        """
        A2Aメッセージの署名を検証

        Args:
            message: 検証するA2Aメッセージ

        Returns:
            bool: 署名が有効な場合True
        """
        if not message.header.signature:
            logger.warning("[A2AHandler] メッセージに署名がありません")
            return False

        try:
            # Pydanticモデルを辞書に変換（署名検証用）
            message_dict = message.model_dump(by_alias=True)

            # Signatureオブジェクトに変換（ap2_crypto用）
            sig = message.header.signature
            signature_obj = Signature(
                algorithm=sig.algorithm.upper(),
                value=sig.value,
                public_key=sig.public_key,
                signed_at=message.header.timestamp
            )

            # 署名検証（ap2_crypto.SignatureManagerを使用）
            is_valid = self.signature_manager.verify_a2a_message_signature(
                message_dict,
                signature_obj
            )

            if is_valid:
                logger.info(f"[A2AHandler] 署名検証成功: sender={message.header.sender}")
            else:
                logger.warning(f"[A2AHandler] 署名検証失敗: sender={message.header.sender}")

            return is_valid

        except Exception as e:
            logger.error(f"[A2AHandler] 署名検証エラー: {e}", exc_info=True)
            return False

    async def handle_message(self, message: A2AMessage) -> Dict[str, Any]:
        """
        A2Aメッセージを処理

        1. 署名検証
        2. recipient確認
        3. @typeに基づくハンドラー呼び出し

        Args:
            message: 処理するA2Aメッセージ

        Returns:
            Dict[str, Any]: 処理結果のペイロード

        Raises:
            ValueError: 検証失敗時
        """
        # 1. 署名検証
        if not await self.verify_message_signature(message):
            raise ValueError("Invalid message signature")

        # 2. recipient確認
        if message.header.recipient != self.agent_id:
            raise ValueError(
                f"Message recipient mismatch: "
                f"expected={self.agent_id}, got={message.header.recipient}"
            )

        # 3. @typeに基づくハンドラー呼び出し
        data_type = message.dataPart.type
        handler = self._handlers.get(data_type)

        if not handler:
            raise ValueError(f"No handler registered for @type: {data_type}")

        logger.info(
            f"[A2AHandler] Processing message: "
            f"type={data_type}, from={message.header.sender}"
        )

        # ハンドラー実行
        result = await handler(message)
        return result

    def create_response_message(
        self,
        recipient: str,
        data_type: str,
        data_id: str,
        payload: Dict[str, Any],
        sign: bool = True
    ) -> A2AMessage:
        """
        レスポンスA2Aメッセージを作成

        Args:
            recipient: 送信先エージェントDID
            data_type: データタイプ (e.g., "ap2/CartMandate")
            data_id: データID
            payload: ペイロード
            sign: 署名するか（デフォルトTrue）

        Returns:
            A2AMessage: 署名済みレスポンスメッセージ
        """
        # ヘッダー作成
        header = A2AMessageHeader(
            message_id=str(uuid.uuid4()),
            sender=self.agent_id,
            recipient=recipient,
            timestamp=datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            schema_version="0.2"
        )

        # DataPart作成
        data_part = A2ADataPart(
            type=data_type,
            id=data_id,
            payload=payload
        )

        # メッセージ作成
        message = A2AMessage(header=header, dataPart=data_part)

        # 署名
        if sign:
            message_dict = message.model_dump(by_alias=True)

            # agent_idから鍵IDを抽出（例: did:ap2:agent:shopping_agent -> shopping_agent）
            key_id = self.agent_id.split(":")[-1]

            # 署名生成（ap2_crypto.SignatureManagerを使用）
            signature_obj = self.signature_manager.sign_a2a_message(message_dict, key_id)

            # Pydanticモデルに変換
            message.header.signature = A2ASignature(
                algorithm=signature_obj.algorithm.lower(),
                public_key=signature_obj.public_key,
                value=signature_obj.value
            )

        logger.info(
            f"[A2AHandler] Created response: "
            f"type={data_type}, to={recipient}, signed={sign}"
        )

        return message

    def create_error_response(
        self,
        recipient: str,
        error_code: str,
        error_message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> A2AMessage:
        """
        エラーレスポンスメッセージを作成

        Args:
            recipient: 送信先エージェントDID
            error_code: エラーコード
            error_message: エラーメッセージ
            details: 追加詳細情報

        Returns:
            A2AMessage: エラーメッセージ
        """
        payload = {
            "error_code": error_code,
            "error_message": error_message,
            "details": details or {}
        }

        return self.create_response_message(
            recipient=recipient,
            data_type="ap2/Error",
            data_id=str(uuid.uuid4()),
            payload=payload,
            sign=True
        )


def infer_recipient_from_mandate(mandate_payload: Dict[str, Any]) -> Optional[str]:
    """
    Mandateの内容から送信先エージェントを推測

    demo_app_v2.mdのrecipient推測機能に対応

    Args:
        mandate_payload: Mandateのペイロード

    Returns:
        Optional[str]: 推測された送信先DID
    """
    mandate_type = mandate_payload.get("type")

    # IntentMandate -> Merchant Agent（商品検索依頼）
    if mandate_type == "IntentMandate":
        return "did:ap2:agent:merchant_agent"

    # CartMandate（未署名） -> Merchant（署名依頼）
    elif mandate_type == "CartMandate":
        if not mandate_payload.get("merchant_signature"):
            return "did:ap2:merchant"
        # 署名済み -> ユーザー（承認依頼）
        else:
            # この場合はShopping Agentが直接ユーザーUIに返す
            return None

    # PaymentMandate -> Credential Provider（認証依頼）
    elif mandate_type == "PaymentMandate":
        return "did:ap2:agent:credential_provider"

    return None
