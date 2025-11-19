"""
Tests for Services Utils Helpers

Tests cover:
- signature_helpers.py (merchant)
- validation_helpers.py (merchant)
- hash_helpers.py (shopping_agent)
- inventory_helpers.py (merchant)
- jwt_helpers.py (merchant)
- a2a_helpers.py (shopping_agent)
- cart_helpers.py (shopping_agent)
- payment_helpers.py (shopping_agent)
- credential_provider utils helpers
"""

import pytest
import json
import base64
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock, Mock


class TestSignatureHelpers:
    """Test merchant signature helpers"""

    def test_compute_cart_hash(self):
        """Test cart hash computation"""
        from services.merchant.utils.signature_helpers import SignatureHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "merchant_id": "merchant_001",
                "items": [
                    {"sku": "ITEM-001", "price": 10000}
                ]
            }
        }

        cart_hash = SignatureHelpers.compute_cart_hash(cart_mandate)

        assert isinstance(cart_hash, str)
        assert len(cart_hash) == 64  # SHA256 hex length
        # Hash should be deterministic
        assert cart_hash == SignatureHelpers.compute_cart_hash(cart_mandate)

    def test_compute_cart_hash_with_different_data(self):
        """Test that hash changes with different data"""
        from services.merchant.utils.signature_helpers import SignatureHelpers

        cart_1 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-001"}]
            }
        }

        cart_2 = {
            "contents": {
                "id": "cart_456",
                "items": [{"sku": "ITEM-002"}]
            }
        }

        hash_1 = SignatureHelpers.compute_cart_hash(cart_1)
        hash_2 = SignatureHelpers.compute_cart_hash(cart_2)

        # Hashes should be different for different data
        assert hash_1 != hash_2


class TestValidationHelpers:
    """Test merchant validation helpers"""

    def test_init(self):
        """Test ValidationHelpers initialization"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")
        assert validator.merchant_id == "merchant_001"

    def test_validate_cart_mandate_success(self):
        """Test successful cart mandate validation"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "cart_expiry": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            },
            "_metadata": {
                "merchant_id": "merchant_001"
            }
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_missing_contents(self):
        """Test validation fails with missing contents"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {}

        with pytest.raises(ValueError, match="CartMandate.contents is missing"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_merchant_id_mismatch(self):
        """Test validation fails with merchant ID mismatch"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
            },
            "_metadata": {
                "merchant_id": "merchant_002"  # Different merchant
            }
        }

        with pytest.raises(ValueError, match="Merchant ID mismatch"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_expired(self):
        """Test validation fails with expired cart"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        # Cart expired 1 hour ago
        expired_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "cart_expiry": expired_time
            },
            "_metadata": {
                "merchant_id": "merchant_001"
            }
        }

        with pytest.raises(ValueError, match="CartMandate has expired"):
            validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_no_merchant_id_metadata(self):
        """Test validation passes when no merchant_id in metadata"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
            },
            "_metadata": {}  # No merchant_id
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)

    def test_validate_cart_mandate_no_expiry(self):
        """Test validation passes when no expiry"""
        from services.merchant.utils.validation_helpers import ValidationHelpers

        validator = ValidationHelpers(merchant_id="merchant_001")

        cart_mandate = {
            "contents": {
                "id": "cart_123"
                # No cart_expiry
            }
        }

        # Should not raise
        validator.validate_cart_mandate(cart_mandate)


class TestHashHelpers:
    """Test shopping agent hash helpers"""

    def test_generate_cart_mandate_hash(self):
        """Test cart mandate hash generation"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "items": [
                    {"sku": "ITEM-001", "quantity": 2, "price": 10000}
                ]
            }
        }

        cart_hash = HashHelpers.generate_cart_mandate_hash(cart_mandate)

        assert isinstance(cart_hash, str)
        assert len(cart_hash) == 64  # SHA256 hex
        # Should be deterministic
        assert cart_hash == HashHelpers.generate_cart_mandate_hash(cart_mandate)

    def test_generate_cart_mandate_hash_consistency(self):
        """Test that cart hash is consistent across multiple calls"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate = {
            "contents": {
                "id": "cart_123",
                "items": [
                    {"sku": "ITEM-001", "quantity": 2, "price": 10000}
                ]
            }
        }

        hash_1 = HashHelpers.generate_cart_mandate_hash(cart_mandate)
        hash_2 = HashHelpers.generate_cart_mandate_hash(cart_mandate)
        hash_3 = HashHelpers.generate_cart_mandate_hash(cart_mandate)

        # All hashes should be identical (deterministic)
        assert hash_1 == hash_2 == hash_3

    def test_generate_payment_mandate_hash(self):
        """Test payment mandate hash generation"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "10000", "currency": "JPY"}
                },
                "payment_response": {
                    "payer_id": "user_001"
                }
            }
        }

        payment_hash = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        assert isinstance(payment_hash, str)
        assert len(payment_hash) == 64  # SHA256 hex
        # Should be deterministic
        assert payment_hash == HashHelpers.generate_payment_mandate_hash(payment_mandate)

    def test_generate_payment_mandate_hash_excludes_user_authorization(self):
        """Test that user_authorization field is excluded from payment hash"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_mandate = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "5000", "currency": "JPY"}
                }
            }
        }

        hash_before = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        # Add user_authorization (should be excluded)
        payment_mandate["user_authorization"] = {
            "transaction_data": ["cart_hash", "payment_hash"]
        }

        hash_after = HashHelpers.generate_payment_mandate_hash(payment_mandate)

        # Hash should be the same (user_authorization excluded)
        assert hash_before == hash_after

    def test_cart_hash_changes_with_content(self):
        """Test that cart hash changes when content changes"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        cart_mandate_1 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-001", "price": 10000}]
            }
        }

        cart_mandate_2 = {
            "contents": {
                "id": "cart_123",
                "items": [{"sku": "ITEM-002", "price": 20000}]  # Different item
            }
        }

        hash_1 = HashHelpers.generate_cart_mandate_hash(cart_mandate_1)
        hash_2 = HashHelpers.generate_cart_mandate_hash(cart_mandate_2)

        # Hashes should be different
        assert hash_1 != hash_2

    def test_payment_hash_changes_with_amount(self):
        """Test that payment hash changes when amount changes"""
        from services.shopping_agent.utils.hash_helpers import HashHelpers

        payment_1 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "10000", "currency": "JPY"}
                }
            }
        }

        payment_2 = {
            "payment_mandate_contents": {
                "payment_details_total": {
                    "amount": {"value": "20000", "currency": "JPY"}  # Different amount
                }
            }
        }

        hash_1 = HashHelpers.generate_payment_mandate_hash(payment_1)
        hash_2 = HashHelpers.generate_payment_mandate_hash(payment_2)

        # Hashes should be different
        assert hash_1 != hash_2


# ============================================================================
# Merchant Utils Helpers Tests - Improve Coverage
# ============================================================================


class TestInventoryHelpers:
    """Test merchant inventory helpers"""

    @pytest.mark.asyncio
    async def test_init(self, db_manager):
        """Test InventoryHelpers initialization"""
        from services.merchant.utils.inventory_helpers import InventoryHelpers

        inventory_helpers = InventoryHelpers(db_manager)
        assert inventory_helpers.db_manager is db_manager

    @pytest.mark.asyncio
    async def test_check_inventory_success(self, db_manager):
        """Test successful inventory check"""
        from services.merchant.utils.inventory_helpers import InventoryHelpers
        from common.database import ProductCRUD

        # Create a test product
        async with db_manager.get_session() as session:
            product = await ProductCRUD.create(session, {
                "sku": "TEST-INV-001",
                "name": "Test Product",
                "description": "Test",
                "price": 10000,
                "inventory_count": 100,
                "image_url": "/test.png",
                "metadata": {"category": "Test"}
            })

        inventory_helpers = InventoryHelpers(db_manager)

        cart_mandate = {
            "contents": {
                "id": "cart_test_001"
            },
            "_metadata": {
                "raw_items": [
                    {"sku": "TEST-INV-001", "quantity": 5}
                ]
            }
        }

        # Should not raise
        await inventory_helpers.check_inventory(cart_mandate)

    @pytest.mark.asyncio
    async def test_check_inventory_insufficient(self, db_manager):
        """Test inventory check fails when insufficient stock"""
        from services.merchant.utils.inventory_helpers import InventoryHelpers
        from common.database import ProductCRUD

        # Create a test product with limited inventory
        async with db_manager.get_session() as session:
            product = await ProductCRUD.create(session, {
                "sku": "TEST-INV-002",
                "name": "Test Product",
                "description": "Test",
                "price": 10000,
                "inventory_count": 5,  # Only 5 available
                "image_url": "/test.png",
                "metadata": {"category": "Test"}
            })

        inventory_helpers = InventoryHelpers(db_manager)

        cart_mandate = {
            "contents": {
                "id": "cart_test_002"
            },
            "_metadata": {
                "raw_items": [
                    {"sku": "TEST-INV-002", "quantity": 10}  # Requesting 10
                ]
            }
        }

        with pytest.raises(ValueError, match="Insufficient inventory"):
            await inventory_helpers.check_inventory(cart_mandate)

    @pytest.mark.asyncio
    async def test_check_inventory_product_not_found(self, db_manager):
        """Test inventory check fails when product not found"""
        from services.merchant.utils.inventory_helpers import InventoryHelpers

        inventory_helpers = InventoryHelpers(db_manager)

        cart_mandate = {
            "contents": {
                "id": "cart_test_003"
            },
            "_metadata": {
                "raw_items": [
                    {"sku": "NONEXISTENT-SKU", "quantity": 1}
                ]
            }
        }

        with pytest.raises(ValueError, match="Product not found"):
            await inventory_helpers.check_inventory(cart_mandate)

    @pytest.mark.asyncio
    async def test_check_inventory_missing_metadata(self, db_manager):
        """Test inventory check fails when raw_items missing"""
        from services.merchant.utils.inventory_helpers import InventoryHelpers

        inventory_helpers = InventoryHelpers(db_manager)

        cart_mandate = {
            "contents": {
                "id": "cart_test_004"
            },
            "_metadata": {}  # No raw_items
        }

        with pytest.raises(ValueError, match="missing required _metadata.raw_items"):
            await inventory_helpers.check_inventory(cart_mandate)


class TestJWTHelpers:
    """Test merchant JWT helpers"""

    def test_init(self):
        """Test JWTHelpers initialization"""
        from services.merchant.utils.jwt_helpers import JWTHelpers

        mock_key_manager = MagicMock()
        jwt_helpers = JWTHelpers(mock_key_manager)
        assert jwt_helpers.key_manager is mock_key_manager

    def test_build_jwt_header(self):
        """Test JWT header construction"""
        from services.merchant.utils.jwt_helpers import JWTHelpers

        merchant_id = "did:ap2:merchant:test"
        header = JWTHelpers.build_jwt_header(merchant_id)

        assert header["alg"] == "ES256"
        assert header["kid"] == "did:ap2:merchant:test#key-1"
        assert header["typ"] == "JWT"

    def test_build_merchant_jwt_payload(self):
        """Test JWT payload construction"""
        from services.merchant.utils.jwt_helpers import JWTHelpers

        merchant_id = "did:ap2:merchant:test"
        cart_hash = "a" * 64  # 64 char hex hash

        payload = JWTHelpers.build_merchant_jwt_payload(merchant_id, cart_hash)

        assert payload["iss"] == merchant_id
        assert payload["sub"] == merchant_id
        assert payload["aud"] == "did:ap2:agent:payment_processor"
        assert payload["cart_hash"] == cart_hash
        assert "iat" in payload
        assert "exp" in payload
        assert "jti" in payload

    def test_base64url_encode_jwt_part(self):
        """Test Base64URL encoding of JWT part"""
        from services.merchant.utils.jwt_helpers import JWTHelpers

        data = {"test": "value", "number": 123}
        encoded = JWTHelpers.base64url_encode_jwt_part(data)

        assert isinstance(encoded, str)
        # Should not have padding
        assert not encoded.endswith('=')
        # Should be URL-safe
        assert '+' not in encoded
        assert '/' not in encoded

    def test_sign_jwt_message(self):
        """Test JWT message signing"""
        from services.merchant.utils.jwt_helpers import JWTHelpers
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        # Create mock key manager with real EC key
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        mock_key_manager = MagicMock()
        mock_key_manager.get_private_key.return_value = private_key

        jwt_helpers = JWTHelpers(mock_key_manager)

        message = "test.message"
        signature = jwt_helpers.sign_jwt_message(message, "test_key_id")

        assert isinstance(signature, str)
        # ES256 produces 64-byte signature (32 bytes R + 32 bytes S)
        # Base64URL encoded should be ~86 characters
        assert len(signature) > 80

    def test_sign_jwt_message_key_not_found(self):
        """Test JWT signing fails when key not found"""
        from services.merchant.utils.jwt_helpers import JWTHelpers

        mock_key_manager = MagicMock()
        mock_key_manager.get_private_key.return_value = None

        jwt_helpers = JWTHelpers(mock_key_manager)

        with pytest.raises(ValueError, match="private key not found"):
            jwt_helpers.sign_jwt_message("test.message", "missing_key")

    def test_generate_merchant_authorization_jwt(self):
        """Test full merchant authorization JWT generation"""
        from services.merchant.utils.jwt_helpers import JWTHelpers
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.backends import default_backend

        # Create real EC key
        private_key = ec.generate_private_key(ec.SECP256R1(), default_backend())
        mock_key_manager = MagicMock()
        mock_key_manager.get_private_key.return_value = private_key

        jwt_helpers = JWTHelpers(mock_key_manager)

        cart_hash = "a" * 64
        merchant_id = "did:ap2:merchant:test"

        jwt_token = jwt_helpers.generate_merchant_authorization_jwt(cart_hash, merchant_id)

        # JWT should have 3 parts separated by dots
        parts = jwt_token.split('.')
        assert len(parts) == 3

        # Verify header
        header_json = base64.urlsafe_b64decode(parts[0] + '==').decode('utf-8')
        header = json.loads(header_json)
        assert header["alg"] == "ES256"

        # Verify payload
        payload_json = base64.urlsafe_b64decode(parts[1] + '==').decode('utf-8')
        payload = json.loads(payload_json)
        assert payload["cart_hash"] == cart_hash
        assert payload["iss"] == merchant_id


# ============================================================================
# Shopping Agent Utils Helpers Tests - Improve Coverage
# ============================================================================


class TestA2AHelpers:
    """Test shopping agent A2A helpers"""

    @pytest.mark.asyncio
    async def test_init(self):
        """Test A2AHelpers initialization"""
        from services.shopping_agent.utils.a2a_helpers import A2AHelpers

        mock_a2a_handler = MagicMock()
        mock_http_client = MagicMock()
        mock_tracer = MagicMock()

        helpers = A2AHelpers(
            a2a_handler=mock_a2a_handler,
            http_client=mock_http_client,
            merchant_agent_url="http://merchant:8001",
            tracer=mock_tracer,
            a2a_timeout=300.0
        )

        assert helpers.a2a_handler is mock_a2a_handler
        assert helpers.http_client is mock_http_client
        assert helpers.merchant_agent_url == "http://merchant:8001"
        assert helpers.tracer is mock_tracer
        assert helpers.a2a_timeout == 300.0

    @pytest.mark.asyncio
    async def test_send_cart_request_via_a2a_success(self):
        """Test successful A2A cart request"""
        from services.shopping_agent.utils.a2a_helpers import A2AHelpers

        # Create mocks
        mock_a2a_handler = MagicMock()
        mock_message = MagicMock()
        mock_message.header.message_id = "msg_123"
        mock_message.dataPart.type = "ap2.requests.CartRequest"
        mock_message.model_dump.return_value = {"test": "data"}
        mock_a2a_handler.create_response_message.return_value = mock_message

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "success"}

        mock_http_client = MagicMock()
        mock_http_client.post = AsyncMock(return_value=mock_response)

        mock_tracer = MagicMock()

        helpers = A2AHelpers(
            a2a_handler=mock_a2a_handler,
            http_client=mock_http_client,
            merchant_agent_url="http://merchant:8001",
            tracer=mock_tracer
        )

        cart_request = {
            "intent_mandate_id": "intent_123",
            "items": [{"product_id": "prod_001", "quantity": 1}]
        }

        # Mock the span context manager
        mock_span = MagicMock()
        mock_span.__enter__ = MagicMock(return_value=mock_span)
        mock_span.__exit__ = MagicMock(return_value=False)

        with patch('common.telemetry.create_http_span', return_value=mock_span):
            result = await helpers.send_cart_request_via_a2a(cart_request)

        assert result == {"status": "success"}
        mock_a2a_handler.create_response_message.assert_called_once()
        mock_http_client.post.assert_called_once()


class TestCartHelpers:
    """Test shopping agent cart helpers"""

    def test_init(self):
        """Test CartHelpers initialization"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        mock_signature_manager = MagicMock()
        helpers = CartHelpers(mock_signature_manager)
        assert helpers.signature_manager is mock_signature_manager

    def test_create_cart_mandate(self):
        """Test cart mandate creation"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        product = {
            "id": "prod_001",
            "sku": "TEST-SKU-001",
            "name": "Test Product",
            "price": 10000
        }

        session = {
            "intent_mandate": {"id": "intent_123"}
        }

        cart_mandate = CartHelpers.create_cart_mandate(product, session)

        assert cart_mandate["type"] == "CartMandate"
        assert cart_mandate["version"] == "0.2"
        assert cart_mandate["intent_mandate_id"] == "intent_123"
        assert len(cart_mandate["items"]) == 1
        assert cart_mandate["items"][0]["sku"] == "TEST-SKU-001"
        assert cart_mandate["items"][0]["quantity"] == 1
        assert "id" in cart_mandate
        assert "created_at" in cart_mandate

    def test_build_cart_request(self):
        """Test cart request building"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        selected_product = {
            "id": "prod_001",
            "sku": "TEST-SKU",
            "name": "Test"
        }

        session = {
            "intent_mandate": {"id": "intent_123"},
            "intent_message_id": "msg_456"
        }

        cart_request = CartHelpers.build_cart_request(selected_product, session)

        assert cart_request["intent_mandate_id"] == "intent_123"
        assert cart_request["intent_message_id"] == "msg_456"
        assert len(cart_request["items"]) == 1
        assert cart_request["items"][0]["product_id"] == "prod_001"
        assert "shipping_address" in cart_request

    @pytest.mark.asyncio
    async def test_extract_cart_mandate_from_artifact(self):
        """Test extracting CartMandate from A2A artifact response"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        result = {
            "dataPart": {
                "kind": "artifact",
                "artifact": {
                    "name": "Test Artifact",
                    "artifactId": "art_123",
                    "parts": [
                        {
                            "kind": "data",
                            "data": {
                                "CartMandate": {
                                    "id": "cart_123",
                                    "contents": {}
                                }
                            }
                        }
                    ]
                }
            }
        }

        cart_mandate = await CartHelpers.extract_cart_mandate_from_a2a_response(result)

        assert cart_mandate is not None
        assert cart_mandate["id"] == "cart_123"

    @pytest.mark.asyncio
    async def test_extract_cart_mandate_from_legacy_format(self):
        """Test extracting CartMandate from legacy A2A response"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        result = {
            "dataPart": {
                "type": "ap2.mandates.CartMandate",
                "payload": {
                    "id": "cart_456",
                    "contents": {}
                }
            }
        }

        cart_mandate = await CartHelpers.extract_cart_mandate_from_a2a_response(result)

        assert cart_mandate is not None
        assert cart_mandate["id"] == "cart_456"

    @pytest.mark.asyncio
    async def test_extract_cart_mandate_error_response(self):
        """Test error handling for error response"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        result = {
            "dataPart": {
                "type": "ap2.errors.Error",
                "payload": {
                    "error_message": "Test error"
                }
            }
        }

        with pytest.raises(ValueError, match="Test error"):
            await CartHelpers.extract_cart_mandate_from_a2a_response(result)

    @pytest.mark.asyncio
    async def test_extract_cart_mandate_invalid_response(self):
        """Test invalid response format"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        result = {}

        with pytest.raises(ValueError, match="Invalid response format"):
            await CartHelpers.extract_cart_mandate_from_a2a_response(result)

    def test_verify_merchant_cart_signature_missing_authorization(self):
        """Test signature verification fails when merchant_authorization missing"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        mock_signature_manager = MagicMock()
        helpers = CartHelpers(mock_signature_manager)

        signed_cart_mandate = {
            "contents": {}
            # No merchant_authorization
        }

        with pytest.raises(ValueError, match="does not contain merchant_authorization"):
            helpers.verify_merchant_cart_signature(signed_cart_mandate)

    def test_verify_merchant_cart_signature_missing_contents(self):
        """Test signature verification fails when contents missing"""
        from services.shopping_agent.utils.cart_helpers import CartHelpers

        mock_signature_manager = MagicMock()
        helpers = CartHelpers(mock_signature_manager)

        signed_cart_mandate = {
            "merchant_authorization": "jwt_token"
            # No contents
        }

        with pytest.raises(ValueError, match="does not contain contents"):
            helpers.verify_merchant_cart_signature(signed_cart_mandate)


class TestPaymentHelpers:
    """Test shopping agent payment helpers"""

    def test_init(self):
        """Test PaymentHelpers initialization"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        mock_risk_engine = MagicMock()
        helpers = PaymentHelpers(mock_risk_engine)
        assert helpers.risk_engine is mock_risk_engine

    def test_validate_cart_and_payment_method_success(self):
        """Test successful validation"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        session = {
            "cart_mandate": {"id": "cart_123"},
            "tokenized_payment_method": {"token": "tok_xyz"}
        }

        cart_mandate, tokenized_payment_method = PaymentHelpers.validate_cart_and_payment_method(session)

        assert cart_mandate["id"] == "cart_123"
        assert tokenized_payment_method["token"] == "tok_xyz"

    def test_validate_cart_and_payment_method_no_cart(self):
        """Test validation fails when cart_mandate missing"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        session = {
            "tokenized_payment_method": {"token": "tok_xyz"}
        }

        with pytest.raises(ValueError, match="No cart mandate available"):
            PaymentHelpers.validate_cart_and_payment_method(session)

    def test_validate_cart_and_payment_method_no_payment(self):
        """Test validation fails when payment_method missing"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        session = {
            "cart_mandate": {"id": "cart_123"}
        }

        with pytest.raises(ValueError, match="No tokenized payment method available"):
            PaymentHelpers.validate_cart_and_payment_method(session)

    def test_extract_payment_amount_from_cart(self):
        """Test extracting payment amount from cart"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        cart_mandate = {
            "contents": {
                "payment_request": {
                    "details": {
                        "total": {
                            "amount": {
                                "value": "10000.00",
                                "currency": "JPY"
                            }
                        }
                    }
                }
            }
        }

        amount = PaymentHelpers.extract_payment_amount_from_cart(cart_mandate)

        assert amount["value"] == "10000.00"
        assert amount["currency"] == "JPY"

    def test_build_payment_response(self):
        """Test building payment response"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        tokenized_payment_method = {
            "brand": "visa",
            "token": "tok_test_123"
        }

        payment_response = PaymentHelpers.build_payment_response(tokenized_payment_method)

        assert payment_response["methodName"] == "https://a2a-protocol.org/payment-methods/ap2-payment"
        assert payment_response["details"]["cardBrand"] == "visa"
        assert payment_response["details"]["token"] == "tok_test_123"
        assert payment_response["details"]["tokenized"] is True

    def test_build_payment_mandate_contents(self):
        """Test building payment mandate contents"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        cart_mandate = {
            "id": "cart_123",
            "merchant_id": "merchant_001"
        }

        total_amount = {
            "value": "10000.00",
            "currency": "JPY"
        }

        payment_response = {
            "methodName": "test"
        }

        payment_mandate_id, payment_mandate_contents = PaymentHelpers.build_payment_mandate_contents(
            cart_mandate, total_amount, payment_response
        )

        assert payment_mandate_id.startswith("payment_")
        assert payment_mandate_contents["payment_mandate_id"] == payment_mandate_id
        assert payment_mandate_contents["payment_details_id"] == "cart_123"
        assert payment_mandate_contents["payment_details_total"]["amount"]["value"] == "10000.00"
        assert payment_mandate_contents["merchant_agent"] == "merchant_001"

    def test_generate_user_authorization_for_payment_no_assertion(self):
        """Test user authorization generation returns None when no assertion"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        session = {}
        cart_mandate = {}
        payment_mandate_contents = {}
        public_key_cose = "test_key"

        result = PaymentHelpers.generate_user_authorization_for_payment(
            session, cart_mandate, payment_mandate_contents, public_key_cose
        )

        assert result is None

    def test_perform_risk_assessment_success(self):
        """Test successful risk assessment"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        mock_risk_engine = MagicMock()
        mock_risk_result = MagicMock()
        mock_risk_result.risk_score = 25
        mock_risk_result.recommendation = "approve"
        mock_risk_result.fraud_indicators = []
        mock_risk_engine.assess_payment_mandate.return_value = mock_risk_result

        helpers = PaymentHelpers(mock_risk_engine)

        payment_mandate = {"id": "pm_123"}
        cart_mandate = {"id": "cart_123"}
        intent_mandate = {"id": "intent_123"}

        risk_score, fraud_indicators = helpers.perform_risk_assessment(
            payment_mandate, cart_mandate, intent_mandate
        )

        assert risk_score == 25
        assert fraud_indicators == []

    def test_perform_risk_assessment_high_risk(self):
        """Test high risk assessment"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        mock_risk_engine = MagicMock()
        mock_risk_result = MagicMock()
        mock_risk_result.risk_score = 85
        mock_risk_result.recommendation = "decline"
        mock_risk_result.fraud_indicators = ["high_amount"]
        mock_risk_engine.assess_payment_mandate.return_value = mock_risk_result

        helpers = PaymentHelpers(mock_risk_engine)

        payment_mandate = {"id": "pm_123"}
        cart_mandate = {"id": "cart_123"}
        intent_mandate = {"id": "intent_123"}

        risk_score, fraud_indicators = helpers.perform_risk_assessment(
            payment_mandate, cart_mandate, intent_mandate
        )

        assert risk_score == 85
        assert fraud_indicators == ["high_amount"]

    def test_perform_risk_assessment_failure(self):
        """Test risk assessment handles failure gracefully"""
        from services.shopping_agent.utils.payment_helpers import PaymentHelpers

        mock_risk_engine = MagicMock()
        mock_risk_engine.assess_payment_mandate.side_effect = Exception("Risk engine error")

        helpers = PaymentHelpers(mock_risk_engine)

        payment_mandate = {"id": "pm_123"}
        cart_mandate = {"id": "cart_123"}
        intent_mandate = {"id": "intent_123"}

        risk_score, fraud_indicators = helpers.perform_risk_assessment(
            payment_mandate, cart_mandate, intent_mandate
        )

        # Should return default medium risk
        assert risk_score == 50
        assert "risk_assessment_failed" in fraud_indicators


# ============================================================================
# Credential Provider Utils Helpers Tests - New Coverage
# ============================================================================


class TestPasskeyHelpers:
    """Test credential provider passkey helpers"""

    def test_init(self):
        """Test PasskeyHelpers initialization"""
        from services.credential_provider.utils.passkey_helpers import PasskeyHelpers

        mock_db_manager = MagicMock()
        mock_key_manager = MagicMock()
        mock_attestation_manager = MagicMock()
        mock_challenge_store = MagicMock()

        helpers = PasskeyHelpers(
            db_manager=mock_db_manager,
            key_manager=mock_key_manager,
            attestation_manager=mock_attestation_manager,
            challenge_store=mock_challenge_store
        )

        assert helpers.db_manager is mock_db_manager
        assert helpers.key_manager is mock_key_manager
        assert helpers.attestation_manager is mock_attestation_manager
        assert helpers.challenge_store is mock_challenge_store


class TestPaymentMethodHelpers:
    """Test credential provider payment method helpers"""

    def test_init(self):
        """Test PaymentMethodHelpers initialization"""
        from services.credential_provider.utils.payment_method_helpers import PaymentMethodHelpers

        mock_db_manager = MagicMock()
        mock_token_store = MagicMock()

        helpers = PaymentMethodHelpers(
            db_manager=mock_db_manager,
            token_store=mock_token_store
        )

        assert helpers.db_manager is mock_db_manager
        assert helpers.token_store is mock_token_store


class TestStepUpHelpers:
    """Test credential provider step-up helpers"""

    def test_init(self):
        """Test StepUpHelpers initialization"""
        from services.credential_provider.utils.stepup_helpers import StepUpHelpers

        mock_db_manager = MagicMock()
        mock_session_store = MagicMock()
        mock_challenge_store = MagicMock()
        payment_network_url = "http://payment_network:8005"

        helpers = StepUpHelpers(
            db_manager=mock_db_manager,
            session_store=mock_session_store,
            challenge_store=mock_challenge_store,
            payment_network_url=payment_network_url
        )

        assert helpers.db_manager is mock_db_manager
        assert helpers.session_store is mock_session_store
        assert helpers.challenge_store is mock_challenge_store
        assert helpers.payment_network_url == payment_network_url


class TestReceiptHelpers:
    """Test credential provider receipt helpers"""

    @pytest.mark.asyncio
    async def test_init(self):
        """Test ReceiptHelpers initialization"""
        from services.credential_provider.utils.receipt_helpers import ReceiptHelpers

        mock_db_manager = MagicMock()

        helpers = ReceiptHelpers(db_manager=mock_db_manager)

        assert helpers.db_manager is mock_db_manager

    @pytest.mark.asyncio
    async def test_receive_receipt_success(self, db_manager):
        """Test successful receipt reception"""
        from services.credential_provider.utils.receipt_helpers import ReceiptHelpers

        helpers = ReceiptHelpers(db_manager=db_manager)

        receipt_data = {
            "transaction_id": "txn_123",
            "receipt_url": "http://example.com/receipt/123",
            "payer_id": "user_001",
            "amount": {"value": "10000", "currency": "JPY"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        result = await helpers.receive_receipt(receipt_data)

        assert result["status"] == "received"
        assert result["transaction_id"] == "txn_123"

    @pytest.mark.asyncio
    async def test_receive_receipt_missing_fields(self, db_manager):
        """Test receipt reception fails with missing fields"""
        from services.credential_provider.utils.receipt_helpers import ReceiptHelpers
        from fastapi import HTTPException

        helpers = ReceiptHelpers(db_manager=db_manager)

        receipt_data = {
            "transaction_id": "txn_123"
            # Missing receipt_url and payer_id
        }

        with pytest.raises(HTTPException) as exc_info:
            await helpers.receive_receipt(receipt_data)

        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_receipts(self, db_manager):
        """Test getting user receipts"""
        from services.credential_provider.utils.receipt_helpers import ReceiptHelpers

        helpers = ReceiptHelpers(db_manager=db_manager)

        # First, add a receipt
        receipt_data = {
            "transaction_id": "txn_456",
            "receipt_url": "http://example.com/receipt/456",
            "payer_id": "user_002",
            "amount": {"value": "5000", "currency": "JPY"},
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        await helpers.receive_receipt(receipt_data)

        # Now get receipts
        result = await helpers.get_receipts("user_002")

        assert result["user_id"] == "user_002"
        assert "receipts" in result
        assert result["total_count"] >= 1


class TestTokenHelpers:
    """Test credential provider token helpers"""

    def test_init(self):
        """Test TokenHelpers initialization"""
        from services.credential_provider.utils.token_helpers import TokenHelpers

        mock_db_manager = MagicMock()

        helpers = TokenHelpers(db_manager=mock_db_manager)

        assert helpers.db_manager is mock_db_manager

    def test_generate_token(self):
        """Test token generation"""
        from services.credential_provider.utils.token_helpers import TokenHelpers

        payment_mandate = {
            "payer_id": "user_001",
            "id": "pm_123"
        }

        attestation = {
            "verified": True
        }

        token = TokenHelpers.generate_token(payment_mandate, attestation)

        assert isinstance(token, str)
        assert token.startswith("cred_token_")
        assert len(token) > 20  # Should be reasonably long

    @pytest.mark.asyncio
    async def test_save_attestation(self, db_manager):
        """Test saving attestation to database"""
        from services.credential_provider.utils.token_helpers import TokenHelpers

        helpers = TokenHelpers(db_manager=db_manager)

        attestation_raw = {
            "type": "webauthn",
            "credential_id": "cred_123"
        }

        token = "cred_token_test"
        agent_token = "agent_token_test"

        # Should not raise
        await helpers.save_attestation(
            user_id="user_001",
            attestation_raw=attestation_raw,
            verified=True,
            token=token,
            agent_token=agent_token
        )

    @pytest.mark.asyncio
    async def test_save_attestation_failed(self, db_manager):
        """Test saving failed attestation"""
        from services.credential_provider.utils.token_helpers import TokenHelpers

        helpers = TokenHelpers(db_manager=db_manager)

        attestation_raw = {
            "type": "webauthn",
            "credential_id": "cred_failed"
        }

        # Should not raise even when verified=False
        await helpers.save_attestation(
            user_id="user_001",
            attestation_raw=attestation_raw,
            verified=False
        )
