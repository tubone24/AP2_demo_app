"""
v2/common/did_resolver.py

DID解決機能 - W3C DID仕様準拠

専門家の指摘対応：
「sender_didから公開鍵を解決する仕組みが不十分。現在はproof.publicKeyに直接埋め込んでいるが、
本来はDIDドキュメントから解決すべき。」

このモジュールは、DIDからDIDドキュメントを取得し、KIDから公開鍵を解決する機能を提供します。
"""

import logging
from typing import Optional, Dict
from pathlib import Path

from v2.common.models import DIDDocument, VerificationMethod
from v2.common.crypto import KeyManager

logger = logging.getLogger(__name__)


class DIDResolver:
    """
    DID解決クラス

    W3C DID仕様準拠：DIDからDIDドキュメントを解決し、公開鍵を取得

    デモ実装：
    - KeyManagerから公開鍵を読み込んでDIDドキュメントを生成
    - インメモリキャッシュでDIDドキュメントを管理

    本番実装：
    - ブロックチェーンやDLT（Distributed Ledger Technology）からDIDドキュメントを取得
    - IPFS、Ethereumなどの分散ストレージから解決
    """

    def __init__(self, key_manager: KeyManager):
        """
        Args:
            key_manager: 公開鍵を取得するためのKeyManagerインスタンス
        """
        self.key_manager = key_manager

        # DIDドキュメントキャッシュ（デモ用インメモリストレージ）
        self._did_registry: Dict[str, DIDDocument] = {}

        # デモ環境のDIDをレジストリに登録
        self._init_demo_registry()

    def _init_demo_registry(self):
        """デモ環境用のDIDレジストリを初期化"""
        # AP2デモで使用する全エージェントのDIDを登録
        demo_agents = [
            "shopping_agent",
            "merchant_agent",
            "merchant",
            "credential_provider",
            "payment_processor"
        ]

        for agent_key in demo_agents:
            did = f"did:ap2:agent:{agent_key}"

            try:
                # KeyManagerから公開鍵を読み込み（ECPublicKeyオブジェクト）
                public_key_obj = self.key_manager.load_public_key(agent_key)

                # PEM文字列に変換
                public_key_pem = self.key_manager.public_key_to_pem(public_key_obj)

                # DIDドキュメントを生成
                did_doc = self._create_did_document(did, agent_key, public_key_pem)

                # レジストリに登録
                self._did_registry[did] = did_doc

                logger.info(f"[DIDResolver] Registered DID: {did}")

            except Exception as e:
                logger.warning(
                    f"[DIDResolver] Failed to register DID {did}: {e}. "
                    f"Public key may not exist yet."
                )

    def _create_did_document(
        self,
        did: str,
        agent_key: str,
        public_key_pem: str
    ) -> DIDDocument:
        """
        DIDドキュメントを生成

        Args:
            did: DID（例: did:ap2:agent:shopping_agent）
            agent_key: エージェント鍵ID（例: shopping_agent）
            public_key_pem: PEM形式の公開鍵

        Returns:
            DIDDocument: 生成されたDIDドキュメント
        """
        # 検証メソッドID（DIDフラグメント形式）
        verification_method_id = f"{did}#key-1"

        # 検証メソッド定義
        verification_method = VerificationMethod(
            id=verification_method_id,
            type="EcdsaSecp256k1VerificationKey2019",
            controller=did,
            publicKeyPem=public_key_pem
        )

        # DIDドキュメント生成
        did_document = DIDDocument(
            id=did,
            verificationMethod=[verification_method],
            authentication=["#key-1"],  # 認証に使用
            assertionMethod=["#key-1"]  # アサーションに使用
        )

        return did_document

    def resolve(self, did: str) -> Optional[DIDDocument]:
        """
        DIDからDIDドキュメントを解決

        Args:
            did: 解決するDID（例: did:ap2:agent:shopping_agent）

        Returns:
            Optional[DIDDocument]: DIDドキュメント（存在しない場合はNone）
        """
        # レジストリから取得
        did_doc = self._did_registry.get(did)

        if did_doc:
            logger.debug(f"[DIDResolver] Resolved DID: {did}")
            return did_doc
        else:
            logger.warning(f"[DIDResolver] DID not found: {did}")
            return None

    def resolve_public_key(self, kid: str) -> Optional[str]:
        """
        KID（鍵ID）から公開鍵を解決

        専門家の指摘対応：
        「kidからDIDドキュメントを参照し、該当する公開鍵を取得する」

        Args:
            kid: 鍵ID（DIDフラグメント形式、例: did:ap2:agent:shopping_agent#key-1）

        Returns:
            Optional[str]: PEM形式の公開鍵（存在しない場合はNone）
        """
        # KIDからDIDとフラグメントを分離
        if "#" not in kid:
            logger.error(f"[DIDResolver] Invalid KID format: {kid}. Expected DID#fragment")
            return None

        did, fragment = kid.split("#", 1)

        # DIDドキュメントを解決
        did_doc = self.resolve(did)
        if not did_doc:
            return None

        # フラグメントに一致する検証メソッドを検索
        for vm in did_doc.verificationMethod:
            # フルIDまたはフラグメントのみで一致判定
            if vm.id == kid or vm.id.endswith(f"#{fragment}"):
                logger.debug(
                    f"[DIDResolver] Resolved public key for KID: {kid}, "
                    f"type: {vm.type}"
                )
                return vm.publicKeyPem

        logger.warning(
            f"[DIDResolver] Verification method not found for KID: {kid} "
            f"in DID document: {did}"
        )
        return None

    def register_did_document(self, did_doc: DIDDocument):
        """
        DIDドキュメントをレジストリに登録（デモ用）

        Args:
            did_doc: 登録するDIDドキュメント
        """
        self._did_registry[did_doc.id] = did_doc
        logger.info(f"[DIDResolver] Manually registered DID: {did_doc.id}")

    def update_public_key(self, did: str, agent_key: str):
        """
        DIDの公開鍵を更新（デモ用：鍵が新規生成された場合）

        Args:
            did: 更新するDID
            agent_key: エージェント鍵ID
        """
        try:
            # KeyManagerから最新の公開鍵を読み込み（ECPublicKeyオブジェクト）
            public_key_obj = self.key_manager.load_public_key(agent_key)

            # PEM文字列に変換
            public_key_pem = self.key_manager.public_key_to_pem(public_key_obj)

            # DIDドキュメントを再生成
            did_doc = self._create_did_document(did, agent_key, public_key_pem)

            # レジストリを更新
            self._did_registry[did] = did_doc

            logger.info(f"[DIDResolver] Updated DID document for: {did}")

        except Exception as e:
            logger.error(f"[DIDResolver] Failed to update DID {did}: {e}")
            raise
