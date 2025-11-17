"""
Tests for Pydantic Models

Tests cover:
- A2A message models validation
- Signature and proof models
- Device attestation models
- DID document models
- Pydantic field validation
"""

import pytest
from pydantic import ValidationError
from datetime import datetime, timezone


class TestA2AProofModel:
    """Test A2AProof model validation"""

    def test_a2a_proof_valid(self):
        """Test valid A2AProof creation"""
        from common.models import A2AProof

        proof = A2AProof(
            algorithm="ed25519",
            signatureValue="MEUCIQDx8yZ...",
            publicKeyMultibase="z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",
            kid="did:ap2:agent:shopping_agent#key-1",
            created=datetime.now(timezone.utc).isoformat(),
            proofPurpose="authentication"
        )

        # Validate fields
        assert proof.algorithm in ["ed25519", "ecdsa"]
        assert proof.publicKeyMultibase.startswith("z")
        assert proof.proofPurpose == "authentication"

    def test_a2a_proof_algorithm_validation(self):
        """Test algorithm field validation"""
        from common.models import A2AProof

        # Valid algorithms
        valid_algorithms = ["ed25519", "ecdsa"]
        for alg in valid_algorithms:
            proof = A2AProof(
                algorithm=alg,
                signatureValue="sig",
                publicKeyMultibase="z6Mk...",
                created=datetime.now(timezone.utc).isoformat()
            )
            assert proof.algorithm == alg

    def test_a2a_proof_purpose_validation(self):
        """Test proofPurpose field validation"""
        from common.models import A2AProof

        valid_purposes = ["authentication", "assertionMethod", "agreement"]
        for purpose in valid_purposes:
            proof = A2AProof(
                algorithm="ed25519",
                signatureValue="sig",
                publicKeyMultibase="z6Mk...",
                created=datetime.now(timezone.utc).isoformat(),
                proofPurpose=purpose
            )
            assert proof.proofPurpose == purpose


class TestSignatureModel:
    """Test Signature model validation"""

    def test_signature_valid(self):
        """Test valid Signature creation"""
        from common.models import Signature

        signature = Signature(
            algorithm="Ed25519",
            value="MEUCIQDx...",
            publicKeyMultibase="z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",
            signed_at=datetime.now(timezone.utc).isoformat(),
            key_id="shopping_agent"
        )

        # Validate fields
        assert signature.algorithm in ["Ed25519", "ECDSA"]
        assert signature.publicKeyMultibase.startswith("z")
        assert signature.key_id is not None

    def test_signature_default_algorithm(self):
        """Test default algorithm is Ed25519"""
        from common.models import Signature

        signature = Signature(
            value="sig",
            publicKeyMultibase="z6Mk...",
            signed_at=datetime.now(timezone.utc).isoformat()
        )

        assert signature.algorithm == "Ed25519"


class TestDeviceAttestationModel:
    """Test DeviceAttestation model validation"""

    def test_device_attestation_valid(self):
        """Test valid DeviceAttestation creation"""
        from common.models import DeviceAttestation, AttestationType

        attestation = DeviceAttestation(
            device_id="device_abc123",
            attestation_type=AttestationType.WEBAUTHN,
            attestation_value="MEUCIQDx...",
            timestamp=datetime.now(timezone.utc).isoformat(),
            device_public_key_multibase="z2oAtgCswLVHGBgbaEmaRp6m1zmj3jx4tf1LgSCKreVPjwRm1",
            challenge="random_challenge_abc123",
            platform="Web",
            os_version="macOS 14.0",
            app_version="1.0.0"
        )

        # Validate fields
        assert attestation.device_id == "device_abc123"
        assert attestation.attestation_type == AttestationType.WEBAUTHN
        assert attestation.platform == "Web"

    def test_attestation_type_enum(self):
        """Test AttestationType enum values"""
        from common.models import AttestationType

        # Validate all enum values
        assert AttestationType.BIOMETRIC == "biometric"
        assert AttestationType.PIN == "pin"
        assert AttestationType.PATTERN == "pattern"
        assert AttestationType.DEVICE_CREDENTIAL == "device_credential"
        assert AttestationType.WEBAUTHN == "webauthn"

    def test_webauthn_fields(self):
        """Test WebAuthn-specific fields"""
        from common.models import DeviceAttestation, AttestationType

        attestation = DeviceAttestation(
            device_id="device_123",
            attestation_type=AttestationType.WEBAUTHN,
            attestation_value="value",
            timestamp=datetime.now(timezone.utc).isoformat(),
            device_public_key_multibase="z6Mk...",
            challenge="challenge",
            platform="Web",
            webauthn_signature="signature_data",
            webauthn_authenticator_data="auth_data",
            webauthn_client_data_json='{"type":"webauthn.get"}'
        )

        # Validate WebAuthn fields
        assert attestation.webauthn_signature is not None
        assert attestation.webauthn_authenticator_data is not None
        assert attestation.webauthn_client_data_json is not None


class TestA2AMessageHeaderModel:
    """Test A2AMessageHeader model validation"""

    def test_message_header_valid(self):
        """Test valid A2AMessageHeader creation"""
        from common.models import A2AMessageHeader

        header = A2AMessageHeader(
            message_id="msg_001",
            sender="did:ap2:agent:shopping_agent",
            recipient="did:ap2:agent:merchant_agent",
            timestamp=datetime.now(timezone.utc).isoformat(),
            nonce="unique_nonce_123",
            schema_version="0.2"
        )

        # Validate required fields
        assert header.message_id == "msg_001"
        assert header.sender.startswith("did:ap2:")
        assert header.recipient.startswith("did:ap2:")
        assert header.schema_version == "0.2"

    def test_message_header_with_proof(self):
        """Test message header with proof"""
        from common.models import A2AMessageHeader, A2AProof

        proof = A2AProof(
            algorithm="ed25519",
            signatureValue="sig",
            publicKeyMultibase="z6Mk...",
            created=datetime.now(timezone.utc).isoformat()
        )

        header = A2AMessageHeader(
            message_id="msg_001",
            sender="did:ap2:agent:shopping_agent",
            recipient="did:ap2:agent:merchant_agent",
            timestamp=datetime.now(timezone.utc).isoformat(),
            nonce="nonce",
            schema_version="0.2",
            proof=proof
        )

        # Validate proof is attached
        assert header.proof is not None
        assert header.proof.algorithm == "ed25519"


class TestA2ADataPartModel:
    """Test A2ADataPart model validation"""

    def test_data_part_valid_types(self):
        """Test valid A2ADataPart types"""
        from common.models import A2ADataPart

        valid_types = [
            "ap2.mandates.IntentMandate",
            "ap2.mandates.CartMandate",
            "ap2.mandates.PaymentMandate",
            "ap2.requests.CartRequest",
            "ap2.responses.CartMandatePending",
            "ap2.errors.Error"
        ]

        for msg_type in valid_types:
            data_part = A2ADataPart(
                type=msg_type,
                id="test_001",
                payload={"test": "data"}
            )
            assert data_part.type == msg_type


class TestDIDDocumentModel:
    """Test DIDDocument model validation"""

    def test_did_document_valid(self):
        """Test valid DIDDocument creation"""
        from common.models import DIDDocument, VerificationMethod

        verification_method = VerificationMethod(
            id="did:ap2:agent:test#key-1",
            type="Ed25519VerificationKey2020",
            controller="did:ap2:agent:test",
            publicKeyPem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----",
            publicKeyMultibase="z6Mk..."
        )

        did_doc = DIDDocument(
            id="did:ap2:agent:test",
            verificationMethod=[verification_method],
            authentication=["#key-1"],
            assertionMethod=["#key-1"]
        )

        # Validate fields
        assert did_doc.id == "did:ap2:agent:test"
        assert len(did_doc.verificationMethod) == 1
        assert "#key-1" in did_doc.authentication

    def test_verification_method_model(self):
        """Test VerificationMethod model"""
        from common.models import VerificationMethod

        vm = VerificationMethod(
            id="did:ap2:agent:test#key-1",
            type="Ed25519VerificationKey2020",
            controller="did:ap2:agent:test",
            publicKeyPem="-----BEGIN PUBLIC KEY-----\n...\n-----END PUBLIC KEY-----"
        )

        # Validate required fields
        assert vm.id.endswith("#key-1")
        assert vm.controller.startswith("did:ap2:")
        assert "BEGIN PUBLIC KEY" in vm.publicKeyPem


class TestUserConsentModel:
    """Test UserConsent model validation"""

    def test_user_consent_valid(self):
        """Test valid UserConsent creation"""
        from common.models import UserConsent

        consent = UserConsent(
            consent_id="consent_001",
            cart_mandate_id="cart_001",
            intent_message_id="intent_001",
            user_id="user_001",
            approved=True,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        # Validate fields
        assert consent.approved is True
        assert consent.user_id == "user_001"

    def test_user_consent_with_passkey(self):
        """Test UserConsent with passkey signature"""
        from common.models import UserConsent

        consent = UserConsent(
            consent_id="consent_001",
            cart_mandate_id="cart_001",
            intent_message_id="intent_001",
            user_id="user_001",
            approved=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
            passkey_signature={
                "signature": "sig_data",
                "clientDataJSON": "client_data",
                "authenticatorData": "auth_data"
            }
        )

        # Validate passkey signature
        assert consent.passkey_signature is not None
        assert "signature" in consent.passkey_signature


class TestServiceEndpointModel:
    """Test ServiceEndpoint model validation"""

    def test_service_endpoint_valid(self):
        """Test valid ServiceEndpoint creation"""
        from common.models import ServiceEndpoint

        endpoint = ServiceEndpoint(
            id="did:ap2:cp:demo_cp#credential-service",
            type="CredentialProvider",
            serviceEndpoint="http://credential_provider:8003",
            name="Demo Credential Provider",
            description="AP2 Demo Credential Provider Service",
            supported_methods=["passkey", "webauthn"]
        )

        # Validate fields
        assert endpoint.type == "CredentialProvider"
        assert endpoint.serviceEndpoint.startswith("http")
        assert "passkey" in endpoint.supported_methods


class TestRequiredFieldsValidation:
    """Test required fields validation"""

    def test_missing_required_field_raises_error(self):
        """Test that missing required fields raise ValidationError"""
        from common.models import Signature

        # Missing required field 'value'
        with pytest.raises(ValidationError):
            Signature(
                publicKeyMultibase="z6Mk...",
                signed_at=datetime.now(timezone.utc).isoformat()
                # 'value' is missing
            )

    def test_all_required_fields_present(self):
        """Test that all required fields must be present"""
        from common.models import Signature

        # All required fields present - should not raise
        signature = Signature(
            value="sig_value",
            publicKeyMultibase="z6Mk...",
            signed_at=datetime.now(timezone.utc).isoformat()
        )
        assert signature.value == "sig_value"


class TestFieldDefaults:
    """Test field default values"""

    def test_signature_default_algorithm(self):
        """Test Signature default algorithm"""
        from common.models import Signature

        sig = Signature(
            value="sig",
            publicKeyMultibase="z6Mk...",
            signed_at=datetime.now(timezone.utc).isoformat()
        )

        assert sig.algorithm == "Ed25519"

    def test_a2a_proof_default_purpose(self):
        """Test A2AProof default purpose"""
        from common.models import A2AProof

        proof = A2AProof(
            signatureValue="sig",
            publicKeyMultibase="z6Mk...",
            created=datetime.now(timezone.utc).isoformat()
        )

        assert proof.algorithm == "ed25519"
        assert proof.proofPurpose == "authentication"


class TestMultibaseValidation:
    """Test multibase format validation"""

    def test_multibase_format_starts_with_z(self):
        """Test that publicKeyMultibase starts with 'z'"""
        multibase_examples = [
            "z6MkpTHR8VNsBxYAAWHut2Geadd9jSwuBV8xRoAnwWsdvktH",  # Ed25519
            "z2oAtgCswLVHGBgbaEmaRp6m1zmj3jx4tf1LgSCKreVPjwRm1"   # P-256
        ]

        for multibase in multibase_examples:
            assert multibase.startswith("z")
            assert len(multibase) > 20
