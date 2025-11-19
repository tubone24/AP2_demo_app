"""
Tests for Payment Processor Service (processor.py)

Tests cover:
- PaymentProcessorService initialization
- Payment processing workflows
- JWT validation
- Mandate validation
- Receipt generation
- Transaction management
- Credential verification
- HTTP endpoints
"""

import pytest
import uuid
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from fastapi import HTTPException
from fastapi.testclient import TestClient


class TestPaymentProcessorServiceInit:
    """Test PaymentProcessorService initialization"""

    @patch('common.base_agent.KeyManager')
    @patch('services.payment_processor.processor.MandateHelpers')
    @patch('services.payment_processor.processor.JWTHelpers')
    @patch('services.payment_processor.processor.LoggingAsyncClient')
    @patch('services.payment_processor.processor.DatabaseManager')
    def test_service_initialization(self, mock_db_manager, mock_http_client,
                                    mock_jwt_helpers, mock_mandate_helpers, mock_key_manager):
        """Test service initializes with correct configuration"""
        from services.payment_processor.processor import PaymentProcessorService

        service = PaymentProcessorService()

        # Verify agent properties
        assert service.agent_id == "did:ap2:agent:payment_processor"
        assert service.agent_name == "Payment Processor"

        # Verify database manager was created
        mock_db_manager.assert_called_once()

        # Verify HTTP client was created
        mock_http_client.assert_called_once()

    def test_get_ap2_roles(self):
        """Test AP2 roles are correctly defined"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()
            roles = service.get_ap2_roles()

            assert isinstance(roles, list)
            assert "payment-processor" in roles

    def test_get_agent_description(self):
        """Test agent description"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()
            description = service.get_agent_description()

            assert isinstance(description, str)
            assert "Payment Processor" in description
            assert "AP2" in description


class TestPaymentMandateValidation:
    """Test PaymentMandate validation"""

    def test_validate_payment_mandate_success(self):
        """Test successful payment mandate validation"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            payment_mandate = {
                "id": "pm_test_001",
                "type": "PaymentMandate",
                "payer_id": "user_001",
                "payee_id": "merchant_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_method": {
                    "type": "card",
                    "token": "tok_test_123"
                },
                "user_authorization": "mock_user_auth_jwt"
            }

            # Should not raise exception
            service._validate_payment_mandate(payment_mandate)

    def test_validate_payment_mandate_missing_fields(self):
        """Test payment mandate validation with missing fields"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            # Missing amount
            payment_mandate = {
                "id": "pm_test_001",
                "payer_id": "user_001"
            }

            with pytest.raises(Exception):
                service._validate_payment_mandate(payment_mandate)


class TestMandateChainValidation:
    """Test mandate chain validation"""

    @pytest.mark.asyncio
    async def test_validate_mandate_chain_success(self):
        """Test successful mandate chain validation"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            cart_mandate = {
                "contents": {
                    "id": "cart_001"
                },
                "merchant_authorization": None
            }

            payment_mandate = {
                "id": "pm_001",
                "cart_mandate_id": "cart_001",
                "user_authorization": None  # Skip for basic test
            }

            # Should validate successfully
            result = service._validate_mandate_chain(payment_mandate, cart_mandate)
            assert result is True

    @pytest.mark.asyncio
    async def test_validate_mandate_chain_missing_cart(self):
        """Test mandate chain validation without cart mandate"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            payment_mandate = {
                "id": "pm_001",
                "cart_mandate_id": "cart_001"
            }

            with pytest.raises(ValueError, match="CartMandate is required"):
                service._validate_mandate_chain(payment_mandate, None)

    @pytest.mark.asyncio
    async def test_validate_mandate_chain_id_mismatch(self):
        """Test mandate chain validation with ID mismatch"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            cart_mandate = {
                "contents": {
                    "id": "cart_002"  # Different ID
                }
            }

            payment_mandate = {
                "id": "pm_001",
                "cart_mandate_id": "cart_001"  # Expects cart_001
            }

            with pytest.raises(ValueError, match="references cart_mandate_id"):
                service._validate_mandate_chain(payment_mandate, cart_mandate)


class TestPaymentProcessing:
    """Test payment processing logic"""

    @pytest.mark.asyncio
    async def test_process_payment_success(self):
        """Test successful payment processing"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient') as mock_client:
            service = PaymentProcessorService()

            # Mock HTTP responses
            mock_http_client = AsyncMock()
            service.http_client = mock_http_client

            # Mock credential verification response
            credential_response = AsyncMock()
            credential_response.status_code = 200
            credential_response.json.return_value = {
                "verified": True,
                "credential_info": {
                    "payment_method_id": "pm_123",
                    "agent_token": "agent_tok_test_123"
                }
            }

            # Mock payment network charge response
            charge_response = AsyncMock()
            charge_response.status_code = 200
            charge_response.json.return_value = {
                "status": "captured",
                "network_transaction_id": "net_txn_123",
                "authorization_code": "AUTH123"
            }

            mock_http_client.post.side_effect = [
                credential_response,
                charge_response
            ]

            payment_mandate = {
                "id": "pm_001",
                "payer_id": "user_001",
                "payee_id": "merchant_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_method": {
                    "token": "tok_test_123"
                },
                "risk_score": 10,
                "user_authorization": "mock_jwt"
            }

            # Need to mock _verify_credential_with_cp to return awaitable
            async def mock_verify():
                return {
                    "payment_method_id": "pm_123",
                    "agent_token": "agent_tok_test_123"
                }

            service._verify_credential_with_cp = mock_verify

            result = await service._process_payment_mock(
                transaction_id="txn_001",
                payment_mandate=payment_mandate
            )

            assert result["status"] == "captured"
            assert result["transaction_id"] == "txn_001"

    @pytest.mark.asyncio
    async def test_process_payment_high_risk(self):
        """Test payment processing with high risk score"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            payment_mandate = {
                "id": "pm_001",
                "payer_id": "user_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_method": {
                    "token": "tok_test_123"
                },
                "risk_score": 85,  # High risk
                "fraud_indicators": ["suspicious_location"],
                "user_authorization": "mock_jwt"
            }

            # Mock credential verification to avoid async issues
            async def mock_verify(token, payer_id, amount):
                return {"agent_token": "test_token"}
            service._verify_credential_with_cp = mock_verify

            result = await service._process_payment_mock(
                transaction_id="txn_001",
                payment_mandate=payment_mandate
            )

            assert result["status"] == "failed"
            assert "High risk" in result["error"]

    @pytest.mark.asyncio
    async def test_process_payment_missing_token(self):
        """Test payment processing without payment method token"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            payment_mandate = {
                "id": "pm_001",
                "payer_id": "user_001",
                "amount": {
                    "value": "1000.00",
                    "currency": "JPY"
                },
                "payment_method": {}  # No token
            }

            result = await service._process_payment_mock(
                transaction_id="txn_001",
                payment_mandate=payment_mandate
            )

            assert result["status"] == "failed"
            assert "No payment method token" in result["error"]


class TestCredentialVerification:
    """Test credential verification with Credential Provider"""

    @pytest.mark.asyncio
    async def test_verify_credential_success(self):
        """Test successful credential verification"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            # Mock HTTP client properly as awaitable
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "verified": True,
                "credential_info": {
                    "payment_method_id": "pm_123",
                    "agent_token": "agent_tok_test"
                }
            })
            mock_response.raise_for_status = AsyncMock()

            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            service.http_client = mock_http_client

            result = await service._verify_credential_with_cp(
                token="tok_test",
                payer_id="user_001",
                amount={"value": "1000.00", "currency": "JPY"}
            )

            assert result["payment_method_id"] == "pm_123"
            assert result["agent_token"] == "agent_tok_test"

    @pytest.mark.asyncio
    async def test_verify_credential_failed(self):
        """Test failed credential verification"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            # Mock HTTP client properly as awaitable
            mock_response = AsyncMock()
            mock_response.status_code = 200
            mock_response.json = AsyncMock(return_value={
                "verified": False,
                "error": "Invalid token"
            })
            mock_response.raise_for_status = AsyncMock()

            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            service.http_client = mock_http_client

            with pytest.raises(ValueError, match="Credential verification failed"):
                await service._verify_credential_with_cp(
                    token="tok_invalid",
                    payer_id="user_001",
                    amount={"value": "1000.00", "currency": "JPY"}
                )


class TestTransactionManagement:
    """Test transaction save and retrieval"""

    @pytest.mark.asyncio
    async def test_save_transaction(self):
        """Test transaction is saved to database"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager') as mock_db, \
             patch('services.payment_processor.processor.LoggingAsyncClient'):

            # Mock database session
            mock_session = AsyncMock()
            mock_db_instance = AsyncMock()
            mock_db_instance.get_session.return_value.__aenter__.return_value = mock_session
            mock_db.return_value = mock_db_instance

            service = PaymentProcessorService()

            payment_mandate = {
                "id": "pm_001",
                "cart_mandate_id": "cart_001",
                "intent_mandate_id": "intent_001"
            }

            result = {
                "status": "captured",
                "transaction_id": "txn_001"
            }

            with patch('common.database.TransactionCRUD.create') as mock_create:
                await service._save_transaction(
                    transaction_id="txn_001",
                    payment_mandate=payment_mandate,
                    result=result
                )

                # Verify TransactionCRUD.create was called
                mock_create.assert_called_once()
                call_args = mock_create.call_args[0]
                assert call_args[1]["id"] == "txn_001"
                assert call_args[1]["status"] == "captured"


class TestReceiptGeneration:
    """Test receipt generation"""

    @pytest.mark.asyncio
    async def test_generate_receipt_success(self):
        """Test successful receipt generation"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager') as mock_db, \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.receipt_generator.generate_receipt_pdf') as mock_gen_pdf, \
             patch('builtins.open', create=True) as mock_open:

            # Mock database
            mock_session = AsyncMock()
            mock_db_instance = AsyncMock()
            mock_db_instance.get_session.return_value.__aenter__.return_value = mock_session
            mock_db.return_value = mock_db_instance

            # Mock transaction
            mock_transaction = Mock()
            mock_transaction.to_dict.return_value = {
                "id": "txn_001",
                "events": [{
                    "type": "payment_processed",
                    "result": {
                        "status": "captured",
                        "amount": {"value": "1000.00", "currency": "JPY"},
                        "authorized_at": datetime.now(timezone.utc).isoformat(),
                        "captured_at": datetime.now(timezone.utc).isoformat()
                    }
                }]
            }

            # Mock PDF generation
            mock_pdf_buffer = Mock()
            mock_pdf_buffer.getvalue.return_value = b"PDF content"
            mock_gen_pdf.return_value = mock_pdf_buffer

            with patch('common.database.TransactionCRUD.get_by_id',
                      return_value=mock_transaction), \
                 patch('common.database.ReceiptCRUD.create'):

                service = PaymentProcessorService()

                cart_mandate = {
                    "contents": {
                        "id": "cart_001",
                        "payment_request": {
                            "details": {
                                "display_items": [],
                                "total": {
                                    "amount": {"value": 1000.0, "currency": "JPY"}
                                }
                            }
                        }
                    }
                }

                payment_mandate = {
                    "payer_id": "user_001"
                }

                receipt_url = await service._generate_receipt(
                    transaction_id="txn_001",
                    payment_mandate=payment_mandate,
                    cart_mandate=cart_mandate
                )

                assert "txn_001.pdf" in receipt_url
                assert receipt_url.startswith("http://")

    @pytest.mark.asyncio
    async def test_generate_receipt_missing_cart_mandate(self):
        """Test receipt generation fails without CartMandate"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager') as mock_db, \
             patch('services.payment_processor.processor.LoggingAsyncClient'):

            # Mock database
            mock_session = AsyncMock()
            mock_db_instance = AsyncMock()
            mock_db_instance.get_session.return_value.__aenter__.return_value = mock_session
            mock_db.return_value = mock_db_instance

            # Mock transaction
            mock_transaction = Mock()
            mock_transaction.to_dict.return_value = {
                "id": "txn_001",
                "events": [{
                    "type": "payment_processed",
                    "result": {"status": "captured"}
                }]
            }

            with patch('common.database.TransactionCRUD.get_by_id',
                      return_value=mock_transaction):

                service = PaymentProcessorService()

                payment_mandate = {"payer_id": "user_001"}

                with pytest.raises(ValueError, match="CartMandate not provided"):
                    await service._generate_receipt(
                        transaction_id="txn_001",
                        payment_mandate=payment_mandate,
                        cart_mandate=None
                    )


class TestA2AMessageHandlers:
    """Test A2A message handlers"""

    @pytest.mark.asyncio
    async def test_handle_payment_mandate_success(self):
        """Test successful PaymentMandate handling"""
        from services.payment_processor.processor import PaymentProcessorService
        from common.models import A2AMessage, A2AMessageHeader, A2ADataPart

        with patch('services.payment_processor.processor.DatabaseManager') as mock_db, \
             patch('services.payment_processor.processor.LoggingAsyncClient'):

            # Mock database
            mock_session = AsyncMock()
            mock_db_instance = AsyncMock()
            mock_db_instance.get_session.return_value.__aenter__.return_value = mock_session
            mock_db.return_value = mock_db_instance

            service = PaymentProcessorService()

            # Mock process payment
            with patch.object(service, '_process_payment_mock',
                            return_value={"status": "captured", "transaction_id": "txn_001"}), \
                 patch.object(service, '_save_transaction'), \
                 patch.object(service, '_generate_receipt',
                            return_value="http://localhost:8004/receipts/txn_001.pdf"), \
                 patch.object(service, '_send_receipt_to_credential_provider'):

                message = A2AMessage(
                    header=A2AMessageHeader(
                        message_id="msg_001",
                        sender="did:ap2:agent:shopping_agent",
                        recipient="did:ap2:agent:payment_processor",
                        timestamp=datetime.now(timezone.utc).isoformat()
                    ),
                    dataPart=A2ADataPart(
                        type="ap2.mandates.PaymentMandate",
                        id="pm_001",
                        payload={
                            "payment_mandate": {
                                "id": "pm_001",
                                "payer_id": "user_001",
                                "amount": {"value": "1000.00", "currency": "JPY"},
                                "payment_method": {"token": "tok_123"}
                            },
                            "cart_mandate": {
                                "contents": {"id": "cart_001"}
                            }
                        }
                    )
                )

                result = await service.handle_payment_mandate(message)

                assert result["type"] == "ap2.responses.PaymentResult"
                assert result["payload"]["status"] == "captured"


class TestHTTPEndpoints:
    """Test HTTP endpoint handlers"""

    def test_process_payment_endpoint_structure(self):
        """Test /process endpoint is registered"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            # Check app has routes
            routes = [route.path for route in service.app.routes]

            assert "/process" in routes
            assert "/transactions/{transaction_id}" in routes
            assert "/refund" in routes
            assert "/receipts/{transaction_id}.pdf" in routes
            assert "/.well-known/did.json" in routes

    def test_did_document_endpoint_registered(self):
        """Test DID document endpoint is registered"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            routes = [route.path for route in service.app.routes]
            assert "/.well-known/did.json" in routes


class TestJWTHelpers:
    """Test JWT helper methods"""

    def test_jwt_helpers_initialization(self):
        """Test JWT helpers are initialized"""
        from services.payment_processor.processor import PaymentProcessorService

        with patch('services.payment_processor.processor.DatabaseManager'), \
             patch('services.payment_processor.processor.LoggingAsyncClient'), \
             patch('common.base_agent.KeyManager'):
            service = PaymentProcessorService()

            assert service.jwt_helpers is not None
            assert hasattr(service.jwt_helpers, 'base64url_decode')


class TestConstants:
    """Test constants and configuration"""

    def test_http_timeout_constants(self):
        """Test HTTP timeout constants are defined"""
        from services.payment_processor import processor

        assert hasattr(processor, 'HTTP_CLIENT_TIMEOUT')
        assert hasattr(processor, 'SHORT_HTTP_TIMEOUT')
        assert processor.HTTP_CLIENT_TIMEOUT > 0
        assert processor.SHORT_HTTP_TIMEOUT > 0

    def test_status_constants(self):
        """Test status constants are defined"""
        from services.payment_processor import processor

        assert hasattr(processor, 'STATUS_CAPTURED')
        assert hasattr(processor, 'STATUS_FAILED')
        assert processor.STATUS_CAPTURED == "captured"
        assert processor.STATUS_FAILED == "failed"
