"""
Tests for Merchant Registry

Tests cover:
- MerchantRegistry initialization
- Merchant registration
- Merchant DID resolution (local and central registry)
- Merchant search functionality
- DID document conversion
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import tempfile
from pathlib import Path

from common.merchant_registry import MerchantRegistry, MerchantDIDRecord
from common.models import DIDDocument, ServiceEndpoint, VerificationMethod


@pytest.fixture
def temp_db_path():
    """Create temporary database path"""
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    db_path = temp_file.name
    temp_file.close()
    yield db_path
    Path(db_path).unlink(missing_ok=True)


class TestMerchantRegistryInitialization:
    """Test MerchantRegistry initialization"""

    def test_initialization_with_defaults(self, temp_db_path):
        """Test registry initialization with default values"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)

        assert registry.registry_url == "https://registry.ap2-protocol.org"
        assert registry.engine is not None

    def test_initialization_with_custom_registry(self, temp_db_path):
        """Test registry initialization with custom registry URL"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(
            database_url=db_url,
            registry_url="https://custom-registry.example.com"
        )

        assert registry.registry_url == "https://custom-registry.example.com"

    @pytest.mark.asyncio
    async def test_init_db(self, temp_db_path):
        """Test database initialization"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)

        await registry.init_db()

        # Database should be initialized
        assert registry.engine is not None


class TestMerchantRegistration:
    """Test merchant registration"""

    @pytest.mark.asyncio
    async def test_register_merchant_success(self, temp_db_path):
        """Test successful merchant registration"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:nike"
        public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----"

        did_doc = await registry.register_merchant(
            merchant_did=merchant_did,
            name="Nike Store",
            agent_endpoint="https://merchant-agent.nike.com",
            public_key_pem=public_key_pem,
            description="Official Nike Store",
            categories=["shoes", "apparel"],
            payment_methods=["credit_card", "paypal"]
        )

        assert did_doc is not None
        assert did_doc.id == merchant_did
        assert len(did_doc.verificationMethod) == 1
        assert len(did_doc.service) == 1
        assert did_doc.verificationMethod[0].publicKeyPem == public_key_pem

    @pytest.mark.asyncio
    async def test_register_merchant_with_minimal_data(self, temp_db_path):
        """Test merchant registration with minimal required data"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:minimal"
        public_key_pem = "-----BEGIN PUBLIC KEY-----\nminimal_key\n-----END PUBLIC KEY-----"

        did_doc = await registry.register_merchant(
            merchant_did=merchant_did,
            name="Minimal Store",
            agent_endpoint="https://merchant.example.com",
            public_key_pem=public_key_pem
        )

        assert did_doc is not None
        assert did_doc.id == merchant_did


class TestMerchantDIDResolution:
    """Test merchant DID resolution"""

    @pytest.mark.asyncio
    async def test_resolve_from_local_db(self, temp_db_path):
        """Test resolving merchant DID from local database"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        # Register a merchant first
        merchant_did = "did:ap2:merchant:local_test"
        public_key_pem = "-----BEGIN PUBLIC KEY-----\nlocal_key\n-----END PUBLIC KEY-----"

        await registry.register_merchant(
            merchant_did=merchant_did,
            name="Local Test Store",
            agent_endpoint="https://local.example.com",
            public_key_pem=public_key_pem
        )

        # Resolve it
        did_doc = await registry.resolve_merchant_did(merchant_did)

        assert did_doc is not None
        assert did_doc.id == merchant_did
        assert len(did_doc.verificationMethod) == 1
        assert len(did_doc.service) == 1

    @pytest.mark.asyncio
    async def test_resolve_from_central_registry(self, temp_db_path):
        """Test resolving merchant DID from central registry"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:central_test"

        # Mock central registry response
        mock_did_doc = {
            "id": merchant_did,
            "verificationMethod": [
                {
                    "id": f"{merchant_did}#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": merchant_did,
                    "publicKeyPem": "-----BEGIN PUBLIC KEY-----\ncentral_key\n-----END PUBLIC KEY-----"
                }
            ],
            "authentication": ["#key-1"],
            "service": [
                {
                    "id": f"{merchant_did}#merchant-agent",
                    "type": "AP2MerchantAgent",
                    "serviceEndpoint": "https://central.example.com"
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_did_doc

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            did_doc = await registry.resolve_merchant_did(merchant_did)

            assert did_doc is not None
            assert did_doc.id == merchant_did
            mock_client_instance.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_not_found(self, temp_db_path):
        """Test resolving non-existent merchant DID"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:nonexistent"

        # Mock 404 response from central registry
        mock_response = MagicMock()
        mock_response.status_code = 404

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "Not found",
                    request=MagicMock(),
                    response=mock_response
                )
            )
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            did_doc = await registry.resolve_merchant_did(merchant_did)

            assert did_doc is None

    @pytest.mark.asyncio
    async def test_resolve_central_registry_timeout(self, temp_db_path):
        """Test central registry timeout handling"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:timeout_test"

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            did_doc = await registry.resolve_merchant_did(merchant_did)

            assert did_doc is None

    @pytest.mark.asyncio
    async def test_cache_to_local_db(self, temp_db_path):
        """Test caching DID document from central registry to local DB"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        merchant_did = "did:ap2:merchant:cache_test"

        # Mock central registry response
        mock_did_doc = {
            "id": merchant_did,
            "verificationMethod": [
                {
                    "id": f"{merchant_did}#key-1",
                    "type": "Ed25519VerificationKey2020",
                    "controller": merchant_did,
                    "publicKeyPem": "-----BEGIN PUBLIC KEY-----\ncache_key\n-----END PUBLIC KEY-----"
                }
            ],
            "authentication": ["#key-1"],
            "service": [
                {
                    "id": f"{merchant_did}#merchant-agent",
                    "type": "AP2MerchantAgent",
                    "serviceEndpoint": "https://cache.example.com"
                }
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_did_doc

        with patch("httpx.AsyncClient") as mock_async_client:
            mock_client_instance = AsyncMock()
            mock_client_instance.get = AsyncMock(return_value=mock_response)
            mock_async_client.return_value.__aenter__.return_value = mock_client_instance

            # First resolve (from central registry)
            did_doc_1 = await registry.resolve_merchant_did(merchant_did)
            assert did_doc_1 is not None

        # Second resolve (should be from local DB, no HTTP call)
        did_doc_2 = await registry.resolve_merchant_did(merchant_did)
        assert did_doc_2 is not None
        assert did_doc_2.id == merchant_did


class TestMerchantSearch:
    """Test merchant search functionality"""

    @pytest.mark.asyncio
    async def test_search_merchants_by_name(self, temp_db_path):
        """Test searching merchants by name"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        # Register multiple merchants
        await registry.register_merchant(
            merchant_did="did:ap2:merchant:nike",
            name="Nike Store",
            agent_endpoint="https://nike.example.com",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nnike_key\n-----END PUBLIC KEY-----"
        )

        await registry.register_merchant(
            merchant_did="did:ap2:merchant:adidas",
            name="Adidas Store",
            agent_endpoint="https://adidas.example.com",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nadidas_key\n-----END PUBLIC KEY-----"
        )

        # Search for Nike
        results = await registry.search_merchants(query="Nike")

        assert len(results) >= 1
        assert any(r["name"] == "Nike Store" for r in results)

    @pytest.mark.asyncio
    async def test_search_merchants_by_trust_score(self, temp_db_path):
        """Test searching merchants by minimum trust score"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        # Register merchant with default trust score (50.0)
        await registry.register_merchant(
            merchant_did="did:ap2:merchant:trusted",
            name="Trusted Store",
            agent_endpoint="https://trusted.example.com",
            public_key_pem="-----BEGIN PUBLIC KEY-----\ntrusted_key\n-----END PUBLIC KEY-----"
        )

        # Search with lower threshold
        results = await registry.search_merchants(min_trust_score=40.0)
        assert len(results) >= 1

        # Search with higher threshold
        results = await registry.search_merchants(min_trust_score=60.0)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_merchants_all(self, temp_db_path):
        """Test searching all merchants"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        # Register merchants
        await registry.register_merchant(
            merchant_did="did:ap2:merchant:store1",
            name="Store 1",
            agent_endpoint="https://store1.example.com",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nstore1_key\n-----END PUBLIC KEY-----"
        )

        await registry.register_merchant(
            merchant_did="did:ap2:merchant:store2",
            name="Store 2",
            agent_endpoint="https://store2.example.com",
            public_key_pem="-----BEGIN PUBLIC KEY-----\nstore2_key\n-----END PUBLIC KEY-----"
        )

        # Search without filters
        results = await registry.search_merchants()

        assert len(results) >= 2


class TestDIDDocumentConversion:
    """Test DID document conversion"""

    @pytest.mark.asyncio
    async def test_record_to_did_document(self, temp_db_path):
        """Test converting database record to DID document"""
        db_url = f"sqlite+aiosqlite:///{temp_db_path}"
        registry = MerchantRegistry(database_url=db_url)
        await registry.init_db()

        # Register a merchant
        merchant_did = "did:ap2:merchant:conversion_test"
        public_key_pem = "-----BEGIN PUBLIC KEY-----\nconversion_key\n-----END PUBLIC KEY-----"

        did_doc = await registry.register_merchant(
            merchant_did=merchant_did,
            name="Conversion Test Store",
            agent_endpoint="https://conversion.example.com",
            public_key_pem=public_key_pem
        )

        # Verify DID document structure
        assert did_doc.id == merchant_did
        assert len(did_doc.verificationMethod) == 1
        assert did_doc.verificationMethod[0].id == f"{merchant_did}#key-1"
        assert did_doc.verificationMethod[0].type == "Ed25519VerificationKey2020"
        assert did_doc.verificationMethod[0].controller == merchant_did
        assert did_doc.verificationMethod[0].publicKeyPem == public_key_pem

        assert len(did_doc.service) == 1
        assert did_doc.service[0].id == f"{merchant_did}#merchant-agent"
        assert did_doc.service[0].type == "AP2MerchantAgent"
        assert did_doc.service[0].serviceEndpoint == "https://conversion.example.com"

        assert len(did_doc.authentication) == 1
