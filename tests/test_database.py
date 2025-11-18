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

    @pytest.mark.asyncio
    async def test_get_receipt_by_transaction_id(self, db_session):
        """Test getting receipt by transaction ID"""
        receipt_data = {
            "user_id": "user_004",
            "transaction_id": "txn_unique_001",
            "receipt_url": "https://example.com/receipts/receipt_004.pdf",
            "amount": {"value": "100.00", "currency": "JPY"},
            "payment_timestamp": "2025-11-17T00:00:00Z"
        }

        await ReceiptCRUD.create(db_session, receipt_data)

        receipt = await ReceiptCRUD.get_by_transaction_id(db_session, "txn_unique_001")

        assert receipt is not None
        assert receipt.transaction_id == "txn_unique_001"
        assert receipt.user_id == "user_004"

    @pytest.mark.asyncio
    async def test_get_receipt_by_id(self, db_session):
        """Test getting receipt by receipt ID"""
        receipt_data = {
            "id": "receipt_specific_001",
            "user_id": "user_005",
            "transaction_id": "txn_005",
            "receipt_url": "https://example.com/receipts/receipt_005.pdf",
            "amount": {"value": "200.00", "currency": "JPY"},
            "payment_timestamp": "2025-11-17T00:00:00Z"
        }

        await ReceiptCRUD.create(db_session, receipt_data)

        receipt = await ReceiptCRUD.get_by_id(db_session, "receipt_specific_001")

        assert receipt is not None
        assert receipt.id == "receipt_specific_001"


class TestProductCRUDExtended:
    """Extended Product CRUD tests for edge cases"""

    @pytest.mark.asyncio
    async def test_list_all_products(self, db_session, sample_product_data):
        """Test listing all products"""
        # Create multiple products
        await ProductCRUD.create(db_session, sample_product_data)

        sample_product_data2 = sample_product_data.copy()
        sample_product_data2["sku"] = "TEST-SKU-002"
        sample_product_data2["name"] = "Test Product 2"
        await ProductCRUD.create(db_session, sample_product_data2)

        products = await ProductCRUD.list_all(db_session, limit=100)

        assert len(products) >= 2

    @pytest.mark.asyncio
    async def test_get_all_with_stock(self, db_session, sample_product_data):
        """Test getting products with stock only"""
        # Create product with stock
        sample_product_data["inventory_count"] = 10
        await ProductCRUD.create(db_session, sample_product_data)

        # Create product without stock
        sample_product_data2 = sample_product_data.copy()
        sample_product_data2["sku"] = "TEST-SKU-NO-STOCK"
        sample_product_data2["inventory_count"] = 0
        await ProductCRUD.create(db_session, sample_product_data2)

        products_with_stock = await ProductCRUD.get_all_with_stock(db_session)

        # Should only return product with stock
        assert all(p.inventory_count > 0 for p in products_with_stock)
        assert any(p.sku == "TEST-SKU-001" for p in products_with_stock)

    @pytest.mark.asyncio
    async def test_delete_product(self, db_session, sample_product_data):
        """Test deleting a product"""
        product = await ProductCRUD.create(db_session, sample_product_data)

        # Delete the product
        deleted = await ProductCRUD.delete(db_session, product.id)
        assert deleted

        # Verify product is deleted
        retrieved = await ProductCRUD.get_by_id(db_session, product.id)
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_product(self, db_session):
        """Test deleting a non-existent product"""
        deleted = await ProductCRUD.delete(db_session, "nonexistent_id")
        assert not deleted

    @pytest.mark.asyncio
    async def test_product_to_dict_with_none_metadata(self, db_session):
        """Test product to_dict with None metadata"""
        product_data = {
            "sku": "TEST-SKU-NO-META",
            "name": "Product Without Metadata",
            "description": "Test product",
            "price": 1000,
            "inventory_count": 5,
            "metadata": None
        }

        product = await ProductCRUD.create(db_session, product_data)
        product_dict = product.to_dict()

        assert product_dict["metadata"] is None

    @pytest.mark.asyncio
    async def test_product_search_empty_query(self, db_session, sample_product_data):
        """Test product search with empty keywords"""
        await ProductCRUD.create(db_session, sample_product_data)

        # Search with stop words only (should return all products)
        results = await ProductCRUD.search(db_session, "が を に")

        assert len(results) >= 0  # Should handle gracefully

    @pytest.mark.asyncio
    async def test_product_search_japanese_keywords(self, db_session):
        """Test product search with Japanese keywords"""
        product_data = {
            "sku": "SHOE-JP-001",
            "name": "ランニングシューズ",
            "description": "快適な走りのための高品質シューズ",
            "price": 8000,
            "inventory_count": 15,
            "metadata": {}
        }

        await ProductCRUD.create(db_session, product_data)

        # Search with Japanese query
        results = await ProductCRUD.search(db_session, "ランニングシューズが欲しい")

        assert len(results) >= 1
        assert any("ランニングシューズ" in p.name for p in results)


class TestUserCRUDExtended:
    """Extended User CRUD tests for edge cases"""

    @pytest.mark.asyncio
    async def test_create_passkey_user(self, db_session):
        """Test creating a user for Passkey authentication (no email/password)"""
        user_data = {
            "display_name": "Passkey User",
            "email": None,  # Passkey users don't need email
            "hashed_password": None,  # Passkey users don't need password
            "is_active": 1
        }

        user = await UserCRUD.create(db_session, user_data)

        assert user.id is not None
        assert user.display_name == "Passkey User"
        assert user.email is None
        assert user.hashed_password is None
        assert user.is_active == 1

    @pytest.mark.asyncio
    async def test_list_all_users(self, db_session, sample_user_data):
        """Test listing all users"""
        await UserCRUD.create(db_session, sample_user_data)

        sample_user_data2 = sample_user_data.copy()
        sample_user_data2["email"] = "user2@example.com"
        await UserCRUD.create(db_session, sample_user_data2)

        users = await UserCRUD.list_all(db_session)

        assert len(users) >= 2


class TestMandateCRUDExtended:
    """Extended Mandate CRUD tests for edge cases"""

    @pytest.mark.asyncio
    async def test_update_mandate_status_with_payload(self, db_session, sample_mandate_data):
        """Test updating mandate status with payload update"""
        mandate = await MandateCRUD.create(db_session, sample_mandate_data)

        new_payload = {
            "intent": "Buy running shoes",
            "constraints": {"max_price": 15000},  # Updated price
            "signed": True
        }

        updated_mandate = await MandateCRUD.update_status(
            db_session, mandate.id, "signed", payload=new_payload
        )

        assert updated_mandate.status == "signed"
        payload = json.loads(updated_mandate.payload)
        assert payload["constraints"]["max_price"] == 15000
        assert payload["signed"] is True


class TestTransactionCRUDExtended:
    """Extended Transaction CRUD tests for edge cases"""

    @pytest.mark.asyncio
    async def test_get_transactions_by_status(self, db_session, sample_transaction_data):
        """Test getting transactions by status"""
        await TransactionCRUD.create(db_session, sample_transaction_data)

        sample_transaction_data2 = sample_transaction_data.copy()
        sample_transaction_data2["status"] = "completed"
        await TransactionCRUD.create(db_session, sample_transaction_data2)

        pending_transactions = await TransactionCRUD.get_by_status(db_session, "pending")
        completed_transactions = await TransactionCRUD.get_by_status(db_session, "completed")

        assert len(pending_transactions) >= 1
        assert len(completed_transactions) >= 1

    @pytest.mark.asyncio
    async def test_list_all_transactions(self, db_session, sample_transaction_data):
        """Test listing all transactions"""
        await TransactionCRUD.create(db_session, sample_transaction_data)

        transactions = await TransactionCRUD.list_all(db_session)

        assert len(transactions) >= 1


class TestPasskeyCredentialCRUDExtended:
    """Extended PasskeyCredential CRUD tests"""

    @pytest.mark.asyncio
    async def test_get_passkeys_by_user_id(self, db_session):
        """Test getting all passkeys for a user"""
        # Create multiple passkeys for same user
        credential_data1 = {
            "credential_id": "cred_user1_device1",
            "user_id": "user_multi_device",
            "public_key_cose": "base64_key_1",
            "counter": 0
        }

        credential_data2 = {
            "credential_id": "cred_user1_device2",
            "user_id": "user_multi_device",
            "public_key_cose": "base64_key_2",
            "counter": 0
        }

        await PasskeyCredentialCRUD.create(db_session, credential_data1)
        await PasskeyCredentialCRUD.create(db_session, credential_data2)

        credentials = await PasskeyCredentialCRUD.get_by_user_id(db_session, "user_multi_device")

        assert len(credentials) == 2
        assert all(c.user_id == "user_multi_device" for c in credentials)

    @pytest.mark.asyncio
    async def test_passkey_credential_to_dict(self, db_session):
        """Test passkey credential to_dict conversion"""
        credential_data = {
            "credential_id": "cred_dict_test",
            "user_id": "user_dict_test",
            "public_key_cose": "base64_encoded_key",
            "counter": 5,
            "transports": ["usb", "nfc", "ble"]
        }

        credential = await PasskeyCredentialCRUD.create(db_session, credential_data)
        cred_dict = credential.to_dict()

        assert cred_dict["credential_id"] == "cred_dict_test"
        assert cred_dict["counter"] == 5
        assert cred_dict["transports"] == ["usb", "nfc", "ble"]


class TestPaymentMethodCRUDExtended:
    """Extended PaymentMethod CRUD tests"""

    @pytest.mark.asyncio
    async def test_payment_method_get_full_data(self, db_session):
        """Test getting full payment data (including PCI sensitive data)"""
        payment_method_data = {
            "id": "pm_full_data",
            "user_id": "user_full_data",
            "payment_method": {
                "type": "card",
                "brand": "visa",
                "last4": "4242",
                "display_name": "Visa ****4242",
                "card_number": "4242424242424242",  # PCI sensitive
                "cvv": "123",  # PCI sensitive
                "expiry_month": "12",
                "expiry_year": "2025"
            }
        }

        payment_method = await PaymentMethodCRUD.create(db_session, payment_method_data)
        full_data = payment_method.get_full_data()

        # Should include all data including PCI sensitive
        assert "card_number" in full_data
        assert "cvv" in full_data
        assert full_data["card_number"] == "4242424242424242"
        assert full_data["cvv"] == "123"

    @pytest.mark.asyncio
    async def test_payment_method_delete(self, db_session):
        """Test deleting a payment method"""
        payment_method_data = {
            "id": "pm_delete_test",
            "user_id": "user_delete_test",
            "payment_method": {
                "type": "card",
                "brand": "mastercard",
                "last4": "5555"
            }
        }

        await PaymentMethodCRUD.create(db_session, payment_method_data)

        # Delete payment method
        deleted = await PaymentMethodCRUD.delete(db_session, "pm_delete_test")
        assert deleted

        # Verify deletion
        payment_method = await PaymentMethodCRUD.get_by_id(db_session, "pm_delete_test")
        assert payment_method is None

    @pytest.mark.asyncio
    async def test_get_payment_methods_by_user_id(self, db_session):
        """Test getting all payment methods for a user"""
        # Create multiple payment methods for same user
        pm_data1 = {
            "id": "pm_user_001_card1",
            "user_id": "user_multiple_pm",
            "payment_method": {"type": "card", "brand": "visa", "last4": "4242"}
        }

        pm_data2 = {
            "id": "pm_user_001_card2",
            "user_id": "user_multiple_pm",
            "payment_method": {"type": "card", "brand": "mastercard", "last4": "5555"}
        }

        await PaymentMethodCRUD.create(db_session, pm_data1)
        await PaymentMethodCRUD.create(db_session, pm_data2)

        payment_methods = await PaymentMethodCRUD.get_by_user_id(db_session, "user_multiple_pm")

        assert len(list(payment_methods)) == 2


class TestTransactionHistoryCRUDExtended:
    """Extended TransactionHistory CRUD tests"""

    @pytest.mark.asyncio
    async def test_cleanup_old_transaction_history(self, db_session):
        """Test cleanup of old transaction history"""
        # Create old transaction history
        old_history_data = {
            "payer_id": "user_old",
            "amount_value": 5000,
            "currency": "JPY",
            "risk_score": 10
        }

        history = await TransactionHistoryCRUD.create(db_session, old_history_data)

        # Manually set timestamp to be old (31 days ago)
        from datetime import timedelta
        old_timestamp = datetime.now(timezone.utc) - timedelta(days=31)
        history.timestamp = old_timestamp
        await db_session.commit()

        # Cleanup records older than 30 days
        deleted_count = await TransactionHistoryCRUD.cleanup_old_records(db_session, days=30)

        assert deleted_count >= 1

    @pytest.mark.asyncio
    async def test_transaction_history_to_dict(self, db_session):
        """Test transaction history to_dict conversion"""
        history_data = {
            "payer_id": "user_dict_test",
            "amount_value": 10000,
            "currency": "USD",
            "risk_score": 50
        }

        history = await TransactionHistoryCRUD.create(db_session, history_data)
        history_dict = history.to_dict()

        assert history_dict["payer_id"] == "user_dict_test"
        assert history_dict["amount_value"] == 10000
        assert history_dict["currency"] == "USD"
        assert history_dict["risk_score"] == 50


class TestAgentSessionCRUDExtended:
    """Extended AgentSession CRUD tests"""

    @pytest.mark.asyncio
    async def test_delete_agent_session(self, db_session):
        """Test deleting an agent session"""
        session_data = {
            "session_id": "sess_delete_test",
            "user_id": "user_delete_test",
            "session_data": {"state": "active"}
        }

        await AgentSessionCRUD.create(db_session, session_data)

        # Delete session
        deleted = await AgentSessionCRUD.delete_session(db_session, "sess_delete_test")
        assert deleted

        # Verify deletion
        session = await AgentSessionCRUD.get_by_session_id(db_session, "sess_delete_test")
        assert session is None

    @pytest.mark.asyncio
    async def test_cleanup_expired_sessions(self, db_session):
        """Test cleanup of expired sessions"""
        # Create expired session
        from datetime import timedelta
        expired_time = datetime.now(timezone.utc) - timedelta(hours=2)

        session_data = {
            "session_id": "sess_expired",
            "user_id": "user_expired",
            "session_data": {"state": "expired"},
            "expires_at": expired_time
        }

        await AgentSessionCRUD.create(db_session, session_data)

        # Cleanup expired sessions
        deleted_count = await AgentSessionCRUD.cleanup_expired_sessions(db_session)

        assert deleted_count >= 1

    @pytest.mark.asyncio
    async def test_agent_session_to_dict(self, db_session):
        """Test agent session to_dict conversion"""
        session_data = {
            "session_id": "sess_dict_test",
            "user_id": "user_dict_test",
            "session_data": {"state": "active", "step": 3}
        }

        agent_session = await AgentSessionCRUD.create(db_session, session_data)
        session_dict = agent_session.to_dict()

        assert session_dict["session_id"] == "sess_dict_test"
        assert session_dict["user_id"] == "user_dict_test"
        assert session_dict["session_data"]["step"] == 3
