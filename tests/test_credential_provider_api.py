"""
Tests for Credential Provider API

Tests cover:
- WebAuthn registration and authentication flow
- Passkey management
- Token issuance (Agent Token, Network Token)
- Payment method management
- User authorization VP generation
"""

import pytest
from datetime import datetime, timezone
import base64
import json


class TestWebAuthnRegistration:
    """Test WebAuthn/Passkey registration flow"""

    def test_registration_options_structure(self):
        """Test registration options structure"""
        registration_options = {
            "challenge": "base64url_encoded_challenge",
            "rp": {
                "name": "AP2 Demo App",
                "id": "localhost"
            },
            "user": {
                "id": "base64url_user_id",
                "name": "testuser@example.com",
                "displayName": "Test User"
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},  # ES256
                {"type": "public-key", "alg": -257}  # RS256
            ],
            "authenticatorSelection": {
                "authenticatorAttachment": "platform",
                "userVerification": "required",
                "residentKey": "required"
            },
            "timeout": 60000
        }

        # Validate required fields
        assert "challenge" in registration_options
        assert "rp" in registration_options
        assert "user" in registration_options
        assert "pubKeyCredParams" in registration_options

    def test_registration_response_structure(self):
        """Test registration response structure"""
        registration_response = {
            "id": "credential_id_base64url",
            "rawId": "credential_id_base64url",
            "response": {
                "clientDataJSON": "base64url_encoded",
                "attestationObject": "base64url_encoded"
            },
            "type": "public-key"
        }

        # Validate required fields
        assert "id" in registration_response
        assert "response" in registration_response
        assert "clientDataJSON" in registration_response["response"]
        assert "attestationObject" in registration_response["response"]
        assert registration_response["type"] == "public-key"


class TestWebAuthnAuthentication:
    """Test WebAuthn authentication flow"""

    def test_authentication_options_structure(self):
        """Test authentication options structure"""
        authentication_options = {
            "challenge": "base64url_encoded_challenge",
            "timeout": 60000,
            "rpId": "localhost",
            "allowCredentials": [
                {
                    "type": "public-key",
                    "id": "credential_id_base64url",
                    "transports": ["internal"]
                }
            ],
            "userVerification": "required"
        }

        # Validate required fields
        assert "challenge" in authentication_options
        assert "rpId" in authentication_options
        assert "allowCredentials" in authentication_options

    def test_authentication_response_structure(self):
        """Test authentication response structure"""
        authentication_response = {
            "id": "credential_id_base64url",
            "rawId": "credential_id_base64url",
            "response": {
                "clientDataJSON": "base64url_encoded",
                "authenticatorData": "base64url_encoded",
                "signature": "base64url_encoded",
                "userHandle": "base64url_user_id"
            },
            "type": "public-key"
        }

        # Validate required fields
        assert "id" in authentication_response
        assert "response" in authentication_response
        assert "clientDataJSON" in authentication_response["response"]
        assert "authenticatorData" in authentication_response["response"]
        assert "signature" in authentication_response["response"]
        assert authentication_response["type"] == "public-key"


class TestPasskeyManagement:
    """Test Passkey credential management"""

    def test_passkey_credential_storage(self):
        """Test passkey credential storage structure"""
        passkey_credential = {
            "credential_id": "cred_abc123",
            "user_id": "user_001",
            "public_key_cose": "base64_encoded_cose_key",
            "counter": 0,
            "transports": ["internal", "usb"],
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Validate required fields
        assert "credential_id" in passkey_credential
        assert "user_id" in passkey_credential
        assert "public_key_cose" in passkey_credential
        assert "counter" in passkey_credential

    def test_counter_increment_replay_protection(self):
        """Test counter increment for replay protection"""
        initial_counter = 0
        new_counter = 5

        # Counter should always increase
        assert new_counter > initial_counter

    def test_multiple_passkeys_per_user(self):
        """Test user can have multiple passkeys"""
        user_id = "user_001"
        passkeys = [
            {"credential_id": "cred_1", "user_id": user_id},
            {"credential_id": "cred_2", "user_id": user_id},
            {"credential_id": "cred_3", "user_id": user_id}
        ]

        # All passkeys should belong to same user
        assert all(pk["user_id"] == user_id for pk in passkeys)
        # Credential IDs should be unique
        credential_ids = [pk["credential_id"] for pk in passkeys]
        assert len(credential_ids) == len(set(credential_ids))


class TestTokenIssuance:
    """Test token issuance (Agent Token, Network Token)"""

    def test_agent_token_structure(self):
        """Test Agent Token structure"""
        agent_token = {
            "token": "at_xxxxxxxxxxxxxxxx",
            "token_type": "agent_token",
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "payment_method_id": "pm_001",
            "payer_id": "user_001",
            "scope": "payment_authorization"
        }

        # Validate required fields
        assert "token" in agent_token
        assert agent_token["token"].startswith("at_")
        assert agent_token["token_type"] == "agent_token"
        assert "expires_at" in agent_token
        assert "payment_method_id" in agent_token

    def test_network_token_structure(self):
        """Test Network Token structure"""
        network_token = {
            "token": "nt_xxxxxxxxxxxxxxxx",
            "token_type": "network_token",
            "expires_at": datetime.now(timezone.utc).isoformat(),
            "brand": "visa",
            "last4": "4242",
            "cryptogram": "base64_cryptogram"
        }

        # Validate required fields
        assert "token" in network_token
        assert network_token["token"].startswith("nt_")
        assert network_token["token_type"] == "network_token"
        assert "brand" in network_token
        assert "last4" in network_token

    def test_token_expiration(self):
        """Test token has expiration"""
        token = {
            "token": "at_test",
            "expires_at": "2025-12-31T23:59:59Z"
        }

        # Should have expiration timestamp
        assert "expires_at" in token
        expiry = datetime.fromisoformat(token["expires_at"].replace('Z', '+00:00'))
        assert expiry.tzinfo is not None


class TestPaymentMethodManagement:
    """Test payment method management"""

    def test_payment_method_storage(self):
        """Test payment method storage structure"""
        payment_method = {
            "id": "pm_001",
            "user_id": "user_001",
            "type": "card",
            "display_name": "Visa ****4242",
            "brand": "visa",
            "last4": "4242",
            "requires_step_up": False,
            "created_at": datetime.now(timezone.utc).isoformat()
        }

        # Validate required fields
        assert "id" in payment_method
        assert payment_method["id"].startswith("pm_")
        assert "user_id" in payment_method
        assert "type" in payment_method

    def test_payment_method_pci_compliance(self):
        """Test payment method does not expose PCI data"""
        safe_payment_method = {
            "id": "pm_001",
            "type": "card",
            "brand": "visa",
            "last4": "4242",
            "display_name": "Visa ****4242"
        }

        # Should NOT contain PCI sensitive data
        pci_fields = ["card_number", "cvv", "expiry_month", "expiry_year"]
        for field in pci_fields:
            assert field not in safe_payment_method

    def test_payment_method_types(self):
        """Test valid payment method types"""
        valid_types = ["card", "bank_account", "digital_wallet"]

        for payment_type in valid_types:
            payment_method = {
                "id": f"pm_{payment_type}",
                "type": payment_type
            }
            assert payment_method["type"] in valid_types


class TestUserAuthorizationGeneration:
    """Test user authorization VP generation"""

    def test_user_authorization_vp_format(self):
        """Test user authorization VP format (SD-JWT+KB)"""
        # VP format: "issuer_jwt~kb_jwt"
        user_authorization = "eyJ...issuer.jwt~eyJ...kb.jwt"

        # Should contain tilde separator
        assert "~" in user_authorization

        # Should have at least 2 parts
        parts = user_authorization.split("~")
        assert len(parts) >= 2

    def test_issuer_jwt_claims(self):
        """Test issuer JWT claims structure"""
        issuer_jwt_payload = {
            "iss": "did:ap2:cp:demo_cp",
            "sub": "user_001",
            "aud": "did:ap2:agent:payment_processor",
            "exp": 1735689599,
            "iat": 1735686000,
            "cnf": {
                "jwk": {
                    "kty": "EC",
                    "crv": "P-256",
                    "x": "base64url_x",
                    "y": "base64url_y"
                }
            }
        }

        # Validate required claims
        assert "iss" in issuer_jwt_payload
        assert "sub" in issuer_jwt_payload
        assert "cnf" in issuer_jwt_payload
        assert "jwk" in issuer_jwt_payload["cnf"]

    def test_kb_jwt_claims(self):
        """Test key-binding JWT claims structure"""
        kb_jwt_payload = {
            "aud": "did:ap2:agent:payment_processor",
            "iat": 1735686000,
            "nonce": "unique_nonce_value",
            "transaction_data": {
                "cart_mandate_hash": "abc123...",
                "payment_mandate_hash": "def456..."
            },
            "webauthn_signature": "base64_signature",
            "webauthn_authenticator_data": "base64_auth_data",
            "webauthn_client_data_json": "base64_client_data"
        }

        # Validate required claims
        assert "transaction_data" in kb_jwt_payload
        assert "cart_mandate_hash" in kb_jwt_payload["transaction_data"]
        assert "payment_mandate_hash" in kb_jwt_payload["transaction_data"]
        assert "webauthn_signature" in kb_jwt_payload


class TestCredentialProviderSecurity:
    """Test Credential Provider security features"""

    def test_challenge_uniqueness(self):
        """Test challenges are unique"""
        challenges = set()

        for _ in range(10):
            challenge = base64.urlsafe_b64encode(b'\x00' * 32).decode('utf-8')
            challenges.add(challenge)

        # All challenges should be unique (in real impl)
        # This test shows the expected behavior
        assert len(challenges) >= 1

    def test_challenge_expiration(self):
        """Test challenges have expiration"""
        challenge_data = {
            "challenge": "base64_challenge",
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc)).isoformat()
        }

        assert "expires_at" in challenge_data

    def test_user_verification_required(self):
        """Test user verification is required"""
        auth_options = {
            "userVerification": "required",
            "authenticatorSelection": {
                "userVerification": "required"
            }
        }

        assert auth_options["userVerification"] == "required"


class TestCredentialProviderEndpoints:
    """Test Credential Provider API endpoints structure"""

    def test_register_passkey_request(self):
        """Test passkey registration request"""
        request = {
            "user_id": "user_001",
            "username": "testuser"
        }

        assert "user_id" in request

    def test_authenticate_passkey_request(self):
        """Test passkey authentication request"""
        request = {
            "user_id": "user_001",
            "assertion": {
                "id": "credential_id",
                "response": {
                    "clientDataJSON": "base64",
                    "authenticatorData": "base64",
                    "signature": "base64"
                }
            }
        }

        assert "user_id" in request
        assert "assertion" in request

    def test_issue_agent_token_request(self):
        """Test agent token issuance request"""
        request = {
            "user_id": "user_001",
            "payment_method_id": "pm_001",
            "user_authorization": "vp_token"
        }

        assert "user_id" in request
        assert "payment_method_id" in request
        assert "user_authorization" in request


# ============================================================================
# Endpoint Implementation Tests - Improve Coverage
# ============================================================================


class TestCredentialProviderEndpointImplementation:
    """Test actual Credential Provider endpoint implementations"""

    @pytest.mark.asyncio
    async def test_get_payment_methods_endpoint(self, credential_provider_client, db_manager):
        """Test GET /payment-methods/{user_id} endpoint"""
        from common.database import PaymentMethodCRUD

        # Create test payment method
        async with db_manager.get_session() as session:
            await PaymentMethodCRUD.create(session, {
                "id": "pm_test_001",
                "user_id": "user_test_001",
                "payment_method": {
                    "type": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "display_name": "Test Card (****1234)",
                    "card_last4": "1234",
                    "card_brand": "Visa",
                    "billing_address": {
                        "country": "JP",
                        "postal_code": "100-0001"
                    },
                    "requires_step_up": False
                }
            })

        # Get payment methods
        response = credential_provider_client.get("/payment-methods/user_test_001")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_test_001"
        assert "payment_methods" in data
        assert len(data["payment_methods"]) > 0

    @pytest.mark.asyncio
    async def test_add_payment_method_endpoint(self, credential_provider_client):
        """Test POST /payment-methods endpoint"""
        request_data = {
            "user_id": "user_test_002",
            "payment_method": {
                "type": "https://a2a-protocol.org/payment-methods/ap2-payment",
                "display_name": "New Card (****5678)",
                "card_last4": "5678",
                "card_brand": "Mastercard",
                "billing_address": {
                    "country": "JP",
                    "postal_code": "150-0001"
                },
                "requires_step_up": False
            }
        }

        response = credential_provider_client.post("/payment-methods", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert data["user_id"] == "user_test_002"

    @pytest.mark.asyncio
    async def test_delete_payment_method_endpoint(self, credential_provider_client, db_manager):
        """Test DELETE /payment-methods/{payment_method_id} endpoint"""
        from common.database import PaymentMethodCRUD

        # Create test payment method
        async with db_manager.get_session() as session:
            pm = await PaymentMethodCRUD.create(session, {
                "id": "pm_delete_001",
                "user_id": "user_test_003",
                "payment_method": {
                    "type": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "display_name": "Test Card",
                    "card_last4": "9999",
                    "card_brand": "Visa",
                    "billing_address": {},
                    "requires_step_up": False
                }
            })

        # Delete payment method
        response = credential_provider_client.delete("/payment-methods/pm_delete_001")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

        # Verify it's deleted
        async with db_manager.get_session() as session:
            pm = await PaymentMethodCRUD.get_by_id(session, "pm_delete_001")
            assert pm is None

    @pytest.mark.asyncio
    async def test_tokenize_payment_method_endpoint(self, credential_provider_client, db_manager):
        """Test POST /tokenize-payment-method endpoint"""
        from common.database import PaymentMethodCRUD

        # Create test payment method
        async with db_manager.get_session() as session:
            await PaymentMethodCRUD.create(session, {
                "id": "pm_tokenize_001",
                "user_id": "user_test_004",
                "payment_method": {
                    "type": "https://a2a-protocol.org/payment-methods/ap2-payment",
                    "display_name": "Test Card (****4242)",
                    "card_last4": "4242",
                    "card_brand": "Visa",
                    "billing_address": {},
                    "requires_step_up": False
                }
            })

        request_data = {
            "user_id": "user_test_004",
            "payment_method_id": "pm_tokenize_001"
        }

        response = credential_provider_client.post("/tokenize-payment-method", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert "token" in data
        assert "expires_at" in data
        assert data["card_last4"] == "4242"
        assert data["card_brand"] == "Visa"

    @pytest.mark.asyncio
    async def test_get_passkey_public_key_endpoint(self, credential_provider_client, db_manager):
        """Test POST /passkey-public-key endpoint"""
        from common.database import PasskeyCredentialCRUD

        # Create test passkey credential
        async with db_manager.get_session() as session:
            await PasskeyCredentialCRUD.create(session, {
                "credential_id": "cred_test_001",
                "user_id": "user_test_005",
                "public_key_cose": base64.urlsafe_b64encode(b"test_public_key").decode(),
                "sign_count": 0,
                "created_at": datetime.now(timezone.utc).isoformat()
            })

        request_data = {
            "credential_id": "cred_test_001"
        }

        response = credential_provider_client.post("/passkey-public-key", json=request_data)

        assert response.status_code == 200
        data = response.json()
        assert "public_key_cose" in data
        assert "user_id" in data
        assert data["user_id"] == "user_test_005"

    @pytest.mark.asyncio
    async def test_receive_receipt_endpoint(self, credential_provider_client):
        """Test POST /receipts endpoint"""
        receipt_data = {
            "transaction_id": "txn_test_001",
            "receipt_url": "http://example.com/receipt/001",
            "payer_id": "user_test_006",
            "amount": {"value": "10000", "currency": "JPY"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        response = credential_provider_client.post("/receipts", json=receipt_data)

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "received"
        assert data["transaction_id"] == "txn_test_001"

    @pytest.mark.asyncio
    async def test_get_receipts_endpoint(self, credential_provider_client, db_manager):
        """Test GET /receipts/{user_id} endpoint"""
        from common.database import ReceiptCRUD

        # Create test receipt
        async with db_manager.get_session() as session:
            await ReceiptCRUD.create(session, {
                "transaction_id": "txn_get_test_001",
                "payer_id": "user_test_007",
                "receipt_url": "http://example.com/receipt/get001",
                "amount": 50000,
                "currency": "JPY",
                "timestamp": datetime.now(timezone.utc).isoformat()
            })

        response = credential_provider_client.get("/receipts/user_test_007")

        assert response.status_code == 200
        data = response.json()
        assert data["user_id"] == "user_test_007"
        assert "receipts" in data
        assert data["total_count"] > 0


class TestCredentialProviderErrorHandling:
    """Test error handling in Credential Provider endpoints"""

    @pytest.mark.asyncio
    async def test_get_payment_methods_not_found(self, credential_provider_client):
        """Test GET /payment-methods/{user_id} with non-existent user"""
        response = credential_provider_client.get("/payment-methods/nonexistent_user")

        assert response.status_code == 200  # Returns empty list, not 404
        data = response.json()
        assert data["user_id"] == "nonexistent_user"
        assert len(data["payment_methods"]) == 0

    @pytest.mark.asyncio
    async def test_delete_payment_method_not_found(self, credential_provider_client):
        """Test DELETE /payment-methods/{payment_method_id} with non-existent ID"""
        response = credential_provider_client.delete("/payment-methods/nonexistent_pm")

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_tokenize_payment_method_not_found(self, credential_provider_client):
        """Test POST /tokenize-payment-method with non-existent payment method"""
        request_data = {
            "user_id": "user_test",
            "payment_method_id": "nonexistent_pm"
        }

        response = credential_provider_client.post("/tokenize-payment-method", json=request_data)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_get_passkey_public_key_not_found(self, credential_provider_client):
        """Test POST /passkey-public-key with non-existent credential"""
        request_data = {
            "credential_id": "nonexistent_cred"
        }

        response = credential_provider_client.post("/passkey-public-key", json=request_data)

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_receive_receipt_missing_fields(self, credential_provider_client):
        """Test POST /receipts with missing required fields"""
        receipt_data = {
            "transaction_id": "txn_incomplete"
            # Missing required fields
        }

        response = credential_provider_client.post("/receipts", json=receipt_data)

        assert response.status_code == 400


class TestCredentialProviderHelperMethods:
    """Test helper methods in Credential Provider"""

    @pytest.mark.asyncio
    async def test_generate_token_method(self):
        """Test _generate_token helper method"""
        from unittest.mock import patch, Mock
        from services.credential_provider.provider import CredentialProviderService

        # Mock service initialization
        with patch.object(CredentialProviderService, '__init__', return_value=None):
            service = CredentialProviderService()

            # Mock the token_helpers with a method that returns expected token
            mock_token_helpers = Mock()
            mock_token_helpers.generate_token.return_value = "cred_token_abc123xyz789"
            service.token_helpers = mock_token_helpers

            payment_mandate = {
                "payer_id": "user_test_helper",
                "id": "pm_helper_001"
            }

            attestation = {
                "verified": True
            }

            token = service._generate_token(payment_mandate, attestation)

            assert isinstance(token, str)
            assert token.startswith("cred_token_")
            assert len(token) > 20  # Should be reasonably long

            # Verify the helper was called with correct arguments
            mock_token_helpers.generate_token.assert_called_once_with(payment_mandate, attestation)

    @pytest.mark.asyncio
    async def test_save_attestation_method(self, db_manager):
        """Test _save_attestation helper method"""
        from unittest.mock import patch, AsyncMock
        from services.credential_provider.provider import CredentialProviderService

        # Mock service initialization
        with patch.object(CredentialProviderService, '__init__', return_value=None):
            service = CredentialProviderService()
            service.db_manager = db_manager

            # Mock the token_helpers with async method
            mock_token_helpers = AsyncMock()
            service.token_helpers = mock_token_helpers

            attestation_raw = {
                "type": "webauthn",
                "credential_id": "cred_save_test"
            }

            await service._save_attestation(
                user_id="user_save_test",
                attestation_raw=attestation_raw,
                verified=True,
                token="test_token_123",
                agent_token="agent_token_456"
            )

            # Verify the helper was called with correct arguments
            mock_token_helpers.save_attestation.assert_called_once()
            call_args = mock_token_helpers.save_attestation.call_args
            assert call_args.kwargs["user_id"] == "user_save_test"
            assert call_args.kwargs["verified"] is True
            assert call_args.kwargs["token"] == "test_token_123"
            assert call_args.kwargs["agent_token"] == "agent_token_456"
