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
from v2.common.models import A2AMessage, A2AMessageHeader, A2ADataPart, A2ASignature, A2AProof, Signature
from v2.common.did_resolver import DIDResolver

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

        # DID解決機能（専門家の指摘対応：DIDベースの公開鍵解決）
        self.did_resolver = DIDResolver(key_manager)

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

        A2A仕様準拠：proof構造を優先的に使用、後方互換性のためsignatureもサポート

        専門家の指摘対応：
        1. algorithm（alg）の検証 - ECDSA/Ed25519のみ許可
        2. kid（鍵ID）の検証 - DID形式の確認
        3. timestamp検証 - ±300秒の許容範囲でリプレイ攻撃を防止
        4. nonce検証 - 一度使用されたnonceの再利用を防止

        Args:
            message: 検証するA2Aメッセージ

        Returns:
            bool: 署名が有効な場合True
        """
        from datetime import datetime, timezone, timedelta

        # proof構造を優先的に使用（A2A仕様準拠）
        if message.header.proof:
            try:
                proof = message.header.proof

                # 1. Algorithm検証（専門家の指摘）
                allowed_algorithms = ["ecdsa", "ed25519"]
                if proof.algorithm.lower() not in allowed_algorithms:
                    logger.error(
                        f"[A2AHandler] Invalid algorithm: {proof.algorithm}. "
                        f"Allowed: {allowed_algorithms}"
                    )
                    return False

                # 2. KID検証（専門家の指摘）
                if proof.kid:
                    # kidがDID形式（did:ap2:agent:xxx#key-1）であることを確認
                    if not proof.kid.startswith("did:") or "#" not in proof.kid:
                        logger.error(
                            f"[A2AHandler] Invalid kid format: {proof.kid}. "
                            f"Expected DID fragment format (e.g., did:ap2:agent:xxx#key-1)"
                        )
                        return False

                    # kidのDID部分がsenderと一致することを確認
                    kid_did = proof.kid.split("#")[0]
                    if kid_did != message.header.sender:
                        logger.error(
                            f"[A2AHandler] KID DID mismatch: kid={kid_did}, sender={message.header.sender}"
                        )
                        return False

                # 3. Timestamp検証（専門家の指摘：リプレイ攻撃対策）
                try:
                    msg_timestamp = datetime.fromisoformat(message.header.timestamp.replace('Z', '+00:00'))
                    now = datetime.now(timezone.utc)
                    time_diff = abs((now - msg_timestamp).total_seconds())

                    # ±300秒（5分）の許容範囲
                    if time_diff > 300:
                        logger.error(
                            f"[A2AHandler] Timestamp out of range: {time_diff}s "
                            f"(max 300s allowed)"
                        )
                        return False
                except Exception as e:
                    logger.error(f"[A2AHandler] Invalid timestamp format: {e}")
                    return False

                # 4. Nonce検証（専門家の指摘：リプレイ攻撃対策）
                # TODO: NonceManagerを実装してnonce再利用をチェック
                # 現時点では、nonceフィールドの存在確認のみ
                if not message.header.nonce:
                    logger.error("[A2AHandler] Nonce is required but missing")
                    return False

                # 5. DIDベースの公開鍵解決（専門家の指摘対応）
                public_key_to_verify = proof.publicKey  # デフォルトは埋め込み公開鍵

                if proof.kid:
                    # KIDから公開鍵を解決
                    resolved_public_key_pem = self.did_resolver.resolve_public_key(proof.kid)

                    if not resolved_public_key_pem:
                        logger.warning(
                            f"[A2AHandler] Failed to resolve public key from KID: {proof.kid}. "
                            f"Falling back to embedded public key."
                        )
                        # DID解決失敗時は埋め込み公開鍵にフォールバック
                        # これにより、エージェント起動順序の問題を回避
                        public_key_to_verify = proof.publicKey
                    else:
                        # DID解決したPEM文字列をbase64エンコード
                        # SignatureManagerはbase64エンコードされたPEMを期待するため
                        import base64
                        public_key_to_verify = base64.b64encode(
                            resolved_public_key_pem.encode('utf-8')
                        ).decode('utf-8')

                        logger.debug(
                            f"[A2AHandler] Using DID-resolved public key for verification: "
                            f"kid={proof.kid}"
                        )
                else:
                    # kidがない場合は埋め込み公開鍵を使用（後方互換性）
                    logger.warning(
                        "[A2AHandler] No KID provided, using embedded public key. "
                        "This is not recommended for production."
                    )

                # Pydanticモデルを辞書に変換（署名検証用）
                message_dict = message.model_dump(by_alias=True)

                # Signatureオブジェクトに変換（ap2_crypto用）
                signature_obj = Signature(
                    algorithm=proof.algorithm.upper(),
                    value=proof.signatureValue,
                    public_key=public_key_to_verify,  # DID解決した公開鍵を使用
                    signed_at=proof.created
                )

                # 署名検証（ap2_crypto.SignatureManagerを使用）
                is_valid = self.signature_manager.verify_a2a_message_signature(
                    message_dict,
                    signature_obj
                )

                if is_valid:
                    logger.info(
                        f"[A2AHandler] proof署名検証成功: sender={message.header.sender}, "
                        f"alg={proof.algorithm}, kid={proof.kid}, "
                        f"public_key_source={'DID-resolved' if proof.kid else 'embedded'}"
                    )
                else:
                    logger.warning(f"[A2AHandler] proof署名検証失敗: sender={message.header.sender}")

                return is_valid

            except Exception as e:
                logger.error(f"[A2AHandler] proof署名検証エラー: {e}", exc_info=True)
                return False

        # 後方互換性：旧形式のsignatureをサポート（非推奨）
        elif message.header.signature:
            logger.warning("[A2AHandler] 旧形式のsignature使用（非推奨）。proof構造への移行を推奨")

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
                    logger.info(f"[A2AHandler] signature署名検証成功: sender={message.header.sender}")
                else:
                    logger.warning(f"[A2AHandler] signature署名検証失敗: sender={message.header.sender}")

                return is_valid

            except Exception as e:
                logger.error(f"[A2AHandler] signature署名検証エラー: {e}", exc_info=True)
                return False

        else:
            logger.warning("[A2AHandler] メッセージにproof/signatureがありません")
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
        import json

        # 受信メッセージの詳細ログ
        logger.info(
            f"\n{'='*80}\n"
            f"[A2A受信] メッセージID: {message.header.message_id}\n"
            f"  送信元: {message.header.sender}\n"
            f"  送信先: {message.header.recipient}\n"
            f"  タイプ: {message.dataPart.type}\n"
            f"  データID: {message.dataPart.id}\n"
            f"  タイムスタンプ: {message.header.timestamp}\n"
            f"  ペイロード: {json.dumps(message.dataPart.payload, ensure_ascii=False, indent=2)}\n"
            f"{'='*80}"
        )

        # 1. 署名検証
        if not await self.verify_message_signature(message):
            logger.error(f"[A2A受信] 署名検証失敗: message_id={message.header.message_id}")
            raise ValueError("Invalid message signature")

        # 2. recipient確認
        if message.header.recipient != self.agent_id:
            logger.error(
                f"[A2A受信] 宛先不一致: "
                f"期待={self.agent_id}, 実際={message.header.recipient}"
            )
            raise ValueError(
                f"Message recipient mismatch: "
                f"expected={self.agent_id}, got={message.header.recipient}"
            )

        # 3. @typeに基づくハンドラー呼び出し
        data_type = message.dataPart.type
        handler = self._handlers.get(data_type)

        if not handler:
            logger.error(f"[A2A受信] ハンドラー未登録: type={data_type}")
            raise ValueError(f"No handler registered for @type: {data_type}")

        logger.info(
            f"[A2A処理] ハンドラー実行中: "
            f"type={data_type}, from={message.header.sender}"
        )

        # ハンドラー実行
        result = await handler(message)

        logger.info(
            f"[A2A処理] ハンドラー完了: "
            f"type={data_type}, result_type={result.get('type', 'unknown')}"
        )

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

        A2A仕様準拠：proof構造を使用

        専門家の指摘対応：
        - nonce: リプレイ攻撃対策として32バイトのランダムnonceを生成

        Args:
            recipient: 送信先エージェントDID
            data_type: データタイプ (e.g., "ap2/CartMandate")
            data_id: データID
            payload: ペイロード
            sign: 署名するか（デフォルトTrue）

        Returns:
            A2AMessage: 署名済みレスポンスメッセージ
        """
        import secrets

        # ヘッダー作成
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        nonce = secrets.token_hex(32)  # 32バイト = 64文字のhex文字列

        header = A2AMessageHeader(
            message_id=str(uuid.uuid4()),
            sender=self.agent_id,
            recipient=recipient,
            timestamp=timestamp,
            nonce=nonce,
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

        # 署名（A2A仕様準拠：proof構造を使用）
        if sign:
            message_dict = message.model_dump(by_alias=True)

            # agent_idから鍵IDを抽出（例: did:ap2:agent:shopping_agent -> shopping_agent）
            key_id = self.agent_id.split(":")[-1]

            # 署名生成（ap2_crypto.SignatureManagerを使用）
            signature_obj = self.signature_manager.sign_a2a_message(message_dict, key_id)

            # A2AProof構造に変換（A2A仕様準拠）
            # 専門家の指摘対応：kidフィールドを追加してDIDベースの鍵解決を可能に
            kid = f"{self.agent_id}#key-1"  # DIDフラグメント形式

            message.header.proof = A2AProof(
                algorithm=signature_obj.algorithm.lower(),
                signatureValue=signature_obj.value,
                publicKey=signature_obj.public_key,
                kid=kid,
                created=timestamp,
                proofPurpose="authentication"
            )

        import json as json_lib

        logger.info(
            f"\n{'='*80}\n"
            f"[A2A送信] レスポンス作成\n"
            f"  送信元: {self.agent_id}\n"
            f"  送信先: {recipient}\n"
            f"  タイプ: {data_type}\n"
            f"  データID: {data_id}\n"
            f"  署名: {'あり' if sign else 'なし'}\n"
            f"  タイムスタンプ: {timestamp}\n"
            f"  ペイロード: {json_lib.dumps(payload, ensure_ascii=False, indent=2)}\n"
            f"{'='*80}"
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
            data_type="ap2.errors.Error",
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
