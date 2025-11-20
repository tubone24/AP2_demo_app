"""
Tests for Merchant Agent Handlers

Tests cover:
- cart_handler.py: Cart selection and cart requests
- intent_handler.py: Intent mandate processing
- payment_handler.py: Payment request forwarding
- product_handler.py: Product search
"""

import pytest
import uuid
from datetime import datetime, timezone
from unittest.mock import Mock, patch, AsyncMock
from common.models import A2AMessage, A2AMessageHeader, A2ADataPart


# ============================================
# Cart Handler Tests
# ============================================

class TestCartHandler:
    """Test cart handler functions"""

    @pytest.mark.asyncio
    async def test_handle_cart_selection_success(self):
        """Test successful cart selection handling"""
        from services.merchant_agent.handlers import cart_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock HTTP response
        mock_http_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "signed_cart_mandate": {
                "contents": {"id": "cart_001"}
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        # Create message
        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.requests.CartRequest",
                id="selection_001",
                payload={
                    "selected_cart_id": "cart_001",
                    "cart_mandate": {
                        "contents": {"id": "cart_001"}
                    },
                    "user_id": "user_001"
                }
            )
        )

        result = await cart_handler.handle_cart_selection(mock_agent, message)

        assert result["type"] == "ap2.responses.SignedCartMandate"
        assert result["payload"]["cart_id"] == "cart_001"

    @pytest.mark.asyncio
    async def test_handle_cart_selection_missing_mandate(self):
        """Test cart selection with missing cart mandate"""
        from services.merchant_agent.handlers import cart_handler

        mock_agent = Mock()

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.requests.CartRequest",
                id="selection_001",
                payload={
                    "selected_cart_id": "cart_001",
                    "user_id": "user_001"
                    # Missing cart_mandate
                }
            )
        )

        result = await cart_handler.handle_cart_selection(mock_agent, message)

        assert result["type"] == "ap2.errors.Error"
        assert result["payload"]["error_code"] == "invalid_cart_selection"

    @pytest.mark.asyncio
    async def test_handle_cart_request_success(self):
        """Test successful cart request handling"""
        from services.merchant_agent.handlers import cart_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock cart creation
        mock_create_cart = AsyncMock(return_value={
            "id": "cart_001",
            "type": "CartMandate"
        })
        mock_agent._create_cart_mandate = mock_create_cart

        # Mock HTTP response for signature
        mock_http_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "signed_cart_mandate": {
                "contents": {"id": "cart_001"}
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        # Create message
        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.requests.CartRequest",
                id="request_001",
                payload={
                    "intent_mandate_id": "intent_001",
                    "items": []
                }
            )
        )

        result = await cart_handler.handle_cart_request(mock_agent, message)

        # The handler returns a dict, check for artifact marker
        assert "is_artifact" in result or "type" in result


# ============================================
# Intent Handler Tests
# ============================================

class TestIntentHandler:
    """Test intent handler functions"""

    @pytest.mark.asyncio
    async def test_handle_intent_mandate_success(self):
        """Test successful intent mandate handling"""
        from services.merchant_agent.handlers import intent_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"
        mock_agent.ai_mode_enabled = False  # Use rule-based

        # Mock cart creation
        mock_create_carts = AsyncMock(return_value=[
            {
                "artifactId": "artifact_001",
                "name": "Cart 1",
                "parts": []
            }
        ])
        mock_agent._create_multiple_cart_candidates = mock_create_carts

        # Create message
        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.IntentMandate",
                id="intent_001",
                payload={
                    "intent_mandate": {
                        "id": "intent_001",
                        "natural_language_description": "running shoes",
                        "user_id": "user_001"
                    },
                    "shipping_address": {
                        "recipient": "Test User",
                        "street": "123 Test St"
                    }
                }
            )
        )

        result = await intent_handler.handle_intent_mandate(mock_agent, message)

        assert result["type"] == "ap2.responses.CartCandidates"
        assert "cart_candidates" in result["payload"]

    @pytest.mark.asyncio
    async def test_handle_intent_mandate_invalid_payload(self):
        """Test intent mandate with invalid payload"""
        from services.merchant_agent.handlers import intent_handler

        mock_agent = Mock()

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.IntentMandate",
                id="intent_001",
                payload={}  # Missing intent_mandate
            )
        )

        result = await intent_handler.handle_intent_mandate(mock_agent, message)

        assert result["type"] == "ap2.errors.Error"
        assert result["payload"]["error_code"] == "invalid_payload_format"

    @pytest.mark.asyncio
    async def test_handle_intent_mandate_missing_shipping_address(self):
        """Test intent mandate without shipping address"""
        from services.merchant_agent.handlers import intent_handler

        mock_agent = Mock()

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.IntentMandate",
                id="intent_001",
                payload={
                    "intent_mandate": {
                        "id": "intent_001",
                        "natural_language_description": "running shoes"
                    }
                    # Missing shipping_address
                }
            )
        )

        result = await intent_handler.handle_intent_mandate(mock_agent, message)

        assert result["type"] == "ap2.errors.Error"
        assert result["payload"]["error_code"] == "missing_shipping_address"

    @pytest.mark.asyncio
    async def test_handle_intent_mandate_ai_mode(self):
        """Test intent mandate with AI mode enabled"""
        from services.merchant_agent.handlers import intent_handler

        # Mock agent with AI mode
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"
        mock_agent.ai_mode_enabled = True

        # Mock LangGraph agent
        mock_langgraph = AsyncMock()
        mock_langgraph.create_cart_candidates = AsyncMock(return_value=[
            {
                "artifactId": "artifact_ai_001",
                "name": "AI Cart",
                "parts": []
            }
        ])
        mock_agent.langgraph_agent = mock_langgraph

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.IntentMandate",
                id="intent_001",
                payload={
                    "intent_mandate": {
                        "id": "intent_001",
                        "natural_language_description": "running shoes",
                        "user_id": "user_001"
                    },
                    "shipping_address": {"recipient": "Test User"}
                }
            )
        )

        result = await intent_handler.handle_intent_mandate(mock_agent, message)

        assert result["type"] == "ap2.responses.CartCandidates"
        # Verify LangGraph was called
        mock_langgraph.create_cart_candidates.assert_called_once()


# ============================================
# Payment Handler Tests
# ============================================

class TestPaymentHandler:
    """Test payment handler functions"""

    @pytest.mark.asyncio
    async def test_handle_payment_request_success(self):
        """Test successful payment request handling"""
        from services.merchant_agent.handlers import payment_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.payment_processor_url = "http://payment_processor:8004"

        # Mock A2A handler
        mock_a2a_handler = Mock()
        mock_forward_message = Mock()
        mock_forward_message.model_dump.return_value = {
            "header": {},
            "dataPart": {}
        }
        mock_a2a_handler.create_response_message.return_value = mock_forward_message
        mock_agent.a2a_handler = mock_a2a_handler

        # Mock HTTP response from payment processor
        mock_http_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "dataPart": {
                "@type": "ap2.responses.PaymentResult",
                "id": "result_001",
                "payload": {
                    "status": "captured",
                    "transaction_id": "txn_001"
                }
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        # Create message
        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.PaymentMandate",
                id="payment_001",
                payload={
                    "payment_mandate": {
                        "id": "pm_001"
                    },
                    "cart_mandate": {
                        "contents": {"id": "cart_001"}
                    }
                }
            )
        )

        result = await payment_handler.handle_payment_request(mock_agent, message)

        assert result["type"] == "ap2.responses.PaymentResult"
        assert result["payload"]["status"] == "captured"

    @pytest.mark.asyncio
    async def test_handle_payment_request_missing_mandate(self):
        """Test payment request with missing payment mandate"""
        from services.merchant_agent.handlers import payment_handler

        mock_agent = Mock()

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.PaymentMandate",
                id="payment_001",
                payload={}  # Missing payment_mandate
            )
        )

        result = await payment_handler.handle_payment_request(mock_agent, message)

        assert result["type"] == "ap2.errors.Error"
        assert result["payload"]["error_code"] == "missing_payment_mandate"

    @pytest.mark.asyncio
    async def test_handle_payment_request_processor_error(self):
        """Test payment request with processor error"""
        from services.merchant_agent.handlers import payment_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.payment_processor_url = "http://payment_processor:8004"

        # Mock A2A handler
        mock_a2a_handler = Mock()
        mock_forward_message = Mock()
        mock_forward_message.model_dump.return_value = {}
        mock_a2a_handler.create_response_message.return_value = mock_forward_message
        mock_agent.a2a_handler = mock_a2a_handler

        # Mock HTTP response with error
        mock_http_client = AsyncMock()
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "dataPart": {
                "@type": "ap2.errors.Error",
                "id": "error_001",
                "payload": {
                    "error_code": "payment_failed",
                    "error_message": "Insufficient funds"
                }
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.mandates.PaymentMandate",
                id="payment_001",
                payload={
                    "payment_mandate": {"id": "pm_001"},
                    "cart_mandate": {"contents": {"id": "cart_001"}}
                }
            )
        )

        result = await payment_handler.handle_payment_request(mock_agent, message)

        assert result["type"] == "ap2.errors.Error"
        assert result["payload"]["error_code"] == "payment_request_failed"


# ============================================
# Product Handler Tests
# ============================================

class TestProductHandler:
    """Test product handler functions"""

    @pytest.mark.asyncio
    async def test_handle_product_search_traditional_mode(self):
        """Test product search in traditional mode"""
        from services.merchant_agent.handlers import product_handler

        # Mock agent
        mock_agent = Mock()
        mock_agent.ai_mode_enabled = False
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"

        # Mock database and products
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.to_dict.return_value = {
            "id": "product_001",
            "name": "Test Product",
            "price": 1000
        }

        mock_db_manager = AsyncMock()
        def mock_get_session():
            class MockContext:
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    pass
            return MockContext()
        mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.handlers.product_handler.ProductCRUD') as mock_crud:
            mock_crud.search = AsyncMock(return_value=[mock_product])

            message = A2AMessage(
                header=A2AMessageHeader(
                    message_id="msg_001",
                    sender="did:ap2:agent:shopping_agent",
                    recipient="did:ap2:agent:merchant_agent",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    nonce="test_nonce_001"
                ),
                dataPart=A2ADataPart(
                    type="ap2.requests.ProductSearch",
                    id="search_001",
                    payload={
                        "query": "running shoes",
                        "max_results": 10
                    }
                )
            )

            result = await product_handler.handle_product_search_request(mock_agent, message)

            assert result["type"] == "ap2.responses.ProductList"
            assert len(result["payload"]["products"]) == 1

    @pytest.mark.asyncio
    async def test_handle_product_search_ai_mode(self):
        """Test product search in AI mode"""
        from services.merchant_agent.handlers import product_handler

        # Mock agent with AI mode
        mock_agent = Mock()
        mock_agent.ai_mode_enabled = True
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"

        # Mock LangGraph agent
        mock_langgraph = AsyncMock()
        mock_langgraph.create_cart_candidates = AsyncMock(return_value=[
            {
                "artifactId": "artifact_001",
                "name": "AI Cart",
                "parts": []
            }
        ])
        mock_agent.langgraph_agent = mock_langgraph

        message = A2AMessage(
            header=A2AMessageHeader(
                message_id="msg_001",
                sender="did:ap2:agent:shopping_agent",
                recipient="did:ap2:agent:merchant_agent",
                timestamp=datetime.now(timezone.utc).isoformat(),
                nonce="test_nonce_001"
            ),
            dataPart=A2ADataPart(
                type="ap2.requests.ProductSearch",
                id="search_001",
                payload={
                    "intent_mandate": {
                        "id": "intent_001",
                        "natural_language_description": "running shoes"
                    },
                    "user_id": "user_001",
                    "session_id": "session_001"
                }
            )
        )

        result = await product_handler.handle_product_search_request(mock_agent, message)

        assert result["type"] == "ap2.responses.CartCandidates"
        assert "cart_candidates" in result["payload"]

    @pytest.mark.asyncio
    async def test_handle_product_search_ai_mode_fallback(self):
        """Test product search AI mode with fallback to traditional"""
        from services.merchant_agent.handlers import product_handler

        # Mock agent with AI mode
        mock_agent = Mock()
        mock_agent.ai_mode_enabled = True
        mock_agent.merchant_id = "merchant_001"

        # Mock LangGraph agent that fails
        mock_langgraph = AsyncMock()
        mock_langgraph.create_cart_candidates = AsyncMock(
            side_effect=Exception("AI error")
        )
        mock_agent.langgraph_agent = mock_langgraph

        # Mock database for fallback
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.to_dict.return_value = {
            "id": "product_001",
            "name": "Test Product"
        }

        mock_db_manager = AsyncMock()
        def mock_get_session():
            class MockContext:
                async def __aenter__(self):
                    return mock_session
                async def __aexit__(self, *args):
                    pass
            return MockContext()
        mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.handlers.product_handler.ProductCRUD') as mock_crud:
            mock_crud.search = AsyncMock(return_value=[mock_product])

            message = A2AMessage(
                header=A2AMessageHeader(
                    message_id="msg_001",
                    sender="did:ap2:agent:shopping_agent",
                    recipient="did:ap2:agent:merchant_agent",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    nonce="test_nonce_001"
                ),
                dataPart=A2ADataPart(
                    type="ap2.requests.ProductSearch",
                    id="search_001",
                    payload={
                        "intent_mandate": {
                            "id": "intent_001",
                            "natural_language_description": "running shoes"
                        },
                        "query": "running shoes"
                    }
                )
            )

            result = await product_handler.handle_product_search_request(mock_agent, message)

            # Should fall back to ProductList
            assert result["type"] == "ap2.responses.ProductList"
