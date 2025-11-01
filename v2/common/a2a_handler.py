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
from common.crypto import SignatureManager, KeyManager
from common.models import (
    A2AMessage, A2AMessageHeader, A2ADataPart, A2ASignature, A2AProof, Signature,
    A2AArtifact, A2AArtifactPart
)
from common.did_resolver import DIDResolver
from common.nonce_manager import NonceManager
from common.logger import get_logger, log_a2a_message

logger = get_logger(__name__)


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

        # Nonce管理（専門家の指摘対応：リプレイ攻撃対策）
        self.nonce_manager = NonceManager(ttl_seconds=300)  # タイムスタンプ検証と同じ5分のTTL

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
                if not message.header.nonce:
                    logger.error("[A2AHandler] Nonce is required but missing")
                    return False

                # NonceManagerで再利用攻撃をチェック
                if not await self.nonce_manager.is_valid_nonce(message.header.nonce):
                    logger.error(
                        f"[A2AHandler] Nonce reuse detected (replay attack): "
                        f"nonce={message.header.nonce}, sender={message.header.sender}"
                    )
                    return False

                logger.debug(
                    f"[A2AHandler] Nonce validation successful: "
                    f"nonce={message.header.nonce[:16]}..."  # ログには先頭16文字のみ表示
                )

                # 5. DIDベースの公開鍵解決（AP2完全準拠：publicKeyMultibase形式）
                public_key_multibase_to_verify = proof.publicKeyMultibase  # デフォルトは埋め込み公開鍵

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
                        public_key_multibase_to_verify = proof.publicKeyMultibase
                    else:
                        # DID解決したPEM文字列をpublicKeyMultibase形式に変換
                        # AP2完全準拠：multibase形式に統一
                        from common.crypto import KeyManager
                        import base64

                        # PEM文字列から公開鍵オブジェクトを復元
                        key_manager_temp = KeyManager()
                        pem_bytes = resolved_public_key_pem.encode('utf-8')
                        public_key_obj = key_manager_temp.public_key_from_base64(
                            base64.b64encode(pem_bytes).decode('utf-8')
                        )

                        # publicKeyMultibase形式に変換
                        public_key_multibase_to_verify = key_manager_temp.public_key_to_multibase(public_key_obj)

                        logger.debug(
                            f"[A2AHandler] Using DID-resolved public key for verification: "
                            f"kid={proof.kid}"
                        )
                else:
                    # kidがない場合は埋め込み公開鍵を使用
                    logger.warning(
                        "[A2AHandler] No KID provided, using embedded public key. "
                        "This is not recommended for production."
                    )

                # Pydanticモデルを辞書に変換（署名検証用）
                # AP2/A2A仕様準拠：Noneフィールドを除外して署名時と同じ状態にする
                message_dict = message.model_dump(by_alias=True, exclude_none=True)

                # Signatureオブジェクトに変換（ap2_crypto用、AP2完全準拠）
                signature_obj = Signature(
                    algorithm=proof.algorithm.upper(),
                    value=proof.signatureValue,
                    publicKeyMultibase=public_key_multibase_to_verify,  # DID解決した公開鍵（multibase形式）
                    signed_at=proof.created,
                    key_id=proof.kid  # KIDを設定
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

        # AP2完全準拠：後方互換性は不要（旧形式のsignature削除）
        elif message.header.signature:
            logger.error("[A2AHandler] 旧形式のsignature検出。AP2完全準拠のため、proof構造のみサポートします。")
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

        # 受信メッセージの詳細ログ（AP2完全準拠: ペイロードとヘッダーをJSON形式で出力）
        log_a2a_message(
            logger=logger,
            direction="received",
            message_type=message.dataPart.type,
            payload=message.dataPart.payload,
            peer=message.header.sender,
            headers={
                "message_id": message.header.message_id,
                "sender": message.header.sender,
                "recipient": message.header.recipient,
                "timestamp": message.header.timestamp,
                "nonce": message.header.nonce,
                "schema_version": message.header.schema_version
            }
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
            # AP2/A2A仕様準拠：署名対象データ作成時にNoneフィールドを除外
            # これにより、署名時と検証時で同じcanonical JSONが生成される
            message_dict = message.model_dump(by_alias=True, exclude_none=True)

            # agent_idから鍵IDを抽出（例: did:ap2:agent:shopping_agent -> shopping_agent）
            key_id = self.agent_id.split(":")[-1]

            # 署名生成（ap2_crypto.SignatureManagerを使用）
            signature_obj = self.signature_manager.sign_a2a_message(message_dict, key_id)

            # A2AProof構造に変換（A2A仕様準拠）
            # 専門家の指摘対応：kidフィールドを追加してDIDベースの鍵解決を可能に
            # Ed25519署名の場合は#key-2、ECDSA署名の場合は#key-1を使用
            key_fragment = "#key-2" if signature_obj.algorithm.upper() == "ED25519" else "#key-1"
            kid = f"{self.agent_id}{key_fragment}"  # DIDフラグメント形式

            message.header.proof = A2AProof(
                algorithm=signature_obj.algorithm.lower(),
                signatureValue=signature_obj.value,
                publicKeyMultibase=signature_obj.publicKeyMultibase,
                kid=kid,
                created=timestamp,
                proofPurpose="authentication"
            )

        # 送信メッセージの詳細ログ（AP2完全準拠: ペイロードとヘッダーをJSON形式で出力）
        log_a2a_message(
            logger=logger,
            direction="sent",
            message_type=data_type,
            payload=payload,
            peer=recipient,
            headers={
                "message_id": message.header.message_id,
                "sender": self.agent_id,
                "recipient": recipient,
                "timestamp": timestamp,
                "nonce": message.header.nonce,
                "schema_version": message.header.schema_version,
                "signed": sign
            }
        )

        return message

    def create_artifact_response(
        self,
        recipient: str,
        artifact_name: str,
        artifact_data: Dict[str, Any],
        data_type_key: str,
        sign: bool = True
    ) -> A2AMessage:
        """
        A2A Artifactレスポンスメッセージを作成

        AP2/A2A仕様準拠：CartMandateなどをArtifactとして送信
        a2a-extension.md:144-229の仕様に準拠

        Args:
            recipient: 送信先エージェントDID
            artifact_name: Artifact名 (e.g., "CartMandate")
            artifact_data: Artifactのデータ (e.g., signed CartMandate)
            data_type_key: データタイプキー (e.g., "CartMandate")
            sign: 署名するか（デフォルトTrue）

        Returns:
            A2AMessage: Artifactを含む署名済みレスポンスメッセージ
        """
        import secrets

        # ヘッダー作成
        timestamp = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        nonce = secrets.token_hex(32)

        header = A2AMessageHeader(
            message_id=str(uuid.uuid4()),
            sender=self.agent_id,
            recipient=recipient,
            timestamp=timestamp,
            nonce=nonce,
            schema_version="0.2"
        )

        # ArtifactPart作成（dataタイプで実データを格納）
        artifact_part = A2AArtifactPart(
            kind="data",
            data={data_type_key: artifact_data}
        )

        # Artifact作成
        artifact_id = f"artifact:{str(uuid.uuid4())}"
        artifact = A2AArtifact(
            name=artifact_name,
            artifactId=artifact_id,
            parts=[artifact_part]
        )

        # DataPart作成（kind="artifact"でArtifactを参照）
        data_part = A2ADataPart(
            kind="artifact",
            artifact=artifact
        )

        # メッセージ作成
        message = A2AMessage(header=header, dataPart=data_part)

        # 署名（A2A仕様準拠：proof構造を使用）
        if sign:
            # AP2/A2A仕様準拠：署名対象データ作成時にNoneフィールドを除外
            message_dict = message.model_dump(by_alias=True, exclude_none=True)

            # agent_idから鍵IDを抽出
            key_id = self.agent_id.split(":")[-1]

            # 署名生成
            signature_obj = self.signature_manager.sign_a2a_message(message_dict, key_id)

            # A2AProof構造に変換
            # Ed25519署名の場合は#key-2、ECDSA署名の場合は#key-1を使用
            key_fragment = "#key-2" if signature_obj.algorithm.upper() == "ED25519" else "#key-1"
            kid = f"{self.agent_id}{key_fragment}"

            message.header.proof = A2AProof(
                algorithm=signature_obj.algorithm.lower(),
                signatureValue=signature_obj.value,
                publicKeyMultibase=signature_obj.publicKeyMultibase,
                kid=kid,
                created=timestamp,
                proofPurpose="authentication"
            )

        # 送信メッセージの詳細ログ（AP2完全準拠: ペイロードとヘッダーをJSON形式で出力）
        log_a2a_message(
            logger=logger,
            direction="sent",
            message_type=f"artifact:{artifact_name}",
            payload=artifact_data,
            peer=recipient,
            headers={
                "message_id": message.header.message_id,
                "sender": self.agent_id,
                "recipient": recipient,
                "timestamp": timestamp,
                "nonce": message.header.nonce,
                "schema_version": message.header.schema_version,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "signed": sign
            }
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
