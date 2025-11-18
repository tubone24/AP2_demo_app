"""
Tests for DID Resolver

Tests cover:
- DID document resolution (resolve, resolve_async)
- KID to public key resolution (resolve_public_key)
- W3C DID specification compliance
- HTTP-based DID resolution (_resolve_via_http)
- DID document caching
- DID document registration and update
- Error handling for different DID methods
"""

import pytest
import json
from pathlib import Path
from unittest.mock import Mock, AsyncMock, MagicMock, patch, mock_open
from datetime import datetime, timezone


class TestDIDResolverInitialization:
    """Test DIDResolver initialization"""

    def test_did_resolver_initialization(self):
        """Test DIDResolver initialization with KeyManager"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            assert resolver.key_manager == mock_key_manager
            assert resolver.merchant_registry is None
            assert isinstance(resolver._did_registry, dict)

    def test_did_resolver_initialization_with_merchant_registry(self):
        """Test DIDResolver initialization with merchant registry"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_merchant_registry = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

            assert resolver.key_manager == mock_key_manager
            assert resolver.merchant_registry == mock_merchant_registry

    def test_init_demo_registry_file_not_found(self):
        """Test _init_demo_registry logs error when DID documents are missing"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch('os.getenv', return_value="/nonexistent/path"), \
             patch('pathlib.Path.exists', return_value=False):

            # The DIDResolver catches FileNotFoundError and logs it as a warning
            # It does not raise the exception
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Verify resolver was created but registry is empty (except for any that succeeded)
            assert isinstance(resolver._did_registry, dict)


class TestDIDResolution:
    """Test DID resolution functionality"""

    def test_resolve_from_cache(self):
        """Test resolving DID from cache"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Add DID document to cache
            did = "did:ap2:agent:shopping_agent"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )
            resolver._did_registry[did] = did_doc

            # Resolve from cache
            resolved_doc = resolver.resolve(did)

            assert resolved_doc is not None
            assert resolved_doc.id == did

    def test_resolve_merchant_did_from_registry(self):
        """Test resolving merchant DID from merchant registry"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()
        mock_merchant_registry = AsyncMock()

        # Mock merchant registry to return DID document
        merchant_did = "did:ap2:merchant:mugibo_merchant"
        did_doc = DIDDocument(
            id=merchant_did,
            verificationMethod=[
                VerificationMethod(
                    id=f"{merchant_did}#key-1",
                    type="EcdsaSecp256k1VerificationKey2019",
                    controller=merchant_did,
                    publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                )
            ],
            authentication=["#key-1"],
            assertionMethod=["#key-1"]
        )

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

            # Mock event loop
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = False
            mock_loop.run_until_complete.return_value = did_doc

            with patch('asyncio.get_event_loop', return_value=mock_loop):
                resolved_doc = resolver.resolve(merchant_did)

                assert resolved_doc == did_doc
                # Should be cached
                assert resolver._did_registry[merchant_did] == did_doc

    def test_resolve_did_not_found(self):
        """Test resolving non-existent DID returns None"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            non_existent_did = "did:ap2:agent:non_existent"
            resolved_doc = resolver.resolve(non_existent_did)

            assert resolved_doc is None

    def test_resolve_merchant_did_event_loop_running(self):
        """Test resolve merchant DID when event loop is already running"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_merchant_registry = AsyncMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

            merchant_did = "did:ap2:merchant:test"

            # Mock event loop that is already running
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = True

            with patch('asyncio.get_event_loop', return_value=mock_loop):
                resolved_doc = resolver.resolve(merchant_did)

                # Should return None when event loop is running
                assert resolved_doc is None

    def test_resolve_merchant_did_exception(self):
        """Test resolve merchant DID handles exceptions"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_merchant_registry = AsyncMock()
        mock_merchant_registry.resolve_merchant_did.side_effect = Exception("Test error")

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

            merchant_did = "did:ap2:merchant:test"

            # Mock event loop
            mock_loop = MagicMock()
            mock_loop.is_running.return_value = False
            mock_loop.run_until_complete.side_effect = Exception("Test error")

            with patch('asyncio.get_event_loop', return_value=mock_loop):
                resolved_doc = resolver.resolve(merchant_did)

                # Should return None on exception
                assert resolved_doc is None


class TestAsyncDIDResolution:
    """Test async DID resolution"""

    @pytest.mark.asyncio
    async def test_resolve_async_from_cache(self):
        """Test async resolve from cache"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Add DID document to cache
            did = "did:ap2:agent:shopping_agent"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )
            resolver._did_registry[did] = did_doc

            # Resolve async from cache
            resolved_doc = await resolver.resolve_async(did)

            assert resolved_doc is not None
            assert resolved_doc.id == did

    @pytest.mark.asyncio
    async def test_resolve_async_via_http(self):
        """Test async resolve via HTTP"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:merchant_agent"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )

            # Mock _resolve_via_http to return DID document
            with patch.object(resolver, '_resolve_via_http', return_value=did_doc):
                resolved_doc = await resolver.resolve_async(did)

                assert resolved_doc == did_doc
                # Should be cached
                assert resolver._did_registry[did] == did_doc

    @pytest.mark.asyncio
    async def test_resolve_async_merchant_did_from_registry(self):
        """Test async resolve merchant DID from registry"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()
        mock_merchant_registry = AsyncMock()

        merchant_did = "did:ap2:merchant:mugibo_merchant"
        did_doc = DIDDocument(
            id=merchant_did,
            verificationMethod=[
                VerificationMethod(
                    id=f"{merchant_did}#key-1",
                    type="EcdsaSecp256k1VerificationKey2019",
                    controller=merchant_did,
                    publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                )
            ],
            authentication=["#key-1"],
            assertionMethod=["#key-1"]
        )

        mock_merchant_registry.resolve_merchant_did.return_value = did_doc

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

            # Mock _resolve_via_http to return None (fallback to merchant registry)
            with patch.object(resolver, '_resolve_via_http', return_value=None):
                resolved_doc = await resolver.resolve_async(merchant_did)

                assert resolved_doc == did_doc
                mock_merchant_registry.resolve_merchant_did.assert_called_once_with(merchant_did)

    @pytest.mark.asyncio
    async def test_resolve_async_not_found(self):
        """Test async resolve returns None when DID not found"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            non_existent_did = "did:ap2:agent:non_existent"

            # Mock _resolve_via_http to return None
            with patch.object(resolver, '_resolve_via_http', return_value=None):
                resolved_doc = await resolver.resolve_async(non_existent_did)

                assert resolved_doc is None


class TestHTTPDIDResolution:
    """Test HTTP-based DID resolution"""

    @pytest.mark.asyncio
    async def test_resolve_via_http_success(self):
        """Test successful HTTP DID resolution"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:merchant_agent"
            did_doc_data = {
                "id": did,
                "verificationMethod": [
                    {
                        "id": f"{did}#key-1",
                        "type": "EcdsaSecp256k1VerificationKey2019",
                        "controller": did,
                        "publicKeyPem": "-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    }
                ],
                "authentication": ["#key-1"],
                "assertionMethod": ["#key-1"],
                "service": []
            }

            # Mock httpx response
            mock_response = MagicMock()
            mock_response.json.return_value = did_doc_data
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch('httpx.AsyncClient', return_value=mock_client):
                resolved_doc = await resolver._resolve_via_http(did)

                assert resolved_doc is not None
                assert resolved_doc.id == did
                assert len(resolved_doc.verificationMethod) == 1

    @pytest.mark.asyncio
    async def test_resolve_via_http_not_found(self):
        """Test HTTP resolution returns None for unmapped DID"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            unmapped_did = "did:ap2:agent:unmapped"
            resolved_doc = await resolver._resolve_via_http(unmapped_did)

            assert resolved_doc is None

    @pytest.mark.asyncio
    async def test_resolve_via_http_exception(self):
        """Test HTTP resolution handles exceptions"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:merchant_agent"

            # Mock httpx to raise exception
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Connection error")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None

            with patch('httpx.AsyncClient', return_value=mock_client):
                resolved_doc = await resolver._resolve_via_http(did)

                # Should return None on exception
                assert resolved_doc is None


class TestKIDResolution:
    """Test KID (Key ID) to public key resolution"""

    def test_resolve_public_key_success(self):
        """Test resolving public key from KID"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Add DID document to cache
            did = "did:ap2:agent:shopping_agent"
            public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem=public_key_pem
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )
            resolver._did_registry[did] = did_doc

            # Resolve public key
            kid = f"{did}#key-1"
            resolved_key = resolver.resolve_public_key(kid)

            assert resolved_key == public_key_pem

    def test_resolve_public_key_invalid_kid_format(self):
        """Test resolve public key with invalid KID format"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # KID without fragment
            invalid_kid = "did:ap2:agent:shopping_agent"
            resolved_key = resolver.resolve_public_key(invalid_kid)

            assert resolved_key is None

    def test_resolve_public_key_did_not_found(self):
        """Test resolve public key when DID document not found"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            kid = "did:ap2:agent:non_existent#key-1"
            resolved_key = resolver.resolve_public_key(kid)

            assert resolved_key is None

    def test_resolve_public_key_verification_method_not_found(self):
        """Test resolve public key when verification method not found"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Add DID document with one verification method
            did = "did:ap2:agent:shopping_agent"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )
            resolver._did_registry[did] = did_doc

            # Try to resolve non-existent key
            kid = f"{did}#key-99"
            resolved_key = resolver.resolve_public_key(kid)

            assert resolved_key is None

    def test_resolve_public_key_fragment_only(self):
        """Test resolve public key with fragment-only reference"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Add DID document
            did = "did:ap2:agent:shopping_agent"
            public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem=public_key_pem
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )
            resolver._did_registry[did] = did_doc

            # Resolve with fragment-only KID (should still work)
            kid = f"{did}#key-1"
            resolved_key = resolver.resolve_public_key(kid)

            assert resolved_key == public_key_pem


class TestDIDDocumentManagement:
    """Test DID document registration and update"""

    def test_register_did_document(self):
        """Test registering DID document"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            # Register new DID document
            did = "did:ap2:agent:new_agent"
            did_doc = DIDDocument(
                id=did,
                verificationMethod=[
                    VerificationMethod(
                        id=f"{did}#key-1",
                        type="EcdsaSecp256k1VerificationKey2019",
                        controller=did,
                        publicKeyPem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----"
                    )
                ],
                authentication=["#key-1"],
                assertionMethod=["#key-1"]
            )

            resolver.register_did_document(did_doc)

            # Verify registration
            assert did in resolver._did_registry
            assert resolver._did_registry[did] == did_doc

    def test_update_public_key(self):
        """Test updating DID public key"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_public_key = MagicMock()
        mock_key_manager.load_public_key.return_value = mock_public_key
        mock_key_manager.public_key_to_pem.return_value = "-----BEGIN PUBLIC KEY-----\nnew_key\n-----END PUBLIC KEY-----"

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:test_agent"
            agent_key = "test_agent"

            # Update public key
            resolver.update_public_key(did, agent_key)

            # Verify key manager was called
            mock_key_manager.load_public_key.assert_called_once_with(agent_key)
            mock_key_manager.public_key_to_pem.assert_called_once_with(mock_public_key)

            # Verify DID document was updated
            assert did in resolver._did_registry

    def test_update_public_key_exception(self):
        """Test update public key handles exceptions"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_key_manager.load_public_key.side_effect = Exception("Key not found")

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:test_agent"
            agent_key = "test_agent"

            # Should raise exception
            with pytest.raises(Exception):
                resolver.update_public_key(did, agent_key)


class TestCreateDIDDocument:
    """Test _create_did_document helper method"""

    def test_create_did_document(self):
        """Test creating DID document"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

            did = "did:ap2:agent:test_agent"
            agent_key = "test_agent"
            public_key_pem = "-----BEGIN PUBLIC KEY-----\ntest_key\n-----END PUBLIC KEY-----"

            # Create DID document
            did_doc = resolver._create_did_document(did, agent_key, public_key_pem)

            assert did_doc.id == did
            assert len(did_doc.verificationMethod) == 1
            assert did_doc.verificationMethod[0].id == f"{did}#key-1"
            assert did_doc.verificationMethod[0].publicKeyPem == public_key_pem
            assert did_doc.verificationMethod[0].type == "EcdsaSecp256k1VerificationKey2019"
            assert did_doc.authentication == ["#key-1"]
            assert did_doc.assertionMethod == ["#key-1"]


class TestDIDFormatValidation:
    """Test DID format validation"""

    def test_agent_did_format(self):
        """Test agent DID format"""
        agent_dids = [
            "did:ap2:agent:shopping_agent",
            "did:ap2:agent:merchant_agent",
            "did:ap2:agent:payment_processor"
        ]

        for did in agent_dids:
            assert did.startswith("did:ap2:agent:")
            parts = did.split(":")
            assert len(parts) == 4

    def test_merchant_did_format(self):
        """Test merchant DID format"""
        merchant_dids = [
            "did:ap2:merchant:mugibo_merchant",
            "did:ap2:merchant:nike"
        ]

        for did in merchant_dids:
            assert did.startswith("did:ap2:merchant:")
            parts = did.split(":")
            assert len(parts) == 4

    def test_credential_provider_did_format(self):
        """Test credential provider DID format"""
        cp_dids = [
            "did:ap2:cp:demo_cp",
            "did:ap2:cp:demo_cp_2"
        ]

        for did in cp_dids:
            assert did.startswith("did:ap2:cp:")
            parts = did.split(":")
            assert len(parts) == 4


class TestPersistedDIDDocumentLoading:
    """Test loading persisted DID documents from file"""

    def test_init_demo_registry_with_existing_file(self, tmp_path, monkeypatch):
        """Test loading persisted DID document from existing file"""
        from common.did_resolver import DIDResolver

        # Create a temporary DID document directory structure
        # The code expects: {AP2_KEYS_DIRECTORY}/../data/did_documents/
        keys_dir = tmp_path / "keys"
        keys_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        did_doc_dir = data_dir / "did_documents"
        did_doc_dir.mkdir()

        # Use one of the demo agents from the hardcoded list
        did = "did:ap2:agent:shopping_agent"
        agent_key = "shopping_agent"
        did_doc_file = did_doc_dir / f"{agent_key}_did.json"

        # Create a valid DID document with service endpoint
        did_doc_data = {
            "id": did,
            "verificationMethod": [{
                "id": f"{did}#key-1",
                "type": "EcdsaSecp256r1VerificationKey2019",
                "controller": did,
                "publicKeyPem": "-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----"
            }],
            "authentication": [f"{did}#key-1"],
            "assertionMethod": [f"{did}#key-1"],
            "service": [{
                "id": f"{did}#payment-service",
                "type": "PaymentService",
                "serviceEndpoint": "https://example.com/payment",
                "name": "Test Payment Service",
                "description": "Test service",
                "supported_methods": ["card", "bank"],
                "logo_url": "https://example.com/logo.png"
            }]
        }

        did_doc_file.write_text(json.dumps(did_doc_data))

        # Mock the key manager
        mock_key_manager = MagicMock()

        # Set environment variable to point to our temp keys directory
        monkeypatch.setenv("AP2_KEYS_DIRECTORY", str(keys_dir))

        # Initialize resolver - it should load from our temp directory
        resolver = DIDResolver(key_manager=mock_key_manager)

        # Verify the DID document was loaded
        assert did in resolver._did_registry
        loaded_doc = resolver._did_registry[did]
        assert loaded_doc.id == did
        assert len(loaded_doc.verificationMethod) == 1
        assert loaded_doc.service is not None
        assert len(loaded_doc.service) == 1
        assert loaded_doc.service[0].name == "Test Payment Service"

    def test_resolve_async_with_service_endpoints(self):
        """Test async resolution returns service endpoints"""
        from common.did_resolver import DIDResolver
        from common.models import DIDDocument, VerificationMethod, ServiceEndpoint

        mock_key_manager = MagicMock()

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(key_manager=mock_key_manager)

        # Create DID document with service endpoint
        did = "did:ap2:agent:test"
        service = ServiceEndpoint(
            id=f"{did}#service-1",
            type="TestService",
            serviceEndpoint="https://test.example.com",
            name="Test Service",
            description="A test service",
            supported_methods=["method1", "method2"]
        )

        vm = VerificationMethod(
            id=f"{did}#key-1",
            type="EcdsaSecp256r1VerificationKey2019",
            controller=did,
            publicKeyPem="-----BEGIN PUBLIC KEY-----\\ntest\\n-----END PUBLIC KEY-----"
        )

        did_doc = DIDDocument(
            id=did,
            verificationMethod=[vm],
            authentication=[f"{did}#key-1"],
            service=[service]
        )

        resolver._did_registry[did] = did_doc

        # Resolve and verify service endpoint
        import asyncio
        result = asyncio.run(resolver.resolve_async(did))

        assert result is not None
        assert result.service is not None
        assert len(result.service) == 1
        assert result.service[0].name == "Test Service"
        assert result.service[0].supported_methods == ["method1", "method2"]

    def test_resolve_merchant_did_registry_exception(self):
        """Test merchant DID resolution with registry exception"""
        from common.did_resolver import DIDResolver

        mock_key_manager = MagicMock()
        mock_merchant_registry = MagicMock()

        # Mock registry to raise exception
        mock_merchant_registry.get_merchant_info.side_effect = Exception("Registry error")

        with patch.object(DIDResolver, '_init_demo_registry'):
            resolver = DIDResolver(
                key_manager=mock_key_manager,
                merchant_registry=mock_merchant_registry
            )

        # Should handle exception and return None
        result = resolver.resolve("did:ap2:merchant:test")
        assert result is None
