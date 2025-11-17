"""
Tests for common/database.py

Tests cover:
- Database initialization
- CRUD operations for all models (Product, User, Mandate, Transaction, etc.)
- Data integrity and constraints
- Async database operations
"""

import pytest
import json
from datetime import datetime, timezone, timedelta

from common.database import (
    DatabaseManager,
    Product,
    User,
    Mandate,
    Transaction,
    PasskeyCredential,
    PaymentMethod,
    TransactionHistory,
    AgentSession,
    Receipt,
    ProductCRUD,
    UserCRUD,
    MandateCRUD,
    TransactionCRUD,
    PasskeyCredentialCRUD,
    PaymentMethodCRUD,
    TransactionHistoryCRUD,
    AgentSessionCRUD,
    ReceiptCRUD,
)


class TestDatabaseManager:
    """Test DatabaseManager functionality"""

    @pytest.mark.asyncio
    async def test_init_db(self, db_manager):
        """Test database initialization"""
        # Database should be initialized in fixture
        async with db_manager.get_session() as session:
            # Session should be valid
            assert session is not None


class TestProductCRUD:
    """Test Product CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_product(self, db_session, sample_product_data):
        """Test product creation"""
        product = await ProductCRUD.create(db_session, sample_product_data)

        assert product.id is not None
        assert product.sku == sample_product_data["sku"]
        assert product.name == sample_product_data["name"]
        assert product.price == sample_product_data["price"]
        assert product.inventory_count == sample_product_data["inventory_count"]

    @pytest.mark.asyncio
    async def test_get_product_by_id(self, db_session, sample_product_data):
        """Test getting product by ID"""
        created_product = await ProductCRUD.create(db_session, sample_product_data)

        retrieved_product = await ProductCRUD.get_by_id(db_session, created_product.id)

        assert retrieved_product is not None
        assert retrieved_product.id == created_product.id
        assert retrieved_product.sku == created_product.sku

    @pytest.mark.asyncio
    async def test_get_product_by_sku(self, db_session, sample_product_data):
        """Test getting product by SKU"""
        await ProductCRUD.create(db_session, sample_product_data)

        retrieved_product = await ProductCRUD.get_by_sku(
            db_session, sample_product_data["sku"]
        )

        assert retrieved_product is not None
        assert retrieved_product.sku == sample_product_data["sku"]

    @pytest.mark.asyncio
    async def test_search_products(self, db_session, sample_product_data):
        """Test product search"""
        await ProductCRUD.create(db_session, sample_product_data)

        # Search by name
        results = await ProductCRUD.search(db_session, "Test")
        assert len(results) >= 1
        assert any(p.name == sample_product_data["name"] for p in results)

    @pytest.mark.asyncio
    async def test_update_inventory(self, db_session, sample_product_data):
        """Test inventory update"""
        product = await ProductCRUD.create(db_session, sample_product_data)
        original_count = product.inventory_count

        updated_product = await ProductCRUD.update_inventory(
            db_session, product.id, delta=-2
        )

        assert updated_product.inventory_count == original_count - 2

    @pytest.mark.asyncio
    async def test_product_to_dict(self, db_session, sample_product_data):
        """Test product to dict conversion"""
        product = await ProductCRUD.create(db_session, sample_product_data)
        product_dict = product.to_dict()

        assert product_dict["sku"] == sample_product_data["sku"]
        assert product_dict["name"] == sample_product_data["name"]
        assert "created_at" in product_dict
        assert "updated_at" in product_dict


class TestUserCRUD:
    """Test User CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_user(self, db_session, sample_user_data):
        """Test user creation"""
        user = await UserCRUD.create(db_session, sample_user_data)

        assert user.id is not None
        assert user.display_name == sample_user_data["display_name"]
        assert user.email == sample_user_data["email"]
        assert user.is_active == 1

    @pytest.mark.asyncio
    async def test_get_user_by_id(self, db_session, sample_user_data):
        """Test getting user by ID"""
        created_user = await UserCRUD.create(db_session, sample_user_data)

        retrieved_user = await UserCRUD.get_by_id(db_session, created_user.id)

        assert retrieved_user is not None
        assert retrieved_user.id == created_user.id

    @pytest.mark.asyncio
    async def test_get_user_by_email(self, db_session, sample_user_data):
        """Test getting user by email"""
        await UserCRUD.create(db_session, sample_user_data)

        retrieved_user = await UserCRUD.get_by_email(
            db_session, sample_user_data["email"]
        )

        assert retrieved_user is not None
        assert retrieved_user.email == sample_user_data["email"]

    @pytest.mark.asyncio
    async def test_user_to_dict(self, db_session, sample_user_data):
        """Test user to dict conversion"""
        user = await UserCRUD.create(db_session, sample_user_data)
        user_dict = user.to_dict()

        assert user_dict["username"] == sample_user_data["display_name"]
        assert user_dict["email"] == sample_user_data["email"]
        assert user_dict["is_active"] is True


class TestMandateCRUD:
    """Test Mandate CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_mandate(self, db_session, sample_mandate_data):
        """Test mandate creation"""
        mandate = await MandateCRUD.create(db_session, sample_mandate_data)

        assert mandate.id is not None
        assert mandate.type == sample_mandate_data["type"]
        assert mandate.status == sample_mandate_data["status"]
        assert mandate.issuer == sample_mandate_data["issuer"]

    @pytest.mark.asyncio
    async def test_get_mandate_by_id(self, db_session, sample_mandate_data):
        """Test getting mandate by ID"""
        created_mandate = await MandateCRUD.create(db_session, sample_mandate_data)

        retrieved_mandate = await MandateCRUD.get_by_id(db_session, created_mandate.id)

        assert retrieved_mandate is not None
        assert retrieved_mandate.id == created_mandate.id

    @pytest.mark.asyncio
    async def test_update_mandate_status(self, db_session, sample_mandate_data):
        """Test mandate status update"""
        mandate = await MandateCRUD.create(db_session, sample_mandate_data)

        updated_mandate = await MandateCRUD.update_status(
            db_session, mandate.id, "signed"
        )

        assert updated_mandate.status == "signed"

    @pytest.mark.asyncio
    async def test_get_mandates_by_status(self, db_session, sample_mandate_data):
        """Test getting mandates by status"""
        await MandateCRUD.create(db_session, sample_mandate_data)

        mandates = await MandateCRUD.get_by_status(
            db_session, sample_mandate_data["status"]
        )

        assert len(mandates) >= 1


class TestTransactionCRUD:
    """Test Transaction CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_transaction(self, db_session, sample_transaction_data):
        """Test transaction creation"""
        transaction = await TransactionCRUD.create(db_session, sample_transaction_data)

        assert transaction.id is not None
        assert transaction.intent_id == sample_transaction_data["intent_id"]
        assert transaction.cart_id == sample_transaction_data["cart_id"]
        assert transaction.status == sample_transaction_data["status"]

    @pytest.mark.asyncio
    async def test_add_event_to_transaction(self, db_session, sample_transaction_data):
        """Test adding event to transaction"""
        transaction = await TransactionCRUD.create(db_session, sample_transaction_data)

        event = {
            "type": "status_change",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {"from": "pending", "to": "completed"}
        }

        updated_transaction = await TransactionCRUD.add_event(
            db_session, transaction.id, event
        )

        events = json.loads(updated_transaction.events)
        assert len(events) == 1
        assert events[0]["type"] == "status_change"


class TestPasskeyCredentialCRUD:
    """Test PasskeyCredential CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_passkey_credential(self, db_session):
        """Test passkey credential creation"""
        credential_data = {
            "credential_id": "cred_001",
            "user_id": "user_001",
            "public_key_cose": "base64_encoded_public_key",
            "counter": 0,
            "transports": ["usb", "nfc"]
        }

        credential = await PasskeyCredentialCRUD.create(db_session, credential_data)

        assert credential.credential_id == "cred_001"
        assert credential.user_id == "user_001"
        assert credential.counter == 0

    @pytest.mark.asyncio
    async def test_get_passkey_by_credential_id(self, db_session):
        """Test getting passkey by credential ID"""
        credential_data = {
            "credential_id": "cred_002",
            "user_id": "user_002",
            "public_key_cose": "base64_encoded_public_key",
            "counter": 0
        }

        await PasskeyCredentialCRUD.create(db_session, credential_data)

        retrieved_credential = await PasskeyCredentialCRUD.get_by_credential_id(
            db_session, "cred_002"
        )

        assert retrieved_credential is not None
        assert retrieved_credential.credential_id == "cred_002"

    @pytest.mark.asyncio
    async def test_update_passkey_counter(self, db_session):
        """Test updating passkey counter"""
        credential_data = {
            "credential_id": "cred_003",
            "user_id": "user_003",
            "public_key_cose": "base64_encoded_public_key",
            "counter": 0
        }

        await PasskeyCredentialCRUD.create(db_session, credential_data)

        updated_credential = await PasskeyCredentialCRUD.update_counter(
            db_session, "cred_003", 5
        )

        assert updated_credential.counter == 5


class TestPaymentMethodCRUD:
    """Test PaymentMethod CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_payment_method(self, db_session):
        """Test payment method creation"""
        payment_method_data = {
            "id": "pm_001",
            "user_id": "user_001",
            "payment_method": {
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "display_name": "Visa ****4242"
            }
        }

        payment_method = await PaymentMethodCRUD.create(db_session, payment_method_data)

        assert payment_method.id == "pm_001"
        assert payment_method.user_id == "user_001"

    @pytest.mark.asyncio
    async def test_payment_method_to_dict(self, db_session):
        """Test payment method to_dict (PCI safe)"""
        payment_method_data = {
            "id": "pm_002",
            "user_id": "user_002",
            "payment_method": {
                "type": "card",
                "brand": "mastercard",
                "last4": "5555",
                "display_name": "Mastercard ****5555",
                "card_number": "5555555555555555",  # PCI sensitive
                "cvv": "123"  # PCI sensitive
            }
        }

        payment_method = await PaymentMethodCRUD.create(db_session, payment_method_data)
        safe_dict = payment_method.to_dict()

        # Should not include PCI sensitive data
        assert "card_number" not in safe_dict
        assert "cvv" not in safe_dict

        # Should include safe data
        assert safe_dict["brand"] == "mastercard"
        assert safe_dict["last4"] == "5555"


class TestTransactionHistoryCRUD:
    """Test TransactionHistory CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_transaction_history(self, db_session):
        """Test transaction history creation"""
        history_data = {
            "payer_id": "user_001",
            "amount_value": 10000,
            "currency": "JPY",
            "risk_score": 25
        }

        history = await TransactionHistoryCRUD.create(db_session, history_data)

        assert history.id is not None
        assert history.payer_id == "user_001"
        assert history.amount_value == 10000
        assert history.risk_score == 25

    @pytest.mark.asyncio
    async def test_get_transaction_history_by_payer_id(self, db_session):
        """Test getting transaction history by payer ID"""
        history_data = {
            "payer_id": "user_002",
            "amount_value": 5000,
            "currency": "JPY",
            "risk_score": 10
        }

        await TransactionHistoryCRUD.create(db_session, history_data)

        histories = await TransactionHistoryCRUD.get_by_payer_id(
            db_session, "user_002", days=30
        )

        assert len(histories) >= 1
        assert histories[0].payer_id == "user_002"


class TestAgentSessionCRUD:
    """Test AgentSession CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_agent_session(self, db_session):
        """Test agent session creation"""
        session_data = {
            "session_id": "sess_001",
            "user_id": "user_001",
            "session_data": {"state": "active", "step": 1}
        }

        agent_session = await AgentSessionCRUD.create(db_session, session_data)

        assert agent_session.session_id == "sess_001"
        assert agent_session.user_id == "user_001"

    @pytest.mark.asyncio
    async def test_update_session_data(self, db_session):
        """Test updating agent session data"""
        session_data = {
            "session_id": "sess_002",
            "user_id": "user_002",
            "session_data": {"state": "active", "step": 1}
        }

        await AgentSessionCRUD.create(db_session, session_data)

        new_session_data = {"state": "active", "step": 2}
        updated_session = await AgentSessionCRUD.update_session_data(
            db_session, "sess_002", new_session_data
        )

        updated_data = json.loads(updated_session.session_data)
        assert updated_data["step"] == 2


class TestReceiptCRUD:
    """Test Receipt CRUD operations"""

    @pytest.mark.asyncio
    async def test_create_receipt(self, db_session):
        """Test receipt creation"""
        receipt_data = {
            "user_id": "user_001",
            "transaction_id": "txn_001",
            "receipt_url": "https://example.com/receipts/receipt_001.pdf",
            "amount": {"value": "100.00", "currency": "JPY"},
            "payment_timestamp": "2025-11-17T00:00:00Z"
        }

        receipt = await ReceiptCRUD.create(db_session, receipt_data)

        assert receipt.id is not None
        assert receipt.user_id == "user_001"
        assert receipt.transaction_id == "txn_001"
        assert receipt.amount_value == 10000  # 100.00 * 100 = 10000 cents

    @pytest.mark.asyncio
    async def test_get_receipts_by_user_id(self, db_session):
        """Test getting receipts by user ID"""
        receipt_data = {
            "user_id": "user_002",
            "transaction_id": "txn_002",
            "receipt_url": "https://example.com/receipts/receipt_002.pdf",
            "amount": {"value": "50.00", "currency": "JPY"},
            "payment_timestamp": "2025-11-17T00:00:00Z"
        }

        await ReceiptCRUD.create(db_session, receipt_data)

        receipts = await ReceiptCRUD.get_by_user_id(db_session, "user_002")

        assert len(receipts) >= 1
        assert receipts[0].user_id == "user_002"

    @pytest.mark.asyncio
    async def test_receipt_to_dict(self, db_session):
        """Test receipt to dict conversion"""
        receipt_data = {
            "user_id": "user_003",
            "transaction_id": "txn_003",
            "receipt_url": "https://example.com/receipts/receipt_003.pdf",
            "amount": {"value": "75.50", "currency": "JPY"},
            "payment_timestamp": "2025-11-17T00:00:00Z"
        }

        receipt = await ReceiptCRUD.create(db_session, receipt_data)
        receipt_dict = receipt.to_dict()

        assert receipt_dict["user_id"] == "user_003"
        assert receipt_dict["amount"]["value"] == "75.5"  # cents to decimal
        assert receipt_dict["amount"]["currency"] == "JPY"
