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
