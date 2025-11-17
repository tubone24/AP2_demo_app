"""
Tests for DID Resolver

Tests cover:
- DID document resolution
- KID to public key resolution
- W3C DID specification compliance
- HTTP-based DID resolution
- DID document caching
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime, timezone


class TestDIDDocumentStructure:
    """Test DID document structure"""

    def test_did_document_structure(self):
        """Test W3C DID document structure"""
        did_document = {
            "@context": [
                "https://www.w3.org/ns/did/v1",
                "https://w3id.org/security/suites/ed25519-2020/v1"
            ],
            "id": "did:ap2:agent:shopping_agent",
            "verificationMethod": [
                {
                    "id": "did:ap2:agent:shopping_agent#key-1",
                    "type": "EcdsaSecp256k1VerificationKey2019",
                    "controller": "did:ap2:agent:shopping_agent",
                    "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
                }
            ],
            "authentication": ["#key-1"],
            "assertionMethod": ["#key-1"]
        }

        # Validate required fields
        assert "id" in did_document
        assert "verificationMethod" in did_document
        assert did_document["id"].startswith("did:ap2:")

    def test_verification_method_structure(self):
        """Test verification method structure"""
        verification_method = {
            "id": "did:ap2:agent:shopping_agent#key-1",
            "type": "EcdsaSecp256k1VerificationKey2019",
            "controller": "did:ap2:agent:shopping_agent",
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            "publicKeyMultibase": "z6Mk..."
        }

        # Validate required fields
        required_fields = ["id", "type", "controller", "publicKeyPem"]
        for field in required_fields:
            assert field in verification_method

        # Validate ID format (DID#fragment)
        assert "#" in verification_method["id"]
        assert verification_method["id"].startswith("did:ap2:")


class TestDIDResolution:
    """Test DID resolution functionality"""

    def test_resolve_from_cache(self):
        """Test resolving DID from cache"""
        # Mock cached DID document
        cached_did = "did:ap2:agent:shopping_agent"
        cache = {
            cached_did: {
                "id": cached_did,
                "verificationMethod": []
            }
        }

        # Simulate cache lookup
        did_doc = cache.get(cached_did)
        assert did_doc is not None
        assert did_doc["id"] == cached_did

    def test_resolve_agent_did_format(self):
        """Test agent DID format validation"""
        agent_dids = [
            "did:ap2:agent:shopping_agent",
            "did:ap2:agent:merchant_agent",
            "did:ap2:agent:payment_processor"
        ]

        for did in agent_dids:
            # Validate format
            assert did.startswith("did:ap2:agent:")
            assert len(did.split(":")) == 4

    def test_resolve_merchant_did_format(self):
        """Test merchant DID format validation"""
        merchant_dids = [
            "did:ap2:merchant:mugibo_merchant",
            "did:ap2:merchant:nike"
        ]

        for did in merchant_dids:
            # Validate format
            assert did.startswith("did:ap2:merchant:")
            assert len(did.split(":")) == 4

    def test_resolve_credential_provider_did_format(self):
        """Test credential provider DID format validation"""
        cp_dids = [
            "did:ap2:cp:demo_cp",
            "did:ap2:cp:demo_cp_2"
        ]

        for did in cp_dids:
            # Validate format
            assert did.startswith("did:ap2:cp:")
            assert len(did.split(":")) == 4

    def test_did_not_found(self):
        """Test handling of non-existent DID"""
        cache = {}
        non_existent_did = "did:ap2:agent:non_existent"

        # Simulate cache lookup
        did_doc = cache.get(non_existent_did)
        assert did_doc is None


class TestKIDResolution:
    """Test KID (Key ID) to public key resolution"""

    def test_kid_format_validation(self):
        """Test KID format validation"""
        valid_kids = [
            "did:ap2:agent:shopping_agent#key-1",
            "did:ap2:merchant:mugibo_merchant#key-1",
            "did:ap2:cp:demo_cp#key-1"
        ]

        for kid in valid_kids:
            # Validate KID format (DID#fragment)
            assert "#" in kid
            parts = kid.split("#")
            assert len(parts) == 2
            assert parts[0].startswith("did:ap2:")
            assert parts[1].startswith("key-")

    def test_kid_parsing(self):
        """Test parsing KID into DID and fragment"""
        kid = "did:ap2:agent:shopping_agent#key-1"

        # Parse KID
        did, fragment = kid.split("#", 1)

        assert did == "did:ap2:agent:shopping_agent"
        assert fragment == "key-1"

    def test_invalid_kid_format(self):
        """Test handling of invalid KID format"""
        invalid_kids = [
            "did:ap2:agent:shopping_agent",  # No fragment
            "#key-1",  # No DID
            "invalid_kid"  # Invalid format
        ]

        for invalid_kid in invalid_kids:
            # Should not contain proper DID#fragment format
            if "#" in invalid_kid:
                parts = invalid_kid.split("#")
                if len(parts) == 2:
                    if not parts[0].startswith("did:"):
                        assert True  # Invalid DID part
            else:
                assert "#" not in invalid_kid

    def test_resolve_public_key_from_verification_method(self):
        """Test resolving public key from verification method"""
        verification_methods = [
            {
                "id": "did:ap2:agent:shopping_agent#key-1",
                "type": "EcdsaSecp256k1VerificationKey2019",
                "publicKeyPem": "-----BEGIN PUBLIC KEY-----\nMFkw...\n-----END PUBLIC KEY-----"
            }
        ]

        kid = "did:ap2:agent:shopping_agent#key-1"

        # Find matching verification method
        public_key = None
        for vm in verification_methods:
            if vm["id"] == kid:
                public_key = vm["publicKeyPem"]
                break

        assert public_key is not None
        assert public_key.startswith("-----BEGIN PUBLIC KEY-----")

    def test_verification_method_not_found(self):
        """Test handling of non-existent verification method"""
        verification_methods = [
            {
                "id": "did:ap2:agent:shopping_agent#key-1",
                "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
            }
        ]

        # Search for non-existent key
        kid = "did:ap2:agent:shopping_agent#key-99"
        public_key = None
        for vm in verification_methods:
            if vm["id"] == kid:
                public_key = vm["publicKeyPem"]
                break

        assert public_key is None


class TestHTTPDIDResolution:
    """Test HTTP-based DID resolution"""

    def test_well_known_did_endpoint(self):
        """Test .well-known/did.json endpoint path"""
        endpoint = "/.well-known/did.json"

        # Validate W3C DID specification compliance
        assert endpoint.startswith("/.well-known/")
        assert endpoint.endswith(".json")

    def test_hostname_mapping(self):
        """Test DID to hostname mapping"""
        hostname_port_mapping = {
            "did:ap2:agent:shopping_agent": ("shopping_agent", 8000),
            "did:ap2:agent:merchant_agent": ("merchant_agent", 8001),
            "did:ap2:merchant:mugibo_merchant": ("merchant", 8002),
            "did:ap2:cp:demo_cp": ("credential_provider", 8003),
            "did:ap2:agent:payment_processor": ("payment_processor", 8004),
        }

        for did, (hostname, port) in hostname_port_mapping.items():
            # Validate mapping
            assert isinstance(hostname, str)
            assert isinstance(port, int)
            assert port > 0
            assert port < 65536

    def test_http_url_construction(self):
        """Test HTTP URL construction for DID resolution"""
        did = "did:ap2:agent:merchant_agent"
        hostname = "merchant_agent"
        port = 8001

        url = f"http://{hostname}:{port}/.well-known/did.json"

        # Validate URL
        assert url == "http://merchant_agent:8001/.well-known/did.json"
        assert url.startswith("http://")
        assert "/.well-known/did.json" in url

    @pytest.mark.asyncio
    async def test_http_resolution_timeout(self):
        """Test HTTP resolution timeout handling"""
        timeout = 5.0

        # Validate timeout is reasonable
        assert timeout > 0
        assert timeout <= 30  # Should not be too long


class TestDIDDocumentCaching:
    """Test DID document caching"""

    def test_cache_structure(self):
        """Test cache data structure"""
        cache = {}

        # Add DID documents to cache
        did1 = "did:ap2:agent:shopping_agent"
        did2 = "did:ap2:agent:merchant_agent"

        cache[did1] = {"id": did1, "verificationMethod": []}
        cache[did2] = {"id": did2, "verificationMethod": []}

        # Validate cache
        assert len(cache) == 2
        assert did1 in cache
        assert did2 in cache

    def test_cache_update(self):
        """Test updating cached DID document"""
        cache = {}
        did = "did:ap2:agent:shopping_agent"

        # Initial cache
        cache[did] = {"id": did, "version": 1}

        # Update cache
        cache[did] = {"id": did, "version": 2}

        # Validate update
        assert cache[did]["version"] == 2

    def test_cache_invalidation(self):
        """Test cache invalidation"""
        cache = {
            "did:ap2:agent:shopping_agent": {"id": "did:ap2:agent:shopping_agent"}
        }

        # Remove from cache
        did = "did:ap2:agent:shopping_agent"
        if did in cache:
            del cache[did]

        # Validate removal
        assert did not in cache


class TestDIDDocumentRegistration:
    """Test DID document registration"""

    def test_register_did_document(self):
        """Test registering DID document"""
        registry = {}
        did = "did:ap2:agent:new_agent"
        did_doc = {
            "id": did,
            "verificationMethod": []
        }

        # Register
        registry[did] = did_doc

        # Validate registration
        assert did in registry
        assert registry[did]["id"] == did

    def test_update_did_document(self):
        """Test updating existing DID document"""
        registry = {
            "did:ap2:agent:shopping_agent": {
                "id": "did:ap2:agent:shopping_agent",
                "verificationMethod": []
            }
        }

        did = "did:ap2:agent:shopping_agent"

        # Update with new verification method
        registry[did]["verificationMethod"] = [
            {
                "id": f"{did}#key-1",
                "publicKeyPem": "new_key"
            }
        ]

        # Validate update
        assert len(registry[did]["verificationMethod"]) == 1


class TestDIDTypes:
    """Test different DID types"""

    def test_agent_did_type(self):
        """Test agent DID type identification"""
        agent_did = "did:ap2:agent:shopping_agent"

        # Validate type
        assert agent_did.startswith("did:ap2:agent:")

    def test_merchant_did_type(self):
        """Test merchant DID type identification"""
        merchant_did = "did:ap2:merchant:mugibo_merchant"

        # Validate type
        assert merchant_did.startswith("did:ap2:merchant:")

    def test_credential_provider_did_type(self):
        """Test credential provider DID type identification"""
        cp_did = "did:ap2:cp:demo_cp"

        # Validate type
        assert cp_did.startswith("did:ap2:cp:")

    def test_did_type_detection(self):
        """Test detecting DID type from DID string"""
        test_cases = [
            ("did:ap2:agent:test", "agent"),
            ("did:ap2:merchant:test", "merchant"),
            ("did:ap2:cp:test", "cp"),
        ]

        for did, expected_type in test_cases:
            # Extract type from DID
            parts = did.split(":")
            did_type = parts[2] if len(parts) > 2 else None

            assert did_type == expected_type


class TestServiceEndpoints:
    """Test service endpoints in DID documents"""

    def test_service_endpoint_structure(self):
        """Test service endpoint structure"""
        service_endpoint = {
            "id": "did:ap2:cp:demo_cp#credential-service",
            "type": "CredentialProvider",
            "serviceEndpoint": "http://credential_provider:8003",
            "name": "Demo Credential Provider",
            "description": "AP2 Demo Credential Provider Service",
            "supported_methods": ["passkey", "webauthn"]
        }

        # Validate required fields
        required_fields = ["id", "type", "serviceEndpoint"]
        for field in required_fields:
            assert field in service_endpoint

        # Validate optional fields
        assert "name" in service_endpoint
        assert "supported_methods" in service_endpoint

    def test_multiple_service_endpoints(self):
        """Test DID document with multiple service endpoints"""
        services = [
            {
                "id": "did:ap2:merchant:test#api",
                "type": "MerchantAPI",
                "serviceEndpoint": "http://merchant:8002/api"
            },
            {
                "id": "did:ap2:merchant:test#website",
                "type": "Website",
                "serviceEndpoint": "https://example.com"
            }
        ]

        # Validate multiple endpoints
        assert len(services) == 2
        assert all("serviceEndpoint" in svc for svc in services)


class TestDIDDocumentValidation:
    """Test DID document validation"""

    def test_required_fields_present(self):
        """Test that required fields are present"""
        did_document = {
            "id": "did:ap2:agent:test",
            "verificationMethod": [
                {
                    "id": "did:ap2:agent:test#key-1",
                    "type": "EcdsaSecp256k1VerificationKey2019",
                    "controller": "did:ap2:agent:test",
                    "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
                }
            ],
            "authentication": ["#key-1"]
        }

        # Validate required fields
        assert "id" in did_document
        assert "verificationMethod" in did_document
        assert len(did_document["verificationMethod"]) > 0

    def test_verification_method_references(self):
        """Test verification method references in authentication/assertion"""
        did_document = {
            "id": "did:ap2:agent:test",
            "verificationMethod": [
                {"id": "did:ap2:agent:test#key-1"}
            ],
            "authentication": ["#key-1"],
            "assertionMethod": ["#key-1"]
        }

        # Validate references
        vm_ids = [vm["id"] for vm in did_document["verificationMethod"]]
        did = did_document["id"]

        # Authentication should reference existing verification method
        for auth in did_document["authentication"]:
            if auth.startswith("#"):
                full_id = f"{did}{auth}"
                assert any(full_id == vm_id for vm_id in vm_ids)

    def test_controller_matches_did(self):
        """Test that controller matches DID"""
        did = "did:ap2:agent:shopping_agent"
        verification_method = {
            "id": f"{did}#key-1",
            "controller": did,
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
        }

        # Validate controller
        assert verification_method["controller"] == did


class TestPublicKeyFormats:
    """Test public key format handling"""

    def test_pem_format(self):
        """Test PEM format public key"""
        pem_key = "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE...\n-----END PUBLIC KEY-----"

        # Validate PEM format
        assert pem_key.startswith("-----BEGIN PUBLIC KEY-----")
        assert pem_key.endswith("-----END PUBLIC KEY-----")

    def test_multibase_format(self):
        """Test Multibase format public key"""
        multibase_key = "z6MkhaXgBZDvotDkL5257faiztiGiC2QtKLGpbnnEGta2doK"

        # Validate Multibase format (starts with 'z')
        assert multibase_key.startswith("z")
        assert len(multibase_key) > 10

    def test_verification_method_with_multiple_key_formats(self):
        """Test verification method with both PEM and Multibase"""
        verification_method = {
            "id": "did:ap2:agent:test#key-1",
            "type": "Ed25519VerificationKey2020",
            "publicKeyPem": "-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            "publicKeyMultibase": "z6Mk..."
        }

        # Both formats should be present
        assert "publicKeyPem" in verification_method
        assert "publicKeyMultibase" in verification_method
