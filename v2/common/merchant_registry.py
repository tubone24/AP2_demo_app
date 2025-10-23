"""
v2/common/merchant_registry.py

Merchant Registry - Phase 2 DID Resolution（ローカルDB + 中央レジストリ）

AP2仕様準拠：
- Merchant DID Document管理
- ローカルデータベースキャッシュ
- 中央レジストリとの同期
"""

import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Text, Integer
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.future import select
import httpx

from v2.common.models import DIDDocument, ServiceEndpoint, VerificationMethod
from v2.common.logger import get_logger

logger = get_logger(__name__)

Base = declarative_base()


class MerchantDIDRecord(Base):
    """Merchant DID Document レコード（データベーステーブル）"""
    __tablename__ = "merchant_did_registry"

    # Primary Key
    merchant_did = Column(String, primary_key=True)  # "did:ap2:merchant:nike"

    # Merchant情報
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)

    # Service Endpoint
    agent_endpoint = Column(String, nullable=False)  # "https://merchant-agent.nike.com"
    service_type = Column(String, default="AP2MerchantAgent")  # サービスタイプ

    # 公開鍵（PEM形式）
    public_key_pem = Column(Text, nullable=False)
    verification_method_id = Column(String, nullable=False)  # "did:ap2:merchant:nike#key-1"
    verification_method_type = Column(String, default="Ed25519VerificationKey2020")

    # ステータス・信頼度
    status = Column(String, default="active")  # active, inactive, suspended
    trust_score = Column(Float, default=0.0)  # 0.0 - 100.0

    # メタデータ
    categories = Column(Text, nullable=True)  # JSON文字列（例: ["shoes", "apparel"]）
    payment_methods = Column(Text, nullable=True)  # JSON文字列（例: ["credit_card", "paypal"]）

    # タイムスタンプ
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    last_verified_at = Column(DateTime, nullable=True)

    # 中央レジストリ同期
    registry_synced_at = Column(DateTime, nullable=True)


class MerchantRegistry:
    """Merchant Registry - Phase 2 DID Resolution実装

    機能:
    1. ローカルデータベースからMerchant DID Document取得（高速キャッシュ）
    2. 中央レジストリからMerchant DID Document取得（フォールバック）
    3. Merchant登録・更新
    4. Merchant検索・検証

    AP2仕様準拠:
    - W3C DID Document形式
    - did:ap2:merchant:<merchant_id> 形式
    """

    def __init__(
        self,
        database_url: str,
        registry_url: Optional[str] = None
    ):
        """
        Args:
            database_url: SQLiteデータベースURL（例: "sqlite+aiosqlite:///./data/merchant_registry.db"）
            registry_url: 中央レジストリURL（例: "https://registry.ap2-protocol.org"）
        """
        self.registry_url = registry_url or "https://registry.ap2-protocol.org"

        # 非同期データベースエンジン
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session_maker = sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )

    async def init_db(self):
        """データベーステーブル初期化"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("[MerchantRegistry] Database initialized")

    async def resolve_merchant_did(
        self,
        merchant_did: str
    ) -> Optional[DIDDocument]:
        """Merchant DIDを解決してDID Documentを取得

        解決順序:
        1. ローカルデータベースから検索（高速キャッシュ）
        2. 中央レジストリから取得（フォールバック）
        3. ローカルDBにキャッシュ

        Args:
            merchant_did: "did:ap2:merchant:nike"

        Returns:
            DIDDocument or None
        """
        # 1. ローカルDBから取得
        did_doc = await self._get_from_local_db(merchant_did)
        if did_doc:
            logger.debug(f"[MerchantRegistry] Resolved from local DB: {merchant_did}")
            return did_doc

        # 2. 中央レジストリから取得
        did_doc = await self._get_from_central_registry(merchant_did)
        if did_doc:
            logger.info(f"[MerchantRegistry] Resolved from central registry: {merchant_did}")
            # ローカルDBにキャッシュ
            await self._cache_to_local_db(did_doc, merchant_did)
            return did_doc

        logger.warning(f"[MerchantRegistry] DID not found: {merchant_did}")
        return None

    async def _get_from_local_db(
        self,
        merchant_did: str
    ) -> Optional[DIDDocument]:
        """ローカルデータベースから取得"""
        async with self.async_session_maker() as session:
            result = await session.execute(
                select(MerchantDIDRecord).where(
                    MerchantDIDRecord.merchant_did == merchant_did,
                    MerchantDIDRecord.status == "active"
                )
            )
            record = result.scalar_one_or_none()

            if not record:
                return None

            # DIDDocumentに変換
            return self._record_to_did_document(record)

    async def _get_from_central_registry(
        self,
        merchant_did: str
    ) -> Optional[DIDDocument]:
        """中央レジストリから取得"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{self.registry_url}/resolve/{merchant_did}",
                    timeout=5.0
                )
                response.raise_for_status()
                data = response.json()

                # W3C DID Document形式をパース
                return DIDDocument(**data)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.debug(f"[MerchantRegistry] DID not found in registry: {merchant_did}")
            else:
                logger.warning(f"[MerchantRegistry] Registry HTTP error: {e}")
            return None
        except Exception as e:
            logger.warning(f"[MerchantRegistry] Failed to fetch from registry: {e}")
            return None

    async def _cache_to_local_db(
        self,
        did_doc: DIDDocument,
        merchant_did: str
    ):
        """中央レジストリから取得したDID DocumentをローカルDBにキャッシュ"""
        # DIDDocumentからフィールドを抽出
        verification_method = did_doc.verificationMethod[0] if did_doc.verificationMethod else None
        service_endpoint = did_doc.service[0] if did_doc.service else None

        if not verification_method or not service_endpoint:
            logger.warning(f"[MerchantRegistry] Incomplete DID Document, skipping cache: {merchant_did}")
            return

        record = MerchantDIDRecord(
            merchant_did=merchant_did,
            name=merchant_did.split(":")[-1],  # "nike" from "did:ap2:merchant:nike"
            description="Synced from central registry",
            agent_endpoint=service_endpoint.serviceEndpoint,
            service_type=service_endpoint.type,
            public_key_pem=verification_method.publicKeyPem,
            verification_method_id=verification_method.id,
            verification_method_type=verification_method.type,
            status="active",
            registry_synced_at=datetime.now(timezone.utc)
        )

        async with self.async_session_maker() as session:
            session.add(record)
            await session.commit()

        logger.info(f"[MerchantRegistry] Cached DID Document to local DB: {merchant_did}")

    async def register_merchant(
        self,
        merchant_did: str,
        name: str,
        agent_endpoint: str,
        public_key_pem: str,
        description: Optional[str] = None,
        categories: Optional[List[str]] = None,
        payment_methods: Optional[List[str]] = None
    ) -> DIDDocument:
        """Merchantを登録

        Args:
            merchant_did: "did:ap2:merchant:nike"
            name: "Nike Store"
            agent_endpoint: "https://merchant-agent.nike.com"
            public_key_pem: PEM形式の公開鍵
            description: オプション説明
            categories: カテゴリーリスト
            payment_methods: 支払方法リスト

        Returns:
            DIDDocument
        """
        import json

        verification_method_id = f"{merchant_did}#key-1"
        service_id = f"{merchant_did}#merchant-agent"

        record = MerchantDIDRecord(
            merchant_did=merchant_did,
            name=name,
            description=description,
            agent_endpoint=agent_endpoint,
            service_type="AP2MerchantAgent",
            public_key_pem=public_key_pem,
            verification_method_id=verification_method_id,
            verification_method_type="Ed25519VerificationKey2020",
            status="active",
            trust_score=50.0,  # 初期信頼度スコア
            categories=json.dumps(categories) if categories else None,
            payment_methods=json.dumps(payment_methods) if payment_methods else None
        )

        async with self.async_session_maker() as session:
            session.add(record)
            await session.commit()

        logger.info(f"[MerchantRegistry] Registered merchant: {merchant_did}")

        return self._record_to_did_document(record)

    async def search_merchants(
        self,
        query: Optional[str] = None,
        categories: Optional[List[str]] = None,
        min_trust_score: float = 0.0
    ) -> List[Dict[str, Any]]:
        """Merchantを検索

        Args:
            query: 名前での検索クエリ
            categories: カテゴリーフィルター
            min_trust_score: 最低信頼度スコア

        Returns:
            Merchantリスト
        """
        async with self.async_session_maker() as session:
            stmt = select(MerchantDIDRecord).where(
                MerchantDIDRecord.status == "active",
                MerchantDIDRecord.trust_score >= min_trust_score
            )

            if query:
                stmt = stmt.where(MerchantDIDRecord.name.contains(query))

            result = await session.execute(stmt)
            records = result.scalars().all()

            return [
                {
                    "merchant_did": r.merchant_did,
                    "name": r.name,
                    "description": r.description,
                    "agent_endpoint": r.agent_endpoint,
                    "trust_score": r.trust_score
                }
                for r in records
            ]

    def _record_to_did_document(
        self,
        record: MerchantDIDRecord
    ) -> DIDDocument:
        """データベースレコードをDIDDocumentに変換"""
        verification_method = VerificationMethod(
            id=record.verification_method_id,
            type=record.verification_method_type,
            controller=record.merchant_did,
            publicKeyPem=record.public_key_pem
        )

        service_endpoint = ServiceEndpoint(
            id=f"{record.merchant_did}#merchant-agent",
            type=record.service_type,
            serviceEndpoint=record.agent_endpoint
        )

        return DIDDocument(
            id=record.merchant_did,
            verificationMethod=[verification_method],
            authentication=[f"#{record.verification_method_id.split('#')[-1]}"],
            service=[service_endpoint]
        )
