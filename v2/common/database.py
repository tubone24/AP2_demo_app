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
    image_url = Column(String, nullable=True)  # 内部用: フロントエンド表示用
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
            "image_url": self.image_url,
            "metadata": json.loads(self.product_metadata) if self.product_metadata else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class User(Base):
    """
    usersテーブル（メール/パスワード認証 または Passkey認証）

    AP2仕様準拠:
    - email: PaymentMandate.payer_emailとして使用（Passkey認証時はオプショナル）
    - id: 内部識別子（UUID）
    - is_active: アカウント有効フラグ
    - hashed_password: bcryptハッシュ化パスワード（Passkey認証時は不要）

    AP2仕様: HTTPセッション認証方式は仕様外（実装の自由度あり）
    Mandate署名認証はCredential ProviderのPasskeyで実施（AP2準拠）

    AP2完全準拠: Passkeyはパスワードレス認証のため、emailとhashed_passwordはオプショナル
    """
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    display_name = Column(String, nullable=False)  # username
    email = Column(String, unique=True, nullable=True, index=True)  # AP2 payer_email（Passkey時はNone可）
    hashed_password = Column(String, nullable=True)  # bcryptハッシュ（Passkey時はNone）
    is_active = Column(Integer, nullable=False, default=1)  # SQLiteはBooleanがないためIntegerを使用
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "username": self.display_name,  # Pydanticモデルに合わせる
            "email": self.email,
            "is_active": bool(self.is_active),
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


class PaymentMethod(Base):
    """
    payment_methodsテーブル（AP2完全準拠）

    Credential Providerで管理する支払い方法
    AP2仕様:
    - user_id: ユーザーID（Credential Provider内部のID）
    - payment_method_id: 支払い方法ID（pm_xxxxx形式）
    - type: card, bank_account, digital_wallet等
    - payment_data: 支払い方法の詳細情報（JSON）
        - brand, last4, expiry_month, expiry_year, billing_address等
    - created_at: 作成日時
    """
    __tablename__ = "payment_methods"

    id = Column(String, primary_key=True)  # pm_xxxxx形式
    user_id = Column(String, nullable=False, index=True)
    payment_data = Column(Text, nullable=False)  # JSON as text
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        data = json.loads(self.payment_data) if self.payment_data else {}
        data["id"] = self.id
        return data


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


class TransactionHistory(Base):
    """
    transaction_historyテーブル

    リスク評価エンジンのための取引履歴を保存
    - id (uuid)
    - payer_id (user_id)
    - amount_value (cents)
    - currency (JPY, USD, etc.)
    - risk_score (0-100)
    - timestamp
    """
    __tablename__ = "transaction_history"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    payer_id = Column(String, nullable=False, index=True)
    amount_value = Column(Integer, nullable=False)  # cents
    currency = Column(String, nullable=False, default="JPY")
    risk_score = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "payer_id": self.payer_id,
            "amount_value": self.amount_value,
            "currency": self.currency,
            "risk_score": self.risk_score,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class AgentSession(Base):
    """
    agent_sessionsテーブル

    Shopping Agentのセッション管理
    - session_id (uuid, primary key)
    - user_id (user_id)
    - session_data (json) - セッション状態を保存
    - created_at
    - updated_at
    - expires_at
    """
    __tablename__ = "agent_sessions"

    session_id = Column(String, primary_key=True)
    user_id = Column(String, nullable=False, index=True)
    session_data = Column(Text, nullable=False)  # JSON as text
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=False, index=True)  # セッション有効期限

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "session_data": json.loads(self.session_data) if self.session_data else {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class Receipt(Base):
    """
    receiptsテーブル

    AP2 Step 29対応: Payment Processorから送信された領収書を永続化
    - id (uuid, primary key)
    - user_id (payer_id)
    - transaction_id (関連するtransaction_id)
    - receipt_url (領収書PDFのURL)
    - amount_value (cents)
    - currency (JPY, USD, etc.)
    - payment_timestamp (決済実行時刻)
    - received_at (領収書受信時刻)
    """
    __tablename__ = "receipts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, nullable=False, index=True)
    transaction_id = Column(String, nullable=False, index=True)
    receipt_url = Column(String, nullable=False)
    amount_value = Column(Integer, nullable=False)  # cents
    currency = Column(String, nullable=False, default="JPY")
    payment_timestamp = Column(DateTime, nullable=False)
    received_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "transaction_id": self.transaction_id,
            "receipt_url": self.receipt_url,
            "amount": {
                "value": str(self.amount_value / 100),  # centsをdecimalに変換
                "currency": self.currency
            },
            "payment_timestamp": self.payment_timestamp.isoformat() if self.payment_timestamp else None,
            "received_at": self.received_at.isoformat() if self.received_at else None,
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
        metadata = product_data.get("metadata", {})
        image_url = metadata.get("image_url") if metadata else None

        product = Product(
            id=product_data.get("id", str(uuid.uuid4())),
            sku=product_data["sku"],
            name=product_data["name"],
            description=product_data["description"],
            price=product_data["price"],
            inventory_count=product_data.get("inventory_count", 0),
            image_url=image_url,
            product_metadata=json.dumps(metadata) if metadata else None
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
        from sqlalchemy import or_
        import re
        import logging

        logger = logging.getLogger(__name__)

        # クエリを単語に分割して柔軟な検索を実現
        # 「ランニングシューズが欲しい」→「ランニングシューズ」「ランニング」「シューズ」
        keywords = []

        # まず助詞・助動詞を除去（簡易版）
        # 「欲しい」「ください」「たい」なども除去
        stop_words = ['が', 'を', 'に', 'へ', 'と', 'で', 'から', 'や', 'も', 'は', 'の',
                      'です', 'ます', 'たい', 'ほしい', '欲しい', 'ください', '下さい']

        cleaned_query = query
        for stop_word in stop_words:
            cleaned_query = cleaned_query.replace(stop_word, ' ')

        logger.info(f"[ProductCRUD.search] Original query: '{query}' -> Cleaned: '{cleaned_query}'")

        # スペースで分割して2文字以上のキーワードを抽出
        words = [w.strip() for w in cleaned_query.split() if len(w.strip()) >= 2]

        if words:
            keywords = words
        else:
            # スペースで分割できない場合、元のクエリを使用
            keywords = [query]

        # さらに、元のクエリも検索対象に追加（完全一致の可能性のため）
        if query not in keywords:
            keywords.append(query)

        logger.info(f"[ProductCRUD.search] Extracted keywords: {keywords}")

        # 各キーワードで名前または説明を検索（OR条件）
        conditions = []
        for keyword in keywords:
            if keyword:  # 空文字列を除外
                conditions.append(Product.name.contains(keyword))
                conditions.append(Product.description.contains(keyword))

        if not conditions:
            # フォールバック: 全商品を返す
            stmt = select(Product).limit(limit)
        else:
            stmt = select(Product).where(or_(*conditions)).limit(limit)

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

    @staticmethod
    async def get_all_with_stock(session: AsyncSession, limit: int = 100) -> List[Product]:
        """在庫がある商品のみ取得（AP2準拠）"""
        stmt = select(Product).where(Product.inventory_count > 0).limit(limit)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def delete(session: AsyncSession, product_id: str) -> bool:
        """商品削除"""
        product = await ProductCRUD.get_by_id(session, product_id)
        if product:
            await session.delete(product)
            await session.commit()
            return True
        return False


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
    async def update_status(session: AsyncSession, mandate_id: str, status: str, payload: Dict[str, Any] = None) -> Optional[Mandate]:
        """Mandateステータス更新（オプションでpayloadも更新）"""
        mandate = await MandateCRUD.get_by_id(session, mandate_id)
        if mandate:
            mandate.status = status
            if payload is not None:
                mandate.payload = json.dumps(payload)
            mandate.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(mandate)
        return mandate

    @staticmethod
    async def get_by_status(session: AsyncSession, status: str, limit: int = 100) -> List[Mandate]:
        """ステータスでMandate取得"""
        result = await session.execute(
            select(Mandate).where(Mandate.status == status).order_by(Mandate.issued_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


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

    @staticmethod
    async def get_by_status(session: AsyncSession, status: str, limit: int = 100) -> List[Transaction]:
        """ステータスでTransaction取得"""
        result = await session.execute(
            select(Transaction).where(Transaction.status == status).order_by(Transaction.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def list_all(session: AsyncSession, limit: int = 100) -> List[Transaction]:
        """全Transaction取得"""
        result = await session.execute(
            select(Transaction).order_by(Transaction.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


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


class UserCRUD:
    """User CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, user_data: Dict[str, Any]) -> User:
        """
        ユーザー作成（AP2完全準拠）

        Args:
            user_data: ユーザーデータ
                - display_name: 表示名（必須）
                - email: メールアドレス（オプショナル、Passkey認証時はNone可）
                - hashed_password: ハッシュ化パスワード（オプショナル、Passkey認証時はNone）
                - id: ユーザーID（オプショナル、未指定時はUUID生成）
                - is_active: アクティブフラグ（オプショナル、デフォルト1）
        """
        user = User(
            id=user_data.get("id", user_data.get("user_id", str(uuid.uuid4()))),
            display_name=user_data["display_name"],
            email=user_data.get("email"),  # AP2準拠: Passkey認証時はNone可
            hashed_password=user_data.get("hashed_password"),  # AP2準拠: Passkey認証時はNone
            is_active=user_data.get("is_active", 1)
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: str) -> Optional[User]:
        """IDでユーザー取得"""
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> Optional[User]:
        """メールアドレスでユーザー取得"""
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    @staticmethod
    async def list_all(session: AsyncSession, limit: int = 100) -> List[User]:
        """全ユーザー取得"""
        result = await session.execute(
            select(User).order_by(User.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())


class TransactionHistoryCRUD:
    """TransactionHistory CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, history_data: Dict[str, Any]) -> TransactionHistory:
        """取引履歴作成"""
        history = TransactionHistory(
            id=history_data.get("id", str(uuid.uuid4())),
            payer_id=history_data["payer_id"],
            amount_value=history_data["amount_value"],
            currency=history_data.get("currency", "JPY"),
            risk_score=history_data["risk_score"]
        )
        session.add(history)
        await session.commit()
        await session.refresh(history)
        return history

    @staticmethod
    async def get_by_payer_id(
        session: AsyncSession,
        payer_id: str,
        days: int = 30,
        limit: int = 100
    ) -> List[TransactionHistory]:
        """
        指定されたユーザーの取引履歴を取得（過去N日間）

        Args:
            session: データベースセッション
            payer_id: ユーザーID
            days: 過去何日間の履歴を取得するか（デフォルト30日）
            limit: 最大取得件数

        Returns:
            取引履歴リスト
        """
        from datetime import timedelta
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        result = await session.execute(
            select(TransactionHistory)
            .where(TransactionHistory.payer_id == payer_id)
            .where(TransactionHistory.timestamp >= cutoff_date)
            .order_by(TransactionHistory.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @staticmethod
    async def cleanup_old_records(session: AsyncSession, days: int = 30) -> int:
        """
        古い取引履歴を削除

        Args:
            session: データベースセッション
            days: 保持期間（日数）

        Returns:
            削除件数
        """
        from datetime import timedelta
        from sqlalchemy import delete

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)

        stmt = delete(TransactionHistory).where(TransactionHistory.timestamp < cutoff_date)
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if result.rowcount else 0


class AgentSessionCRUD:
    """AgentSession CRUD操作"""

    @staticmethod
    async def create(session: AsyncSession, session_data_input: Dict[str, Any]) -> AgentSession:
        """
        セッション作成

        Args:
            session: データベースセッション
            session_data_input: セッションデータ
                - session_id: セッションID
                - user_id: ユーザーID
                - session_data: セッション状態（dict）
                - expires_at: 有効期限（datetime）
        """
        from datetime import timedelta

        # 有効期限が指定されていない場合は1時間後に設定
        expires_at = session_data_input.get("expires_at")
        if not expires_at:
            expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        agent_session = AgentSession(
            session_id=session_data_input["session_id"],
            user_id=session_data_input["user_id"],
            session_data=json.dumps(session_data_input["session_data"]),
            expires_at=expires_at
        )
        session.add(agent_session)
        await session.commit()
        await session.refresh(agent_session)
        return agent_session

    @staticmethod
    async def get_by_session_id(session: AsyncSession, session_id: str) -> Optional[AgentSession]:
        """セッションID でセッション取得"""
        result = await session.execute(
            select(AgentSession).where(AgentSession.session_id == session_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def update_session_data(
        session: AsyncSession,
        session_id: str,
        new_session_data: Dict[str, Any]
    ) -> Optional[AgentSession]:
        """セッションデータ更新"""
        agent_session = await AgentSessionCRUD.get_by_session_id(session, session_id)
        if agent_session:
            agent_session.session_data = json.dumps(new_session_data)
            agent_session.updated_at = datetime.now(timezone.utc)
            await session.commit()
            await session.refresh(agent_session)
        return agent_session

    @staticmethod
    async def delete_session(session: AsyncSession, session_id: str) -> bool:
        """セッション削除"""
        agent_session = await AgentSessionCRUD.get_by_session_id(session, session_id)
        if agent_session:
            await session.delete(agent_session)
            await session.commit()
            return True
        return False

    @staticmethod
    async def cleanup_expired_sessions(session: AsyncSession) -> int:
        """
        期限切れセッションを削除

        Returns:
            削除件数
        """
        from sqlalchemy import delete

        now = datetime.now(timezone.utc)

        stmt = delete(AgentSession).where(AgentSession.expires_at < now)
        result = await session.execute(stmt)
        await session.commit()

        return result.rowcount if result.rowcount else 0


class PaymentMethodCRUD:
    """PaymentMethod CRUD操作（AP2完全準拠）"""

    @staticmethod
    async def create(session: AsyncSession, payment_method_data: Dict[str, Any]) -> PaymentMethod:
        """
        支払い方法作成

        Args:
            session: AsyncSession
            payment_method_data: {
                "id": "pm_xxxxx",
                "user_id": "usr_xxxxx",
                "payment_method": {
                    "type": "card",
                    "brand": "visa",
                    "last4": "4242",
                    ...
                }
            }

        Returns:
            PaymentMethod
        """
        payment_method = PaymentMethod(
            id=payment_method_data["id"],
            user_id=payment_method_data["user_id"],
            payment_data=json.dumps(payment_method_data["payment_method"])
        )
        session.add(payment_method)
        await session.commit()
        await session.refresh(payment_method)
        return payment_method

    @staticmethod
    async def get_by_user_id(session: AsyncSession, user_id: str) -> List[PaymentMethod]:
        """ユーザーIDで支払い方法を取得"""
        stmt = select(PaymentMethod).where(PaymentMethod.user_id == user_id)
        result = await session.execute(stmt)
        return result.scalars().all()

    @staticmethod
    async def get_by_id(session: AsyncSession, payment_method_id: str) -> Optional[PaymentMethod]:
        """支払い方法IDで取得"""
        stmt = select(PaymentMethod).where(PaymentMethod.id == payment_method_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def delete(session: AsyncSession, payment_method_id: str) -> bool:
        """支払い方法削除"""
        payment_method = await PaymentMethodCRUD.get_by_id(session, payment_method_id)
        if payment_method:
            await session.delete(payment_method)
            await session.commit()
            return True
        return False


class ReceiptCRUD:
    """Receipt CRUD操作（AP2 Step 29対応）"""

    @staticmethod
    async def create(session: AsyncSession, receipt_data: Dict[str, Any]) -> Receipt:
        """
        領収書作成

        Args:
            session: AsyncSession
            receipt_data: {
                "user_id": "user_demo_001",
                "transaction_id": "txn_xxxxx",
                "receipt_url": "http://...",
                "amount": {"value": "8068.00", "currency": "JPY"},
                "payment_timestamp": "2025-10-18T12:34:56Z"
            }

        Returns:
            Receipt
        """
        # amountをcentsに変換
        amount = receipt_data.get("amount", {})
        amount_value = int(float(amount.get("value", "0")) * 100)
        currency = amount.get("currency", "JPY")

        # payment_timestampをdatetimeに変換
        payment_timestamp_str = receipt_data.get("payment_timestamp")
        if payment_timestamp_str:
            payment_timestamp = datetime.fromisoformat(payment_timestamp_str.replace('Z', '+00:00'))
        else:
            payment_timestamp = datetime.now(timezone.utc)

        receipt = Receipt(
            id=receipt_data.get("id", str(uuid.uuid4())),
            user_id=receipt_data["user_id"],
            transaction_id=receipt_data["transaction_id"],
            receipt_url=receipt_data["receipt_url"],
            amount_value=amount_value,
            currency=currency,
            payment_timestamp=payment_timestamp
        )
        session.add(receipt)
        await session.commit()
        await session.refresh(receipt)
        return receipt

    @staticmethod
    async def get_by_user_id(
        session: AsyncSession,
        user_id: str,
        limit: int = 100
    ) -> List[Receipt]:
        """ユーザーIDで領収書を取得（新しい順）"""
        stmt = (
            select(Receipt)
            .where(Receipt.user_id == user_id)
            .order_by(Receipt.received_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def get_by_transaction_id(
        session: AsyncSession,
        transaction_id: str
    ) -> Optional[Receipt]:
        """トランザクションIDで領収書を取得"""
        stmt = select(Receipt).where(Receipt.transaction_id == transaction_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, receipt_id: str) -> Optional[Receipt]:
        """領収書IDで取得"""
        stmt = select(Receipt).where(Receipt.id == receipt_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
