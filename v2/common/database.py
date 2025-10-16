"""
v2/common/database.py

SQLiteデータベーススキーマとCRUD操作
demo_app_v2.mdのデータモデル要件に準拠
"""

import json
import uuid
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from sqlalchemy import Column, String, Integer, DateTime, Text, create_engine
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from sqlalchemy.future import select

Base = declarative_base()


# ========================================
# SQLAlchemy Models
# ========================================

class Product(Base):
    """
    productsテーブル

    demo_app_v2.md:
    - id (uuid)
    - sku (text)
    - name (text)
    - description (text)
    - price (integer, cents)
    - inventory_count (integer)
    - metadata (json)
    - created_at, updated_at
    """
    __tablename__ = "products"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    sku = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    price = Column(Integer, nullable=False)  # cents
    inventory_count = Column(Integer, nullable=False, default=0)
    product_metadata = Column(Text, nullable=True)  # JSON as text (renamed from 'metadata' to avoid SQLAlchemy reserved word)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "sku": self.sku,
            "name": self.name,
            "description": self.description,
            "price": self.price,
            "inventory_count": self.inventory_count,
            "metadata": json.loads(self.product_metadata) if self.product_metadata else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class User(Base):
    """
    usersテーブル

    demo_app_v2.md:
    - id (uuid)
    - display_name
    - email
    - created_at
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "display_name": self.display_name,
            "email": self.email,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Mandate(Base):
    """
    mandatesテーブル（トランザクション中心テーブル）

    demo_app_v2.md:
    - id (uuid)
    - type (Intent|Cart|Payment)
    - status (draft|pending_signature|signed|submitted|completed|failed)
    - payload (json)
    - issuer (agent id)
    - issued_at, updated_at
    - related_transaction_id (nullable)
    """
    __tablename__ = "mandates"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String, nullable=False, index=True)  # Intent, Cart, Payment
    status = Column(String, nullable=False, default="draft", index=True)
    payload = Column(Text, nullable=False)  # JSON as text
    issuer = Column(String, nullable=False, index=True)
    issued_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    related_transaction_id = Column(String, nullable=True, index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "payload": json.loads(self.payload) if self.payload else {},
            "issuer": self.issuer,
            "issued_at": self.issued_at.isoformat() if self.issued_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "related_transaction_id": self.related_transaction_id,
        }


class Transaction(Base):
    """
    transactionsテーブル

    demo_app_v2.md:
    - id (uuid)
    - intent_id (uuid)
    - cart_id (uuid)
    - payment_id (uuid)
    - status
    - events (json array)
    - created_at, updated_at
    """
    __tablename__ = "transactions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    intent_id = Column(String, nullable=True, index=True)
    cart_id = Column(String, nullable=True, index=True)
    payment_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, default="pending", index=True)
    events = Column(Text, nullable=True)  # JSON array as text
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "intent_id": self.intent_id,
            "cart_id": self.cart_id,
            "payment_id": self.payment_id,
            "status": self.status,
            "events": json.loads(self.events) if self.events else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class PasskeyCredential(Base):
    """
    passkey_credentialsテーブル

    WebAuthn Passkey情報を保存
    - credential_id: WebAuthnのcredential ID (Base64URL)
    - user_id: ユーザーID
    - public_key_cose: COSE形式の公開鍵 (Base64)
    - counter: signature counter (リプレイ攻撃対策)
    - transports: 利用可能なトランスポート (json array)
    - created_at: 作成日時
    """
    __tablename__ = "passkey_credentials"

    credential_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    public_key_cose = Column(Text, nullable=False)  # COSE形式の公開鍵 (Base64)
    counter = Column(Integer, nullable=False, default=0)
    transports = Column(Text, nullable=True)  # JSON array as text
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "credential_id": self.credential_id,
            "user_id": self.user_id,
            "public_key_cose": self.public_key_cose,
            "counter": self.counter,
            "transports": json.loads(self.transports) if self.transports else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Attestation(Base):
    """
    attestationsテーブル

    demo_app_v2.md:
    - id
    - user_id
    - attestation_raw (json)
    - verified (bool)
    - verification_details (json)
    - created_at
    """
    __tablename__ = "attestations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    attestation_raw = Column(Text, nullable=False)  # JSON as text
    verified = Column(Integer, nullable=False, default=0)  # SQLite doesn't have bool, use 0/1
    verification_details = Column(Text, nullable=True)  # JSON as text
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "attestation_raw": json.loads(self.attestation_raw) if self.attestation_raw else {},
            "verified": bool(self.verified),
            "verification_details": json.loads(self.verification_details) if self.verification_details else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ========================================
# Database Manager
# ========================================

class DatabaseManager:
    """SQLiteデータベース管理クラス"""

    def __init__(self, database_url: str = "sqlite+aiosqlite:///./v2/data/ap2.db"):
        """
        Args:
            database_url: データベースURL（デフォルト: v2/data/ap2.db）
        """
        self.database_url = database_url
        self.engine = create_async_engine(database_url, echo=False)
        self.async_session = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

    async def init_db(self):
        """データベース初期化（テーブル作成）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def drop_all(self):
        """全テーブル削除（開発用）"""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    @asynccontextmanager
    async def get_session(self):
        """セッション取得"""
        async with self.async_session() as session:
            yield session


# ========================================
# CRUD Operations
# ========================================

class ProductCRUD:
    """Product CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, product_data: Dict[str, Any]) -> Product:
        """商品作成"""
        product = Product(
            id=product_data.get("id", str(uuid.uuid4())),
            sku=product_data["sku"],
            name=product_data["name"],
            description=product_data["description"],
            price=product_data["price"],
            inventory_count=product_data.get("inventory_count", 0),
            product_metadata=json.dumps(product_data.get("metadata")) if product_data.get("metadata") else None
        )
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return product

    @staticmethod
    async def get_by_id(session: AsyncSession, product_id: str) -> Optional[Product]:
        """IDで商品取得"""
        result = await session.execute(select(Product).where(Product.id == product_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_sku(session: AsyncSession, sku: str) -> Optional[Product]:
        """SKUで商品取得"""
        result = await session.execute(select(Product).where(Product.sku == sku))
        return result.scalar_one_or_none()

    @staticmethod
    async def search(session: AsyncSession, query: str, limit: int = 10) -> List[Product]:
        """商品検索（名前または説明で部分一致）"""
        stmt = select(Product).where(
            (Product.name.contains(query)) | (Product.description.contains(query))
        ).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def update_inventory(session: AsyncSession, product_id: str, delta: int) -> Optional[Product]:
        """在庫更新"""
        product = await ProductCRUD.get_by_id(session, product_id)
        if product:
            product.inventory_count += delta
            product.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(product)
        return product

    @staticmethod
    async def list_all(session: AsyncSession, limit: int = 100) -> List[Product]:
        """全商品取得"""
        result = await session.execute(select(Product).limit(limit))
        return list(result.scalars().all())


class MandateCRUD:
    """Mandate CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, mandate_data: Dict[str, Any]) -> Mandate:
        """Mandate作成"""
        mandate = Mandate(
            id=mandate_data.get("id", str(uuid.uuid4())),
            type=mandate_data["type"],
            status=mandate_data.get("status", "draft"),
            payload=json.dumps(mandate_data["payload"]),
            issuer=mandate_data["issuer"],
            related_transaction_id=mandate_data.get("related_transaction_id")
        )
        session.add(mandate)
        await session.commit()
        await session.refresh(mandate)
        return mandate

    @staticmethod
    async def get_by_id(session: AsyncSession, mandate_id: str) -> Optional[Mandate]:
        """IDでMandate取得"""
        result = await session.execute(select(Mandate).where(Mandate.id == mandate_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def update_status(session: AsyncSession, mandate_id: str, status: str) -> Optional[Mandate]:
        """Mandateステータス更新"""
        mandate = await MandateCRUD.get_by_id(session, mandate_id)
        if mandate:
            mandate.status = status
            mandate.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(mandate)
        return mandate


class TransactionCRUD:
    """Transaction CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, transaction_data: Dict[str, Any]) -> Transaction:
        """Transaction作成"""
        transaction = Transaction(
            id=transaction_data.get("id", str(uuid.uuid4())),
            intent_id=transaction_data.get("intent_id"),
            cart_id=transaction_data.get("cart_id"),
            payment_id=transaction_data.get("payment_id"),
            status=transaction_data.get("status", "pending"),
            events=json.dumps(transaction_data.get("events", []))
        )
        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)
        return transaction

    @staticmethod
    async def get_by_id(session: AsyncSession, transaction_id: str) -> Optional[Transaction]:
        """IDでTransaction取得"""
        result = await session.execute(select(Transaction).where(Transaction.id == transaction_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def add_event(session: AsyncSession, transaction_id: str, event: Dict[str, Any]) -> Optional[Transaction]:
        """Transactionにイベント追加"""
        transaction = await TransactionCRUD.get_by_id(session, transaction_id)
        if transaction:
            events = json.loads(transaction.events) if transaction.events else []
            events.append(event)
            transaction.events = json.dumps(events)
            transaction.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(transaction)
        return transaction


class PasskeyCredentialCRUD:
    """PasskeyCredential CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, credential_data: Dict[str, Any]) -> PasskeyCredential:
        """Passkey Credential作成"""
        credential = PasskeyCredential(
            credential_id=credential_data["credential_id"],
            user_id=credential_data["user_id"],
            public_key_cose=credential_data["public_key_cose"],
            counter=credential_data.get("counter", 0),
            transports=json.dumps(credential_data.get("transports", []))
        )
        session.add(credential)
        await session.commit()
        await session.refresh(credential)
        return credential

    @staticmethod
    async def get_by_credential_id(session: AsyncSession, credential_id: str) -> Optional[PasskeyCredential]:
        """Credential IDでPasskey取得"""
        result = await session.execute(
            select(PasskeyCredential).where(PasskeyCredential.credential_id == credential_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_user_id(session: AsyncSession, user_id: str) -> List[PasskeyCredential]:
        """User IDで全Passkey取得"""
        result = await session.execute(
            select(PasskeyCredential).where(PasskeyCredential.user_id == user_id)
        )
        return list(result.scalars().all())

    @staticmethod
    async def update_counter(session: AsyncSession, credential_id: str, new_counter: int) -> Optional[PasskeyCredential]:
        """Signature counter更新（リプレイ攻撃対策）"""
        credential = await PasskeyCredentialCRUD.get_by_credential_id(session, credential_id)
        if credential:
            credential.counter = new_counter
            await session.commit()
            await session.refresh(credential)
        return credential
