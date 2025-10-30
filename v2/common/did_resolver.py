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

from common.models import DIDDocument, VerificationMethod
from common.crypto import KeyManager

logger = logging.getLogger(__name__)


class DIDResolver:
    """
    DID解決クラス（Phase 2実装）

    W3C DID仕様準拠：DIDからDIDドキュメントを解決し、公開鍵を取得

    Phase 2実装（ハイブリッド型）：
    - Agent DID: KeyManagerから公開鍵を読み込んでDIDドキュメントを生成
    - Merchant DID: MerchantRegistryから解決（ローカルDB + 中央レジストリ）
    - インメモリキャッシュでDIDドキュメントを管理

    本番実装：
    - ブロックチェーンやDLT（Distributed Ledger Technology）からDIDドキュメントを取得
    - IPFS、Ethereumなどの分散ストレージから解決
    """

    def __init__(
        self,
        key_manager: KeyManager,
        merchant_registry: Optional["MerchantRegistry"] = None
    ):
        """
        Args:
            key_manager: 公開鍵を取得するためのKeyManagerインスタンス
            merchant_registry: Merchant Registry（Phase 2実装）
        """
        self.key_manager = key_manager
        self.merchant_registry = merchant_registry

        # DIDドキュメントキャッシュ（デモ用インメモリストレージ）
        self._did_registry: Dict[str, DIDDocument] = {}

        # デモ環境のDIDをレジストリに登録
        self._init_demo_registry()

    def _init_demo_registry(self):
        """
        デモ環境用のDIDレジストリを初期化

        セキュリティ要件（専門家の指摘対応）：
        1. 永続化されたDIDドキュメントJSONファイルを優先的に読み込む
        2. DIDドキュメントが存在しない場合は、KeyManagerから公開鍵を取得して生成
        3. これにより、init_keys.pyで生成したDIDドキュメントを使用し、一貫性を保つ
        """
        import json
        import os

        # 永続化ストレージのDIDドキュメントディレクトリ
        did_docs_dir = Path(os.getenv("AP2_KEYS_DIRECTORY", "./keys")).parent / "data" / "did_documents"

        # AP2デモで使用する全エージェントのDIDを登録
        demo_agents = [
            {"agent_key": "shopping_agent", "did": "did:ap2:agent:shopping_agent"},
            {"agent_key": "merchant_agent", "did": "did:ap2:agent:merchant_agent"},
            {"agent_key": "merchant", "did": "did:ap2:merchant:mugibo_merchant"},
            {"agent_key": "credential_provider", "did": "did:ap2:cp:demo_cp"},
            {"agent_key": "credential_provider_2", "did": "did:ap2:cp:demo_cp_2"},
            {"agent_key": "payment_processor", "did": "did:ap2:agent:payment_processor"}
        ]

        for agent in demo_agents:
            agent_key = agent["agent_key"]
            did = agent["did"]
            did_doc_file = did_docs_dir / f"{agent_key}_did.json"

            try:
                # 1. 永続化されたDIDドキュメントJSONを読み込み（推奨）
                if did_doc_file.exists():
                    logger.info(
                        f"[DIDResolver] 永続化されたDIDドキュメントを読み込み中: {did_doc_file}"
                    )
                    did_doc_dict = json.loads(did_doc_file.read_text())

                    # DIDDocumentモデルに変換
                    # W3C準拠のDIDドキュメントからVerificationMethodを抽出
                    verification_methods = []
                    for vm in did_doc_dict.get("verificationMethod", []):
                        verification_methods.append(VerificationMethod(
                            id=vm["id"],
                            type=vm["type"],
                            controller=vm["controller"],
                            publicKeyPem=vm["publicKeyPem"]
                        ))

                    # AP2完全準拠: serviceフィールドを抽出
                    from common.models import ServiceEndpoint
                    services = []
                    for svc in did_doc_dict.get("service", []):
                        services.append(ServiceEndpoint(
                            id=svc["id"],
                            type=svc["type"],
                            serviceEndpoint=svc["serviceEndpoint"],
                            name=svc.get("name"),
                            description=svc.get("description"),
                            supported_methods=svc.get("supported_methods"),
                            logo_url=svc.get("logo_url")
                        ))

                    did_doc = DIDDocument(
                        id=did_doc_dict["id"],
                        verificationMethod=verification_methods,
                        authentication=did_doc_dict.get("authentication", []),
                        assertionMethod=did_doc_dict.get("assertionMethod", []),
                        service=services if services else None  # AP2完全準拠
                    )

                    # レジストリに登録
                    self._did_registry[did] = did_doc
                    logger.info(f"[DIDResolver] ✓ 永続化DIDドキュメントを登録: {did}")

                # 2. DIDドキュメントが存在しない場合はエラー
                else:
                    error_msg = (
                        f"[DIDResolver] ❌ 永続化されたDIDドキュメントが見つかりません: {did_doc_file}\n"
                        f"   v2/scripts/init_keys.py を実行してDIDドキュメントを生成してください。"
                    )
                    logger.error(error_msg)
                    raise FileNotFoundError(error_msg)

            except Exception as e:
                logger.warning(
                    f"[DIDResolver] DIDの初期化に失敗: {did}: {e}. "
                    f"公開鍵がまだ存在しない可能性があります。"
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
        DIDからDIDドキュメントを解決（Phase 2実装）

        解決順序:
        1. インメモリキャッシュから取得
        2. Merchant DIDの場合: MerchantRegistryから解決
        3. Agent DIDの場合: ローカルレジストリから取得

        Args:
            did: 解決するDID（例: did:ap2:agent:shopping_agent, did:ap2:merchant:nike）

        Returns:
            Optional[DIDDocument]: DIDドキュメント（存在しない場合はNone）
        """
        # 1. インメモリキャッシュから取得
        did_doc = self._did_registry.get(did)
        if did_doc:
            logger.debug(f"[DIDResolver] Resolved from cache: {did}")
            return did_doc

        # 2. Merchant DIDの場合: MerchantRegistryから解決（Phase 2）
        if did.startswith("did:ap2:merchant:") and self.merchant_registry:
            try:
                import asyncio
                # 非同期関数を同期的に呼び出し
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 既にイベントループが実行中の場合（非推奨だが互換性のため）
                    logger.warning(f"[DIDResolver] Cannot resolve Merchant DID synchronously in running event loop: {did}")
                    return None
                else:
                    did_doc = loop.run_until_complete(
                        self.merchant_registry.resolve_merchant_did(did)
                    )
                    if did_doc:
                        # キャッシュに保存
                        self._did_registry[did] = did_doc
                        logger.info(f"[DIDResolver] Resolved Merchant DID from registry: {did}")
                        return did_doc
            except Exception as e:
                logger.error(f"[DIDResolver] Failed to resolve Merchant DID: {did}: {e}")

        # 3. 見つからない場合
        logger.warning(f"[DIDResolver] DID not found: {did}")
        return None

    async def resolve_async(self, did: str) -> Optional[DIDDocument]:
        """
        DIDからDIDドキュメントを解決（非同期版・Phase 2実装）

        解決順序:
        1. インメモリキャッシュから取得
        2. Merchant DIDの場合: MerchantRegistryから解決
        3. Agent DIDの場合: ローカルレジストリから取得

        Args:
            did: 解決するDID（例: did:ap2:agent:shopping_agent, did:ap2:merchant:nike）

        Returns:
            Optional[DIDDocument]: DIDドキュメント（存在しない場合はNone）
        """
        # 1. インメモリキャッシュから取得
        did_doc = self._did_registry.get(did)
        if did_doc:
            logger.debug(f"[DIDResolver] Resolved from cache: {did}")
            return did_doc

        # 2. Merchant DIDの場合: MerchantRegistryから解決（Phase 2）
        if did.startswith("did:ap2:merchant:") and self.merchant_registry:
            try:
                did_doc = await self.merchant_registry.resolve_merchant_did(did)
                if did_doc:
                    # キャッシュに保存
                    self._did_registry[did] = did_doc
                    logger.info(f"[DIDResolver] Resolved Merchant DID from registry: {did}")
                    return did_doc
            except Exception as e:
                logger.error(f"[DIDResolver] Failed to resolve Merchant DID: {did}: {e}")

        # 3. 見つからない場合
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
