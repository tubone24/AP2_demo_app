"""
Pytest configuration and fixtures for AP2 Demo App v2 tests
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from typing import AsyncGenerator

# Database imports
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
    Base
)

# Crypto imports
from common.crypto import (
    KeyManager,
    SignatureManager,
    SecureStorage,
    WebAuthnChallengeManager,
    DeviceAttestationManager
)


@pytest.fixture(scope="session")
def event_loop():
    """
    Create an event loop for async tests
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def temp_keys_dir():
    """
    Temporary directory for test keys
    """
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def temp_db_path():
    """
    Temporary database path for tests
    """
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = temp_file.name
    temp_file.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def key_manager(temp_keys_dir):
    """
    KeyManager instance with temporary keys directory
    """
    return KeyManager(keys_directory=temp_keys_dir)


@pytest.fixture
def signature_manager(key_manager):
    """
    SignatureManager instance
    """
    return SignatureManager(key_manager=key_manager)


@pytest.fixture
def secure_storage(temp_keys_dir):
    """
    SecureStorage instance with temporary storage directory
    """
    storage_dir = Path(temp_keys_dir) / "secure_storage"
    return SecureStorage(storage_directory=str(storage_dir))


@pytest.fixture
def webauthn_challenge_manager():
    """
    WebAuthnChallengeManager instance
    """
    return WebAuthnChallengeManager(challenge_ttl_seconds=60)


@pytest.fixture
def device_attestation_manager(key_manager):
    """
    DeviceAttestationManager instance
    """
    return DeviceAttestationManager(key_manager=key_manager)


@pytest.fixture
async def db_manager(temp_db_path) -> AsyncGenerator[DatabaseManager, None]:
    """
    DatabaseManager instance with temporary SQLite database
    """
    db_url = f"sqlite+aiosqlite:///{temp_db_path}"
    manager = DatabaseManager(database_url=db_url)
    await manager.init_db()
    yield manager
    await manager.engine.dispose()


@pytest.fixture
async def db_session(db_manager):
    """
    Database session for testing
    """
    async with db_manager.get_session() as session:
        yield session


@pytest.fixture
def test_passphrase():
    """
    Test passphrase for key encryption
    """
    return "test_passphrase_secure_12345"


@pytest.fixture
def sample_product_data():
    """
    Sample product data for testing
    """
    return {
        "sku": "TEST-SKU-001",
        "name": "Test Product",
        "description": "A test product for unit testing",
        "price": 1000,
        "inventory_count": 10,
        "image_url": "https://example.com/test.jpg",
        "metadata": {"category": "test", "tags": ["test"]}
    }


@pytest.fixture
def sample_user_data():
    """
    Sample user data for testing
    """
    return {
        "display_name": "Test User",
        "email": "test@example.com",
        "hashed_password": "hashed_password_123",
        "is_active": 1
    }


@pytest.fixture
def sample_mandate_data():
    """
    Sample mandate data for testing
    """
    return {
        "type": "IntentMandate",
        "status": "draft",
        "payload": {
            "intent": "Buy running shoes",
            "constraints": {"max_price": 10000}
        },
        "issuer": "did:ap2:agent:shopping_agent"
    }


@pytest.fixture
def sample_transaction_data():
    """
    Sample transaction data for testing
    """
    return {
        "intent_id": "intent_001",
        "cart_id": "cart_001",
        "payment_id": "payment_001",
        "status": "pending",
        "events": []
    }


@pytest.fixture(autouse=True)
def setup_test_env(monkeypatch):
    """
    Setup test environment variables for all tests
    """
    import os

    # Set required passphrases for agent initialization
    monkeypatch.setenv("AP2_CREDENTIAL_PROVIDER_PASSPHRASE", "test_passphrase_credential_provider_123")
    monkeypatch.setenv("AP2_SHOPPING_AGENT_PASSPHRASE", "test_passphrase_shopping_agent_123")
    monkeypatch.setenv("AP2_MERCHANT_PASSPHRASE", "test_passphrase_merchant_123")
    monkeypatch.setenv("AP2_MERCHANT_AGENT_PASSPHRASE", "test_passphrase_merchant_agent_123")
    monkeypatch.setenv("AP2_PAYMENT_PROCESSOR_PASSPHRASE", "test_passphrase_payment_processor_123")
    monkeypatch.setenv("AP2_PAYMENT_NETWORK_PASSPHRASE", "test_passphrase_payment_network_123")

    # Set other environment variables
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")


@pytest.fixture
def credential_provider_client(db_manager):
    """
    FastAPI TestClient for Credential Provider service

    Note: This fixture requires the credential_provider service to be importable.
    Since we're testing endpoints, we use mocking to avoid full service initialization.
    """
    from fastapi.testclient import TestClient
    from unittest.mock import Mock, patch

    # Mock the service to avoid full initialization
    with patch('services.credential_provider.provider.CredentialProviderService') as MockService:
        mock_service = Mock()
        mock_service.db_manager = db_manager
        MockService.return_value = mock_service

        # Import and create test client
        # Note: Actual implementation would require proper service setup
        # For now, we'll use a minimal mock
        from fastapi import FastAPI

        app = FastAPI()

        # Register minimal endpoints for testing
        @app.get("/payment-methods/{user_id}")
        async def get_payment_methods(user_id: str):
            from common.database import PaymentMethodCRUD
            async with db_manager.get_session() as session:
                methods = await PaymentMethodCRUD.get_by_user_id(session, user_id)
                return {
                    "user_id": user_id,
                    "payment_methods": [
                        {
                            "id": m.id,
                            "user_id": m.user_id,
                            "payment_data": m.payment_data
                        } for m in methods
                    ]
                }

        @app.post("/payment-methods")
        async def add_payment_method(request: dict):
            from common.database import PaymentMethodCRUD
            import uuid
            async with db_manager.get_session() as session:
                pm_id = f"pm_{uuid.uuid4().hex[:8]}"
                await PaymentMethodCRUD.create(session, {
                    "id": pm_id,
                    "user_id": request["user_id"],
                    "payment_method": request["payment_method"]
                })
                return {"id": pm_id, "user_id": request["user_id"]}

        @app.delete("/payment-methods/{payment_method_id}")
        async def delete_payment_method(payment_method_id: str):
            from common.database import PaymentMethodCRUD
            async with db_manager.get_session() as session:
                pm = await PaymentMethodCRUD.get_by_id(session, payment_method_id)
                if not pm:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=404, detail="Payment method not found")
                await PaymentMethodCRUD.delete(session, payment_method_id)
                return {"status": "deleted"}

        @app.post("/tokenize-payment-method")
        async def tokenize_payment_method(request: dict):
            from common.database import PaymentMethodCRUD
            from datetime import datetime, timezone, timedelta
            import json

            async with db_manager.get_session() as session:
                pm = await PaymentMethodCRUD.get_by_id(session, request["payment_method_id"])
                if not pm:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=404, detail="Payment method not found")

                payment_data = json.loads(pm.payment_data)
                return {
                    "token": f"tok_{pm.id}",
                    "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat(),
                    "card_last4": payment_data.get("card_last4"),
                    "card_brand": payment_data.get("card_brand")
                }

        @app.post("/passkey-public-key")
        async def get_passkey_public_key(request: dict):
            from common.database import PasskeyCredentialCRUD

            async with db_manager.get_session() as session:
                cred = await PasskeyCredentialCRUD.get_by_credential_id(session, request["credential_id"])
                if not cred:
                    from fastapi import HTTPException
                    raise HTTPException(status_code=404, detail="Credential not found")

                return {
                    "public_key_cose": cred.public_key_cose,
                    "user_id": cred.user_id
                }

        @app.post("/receipts")
        async def receive_receipt(receipt_data: dict):
            from common.database import ReceiptCRUD

            if not all(k in receipt_data for k in ["transaction_id", "receipt_url", "payer_id"]):
                from fastapi import HTTPException
                raise HTTPException(status_code=400, detail="Missing required fields")

            async with db_manager.get_session() as session:
                # Map fields to what ReceiptCRUD.create expects
                create_data = {
                    "user_id": receipt_data["payer_id"],  # Map payer_id to user_id
                    "transaction_id": receipt_data["transaction_id"],
                    "receipt_url": receipt_data["receipt_url"],
                    "amount": receipt_data.get("amount", {}),
                    "payment_timestamp": receipt_data.get("timestamp")  # Map timestamp to payment_timestamp
                }
                await ReceiptCRUD.create(session, create_data)

            return {
                "status": "received",
                "transaction_id": receipt_data["transaction_id"]
            }

        @app.get("/receipts/{user_id}")
        async def get_receipts(user_id: str):
            from common.database import ReceiptCRUD

            async with db_manager.get_session() as session:
                receipts = await ReceiptCRUD.get_by_user_id(session, user_id)
                return {
                    "user_id": user_id,
                    "receipts": [
                        {
                            "transaction_id": r.transaction_id,
                            "receipt_url": r.receipt_url,
                            "amount": r.amount_value,  # Fixed: use amount_value
                            "currency": r.currency
                        } for r in receipts
                    ],
                    "total_count": len(receipts)
                }

        client = TestClient(app)
        yield client
