"""
Tests for Merchant Agent Cart Service (services/cart_service.py)

Tests cover:
- CartMandate creation
- Multiple cart candidates generation
- Cart item building
- Cost calculations
- Merchant signature waiting
"""

import pytest
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock


class TestCreateCartMandate:
    """Test cart mandate creation"""

    @pytest.mark.asyncio
    async def test_create_cart_mandate_success(self):
        """Test successful cart mandate creation"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"

        # Mock database session and products
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.id = "product_001"
        mock_product.name = "Test Product"
        mock_product.description = "Test Description"
        mock_product.price = 10000  # 100.00 JPY in cents
        mock_product.sku = "SKU001"
        mock_product.image_url = "https://example.com/image.jpg"
        mock_product.product_metadata = '{"category": "test", "brand": "TestBrand"}'

        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        # Mock ProductCRUD
        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.get_by_id = AsyncMock(return_value=mock_product)

            cart_request = {
                "intent_mandate_id": "intent_001",
                "items": [
                    {
                        "product_id": "product_001",
                        "quantity": 2
                    }
                ],
                "shipping_address": {
                    "recipient": "Test User",
                    "street": "123 Test St",
                    "city": "Tokyo"
                }
            }

            cart_mandate = await cart_service.create_cart_mandate(
                agent=mock_agent,
                cart_request=cart_request
            )

            # Verify cart mandate structure
            assert cart_mandate["type"] == "CartMandate"
            assert cart_mandate["intent_mandate_id"] == "intent_001"
            assert len(cart_mandate["items"]) == 1
            assert cart_mandate["merchant_id"] == "merchant_001"

            # Verify calculations
            item = cart_mandate["items"][0]
            assert item["quantity"] == 2
            assert float(item["total_price"]["value"]) == 200.0  # 100 * 2

    @pytest.mark.asyncio
    async def test_create_cart_mandate_product_not_found(self):
        """Test cart mandate creation fails when product not found"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_session = AsyncMock()
        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        # Mock ProductCRUD to return None
        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.get_by_id = AsyncMock(return_value=None)

            cart_request = {
                "intent_mandate_id": "intent_001",
                "items": [
                    {
                        "product_id": "nonexistent_product",
                        "quantity": 1
                    }
                ],
                "shipping_address": {}
            }

            with pytest.raises(ValueError, match="Product not found"):
                await cart_service.create_cart_mandate(
                    agent=mock_agent,
                    cart_request=cart_request
                )


class TestCreateMultipleCartCandidates:
    """Test multiple cart candidates generation"""

    @pytest.mark.asyncio
    async def test_create_multiple_cart_candidates_success(self):
        """Test successful generation of multiple cart candidates"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock cart_helpers
        mock_cart_helpers = Mock()
        mock_cart_helpers.build_cart_items_from_products.return_value = (
            [],  # cart_items
            10000  # subtotal_cents
        )
        mock_cart_helpers.calculate_cart_costs.return_value = {
            "tax_cents": 1000,
            "shipping_cost_cents": 50000,
            "total_cents": 61000
        }
        mock_agent.cart_helpers = mock_cart_helpers

        # Mock HTTP client
        mock_http_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "signed_cart_mandate": {
                "contents": {"id": "cart_001"},
                "merchant_authorization": "jwt_signature"
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        # Mock database and products
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.id = "product_001"
        mock_product.name = "Test Product"
        mock_product.price = 5000

        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.search = AsyncMock(return_value=[mock_product] * 5)

            cart_candidates = await cart_service.create_multiple_cart_candidates(
                agent=mock_agent,
                intent_mandate_id="intent_001",
                intent_text="running shoes",
                shipping_address={"recipient": "Test User"}
            )

            # Verify cart candidates were created
            assert len(cart_candidates) >= 1
            assert isinstance(cart_candidates, list)

            # Verify artifact structure
            for artifact in cart_candidates:
                assert "artifactId" in artifact
                assert "name" in artifact
                assert "parts" in artifact

    @pytest.mark.asyncio
    async def test_create_multiple_cart_candidates_no_products(self):
        """Test cart candidates generation with no products found"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_session = AsyncMock()
        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.search = AsyncMock(return_value=[])  # No products

            cart_candidates = await cart_service.create_multiple_cart_candidates(
                agent=mock_agent,
                intent_mandate_id="intent_001",
                intent_text="nonexistent product",
                shipping_address={}
            )

            # Should return empty list
            assert cart_candidates == []


class TestCreateCartFromProducts:
    """Test cart creation from product list"""

    @pytest.mark.asyncio
    async def test_create_cart_from_products_success(self):
        """Test successful cart creation from products"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock cart_helpers
        mock_cart_helpers = Mock()
        mock_cart_helpers.build_cart_items_from_products.return_value = (
            [{
                "name": "Test Product",
                "total_price": {"value": "100.00"}
            }],  # cart_items
            10000  # subtotal_cents
        )
        mock_cart_helpers.calculate_cart_costs.return_value = {
            "tax_cents": 1000,
            "shipping_cost_cents": 50000,
            "total_cents": 61000
        }
        mock_agent.cart_helpers = mock_cart_helpers

        # Mock HTTP client for merchant signature
        mock_http_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "signed_cart_mandate": {
                "contents": {"id": "cart_001"},
                "merchant_authorization": "jwt_signature"
            }
        }
        mock_http_client.post.return_value = mock_response
        mock_agent.http_client = mock_http_client

        # Mock products
        mock_product = Mock()
        products = [mock_product]
        quantities = [1]

        artifact = await cart_service.create_cart_from_products(
            agent=mock_agent,
            intent_mandate_id="intent_001",
            products=products,
            quantities=quantities,
            shipping_address={"recipient": "Test User"},
            cart_name="Test Cart",
            cart_description="Test cart description"
        )

        # Verify artifact structure
        assert artifact is not None
        assert "artifactId" in artifact
        assert artifact["name"] == "Test Cart"
        assert "parts" in artifact
        assert len(artifact["parts"]) == 1

        # Verify cart mandate in artifact
        part = artifact["parts"][0]
        assert part["kind"] == "data"
        assert "ap2.mandates.CartMandate" in part["data"]

    @pytest.mark.asyncio
    async def test_create_cart_from_products_no_products(self):
        """Test cart creation with empty product list"""
        from services.merchant_agent.services import cart_service

        mock_agent = Mock()

        artifact = await cart_service.create_cart_from_products(
            agent=mock_agent,
            intent_mandate_id="intent_001",
            products=[],  # Empty
            quantities=[],
            shipping_address={},
            cart_name="Empty Cart",
            cart_description="Empty cart"
        )

        # Should return None
        assert artifact is None

    @pytest.mark.asyncio
    async def test_create_cart_from_products_merchant_signature_pending(self):
        """Test cart creation with pending merchant signature"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock cart_helpers
        mock_cart_helpers = Mock()
        mock_cart_helpers.build_cart_items_from_products.return_value = ([], 10000)
        mock_cart_helpers.calculate_cart_costs.return_value = {
            "tax_cents": 1000,
            "shipping_cost_cents": 50000,
            "total_cents": 61000
        }
        mock_agent.cart_helpers = mock_cart_helpers

        # Mock HTTP client - return pending status
        mock_http_client = AsyncMock()

        # First call returns pending
        pending_response = AsyncMock()
        pending_response.status_code = 200
        pending_response.json = AsyncMock(return_value={
            "status": "pending_merchant_signature",
            "cart_mandate_id": "cart_pending_001"
        })
        pending_response.raise_for_status = AsyncMock()

        mock_http_client.post = AsyncMock(return_value=pending_response)
        mock_agent.http_client = mock_http_client

        mock_product = Mock()

        # Mock wait_for_merchant_signature to return signed mandate
        async def mock_wait(agent, cart_mandate_id, cart_name="", timeout=300, poll_interval=2.0):
            return {"contents": {"id": "cart_001"}, "merchant_authorization": "jwt_sig"}

        with patch('services.merchant_agent.services.cart_service.wait_for_merchant_signature',
                  side_effect=mock_wait):

            artifact = await cart_service.create_cart_from_products(
                agent=mock_agent,
                intent_mandate_id="intent_001",
                products=[mock_product],
                quantities=[1],
                shipping_address={},
                cart_name="Pending Cart",
                cart_description="Pending signature"
            )

            # Should return artifact with signed mandate
            assert artifact is not None
            assert "parts" in artifact


class TestWaitForMerchantSignature:
    """Test waiting for merchant signature"""

    @pytest.mark.asyncio
    async def test_wait_for_signature_success(self):
        """Test successful wait for merchant signature"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock HTTP client
        mock_http_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value={
            "status": "signed",
            "payload": {
                "contents": {"id": "cart_001"},
                "merchant_authorization": "jwt_signature"
            }
        })
        mock_response.raise_for_status = AsyncMock()

        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_agent.http_client = mock_http_client

        signed_mandate = await cart_service.wait_for_merchant_signature(
            agent=mock_agent,
            cart_mandate_id="cart_001",
            cart_name="Test Cart",
            timeout=10
        )

        # Verify signed mandate was returned
        assert signed_mandate is not None
        assert signed_mandate["contents"]["id"] == "cart_001"

    @pytest.mark.asyncio
    async def test_wait_for_signature_rejected(self):
        """Test merchant signature rejection"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock HTTP client
        mock_http_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value={
            "status": "rejected",
            "payload": None
        })
        mock_response.raise_for_status = AsyncMock()

        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_agent.http_client = mock_http_client

        signed_mandate = await cart_service.wait_for_merchant_signature(
            agent=mock_agent,
            cart_mandate_id="cart_001",
            timeout=10
        )

        # Should return None
        assert signed_mandate is None

    @pytest.mark.asyncio
    async def test_wait_for_signature_timeout(self):
        """Test merchant signature timeout"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_url = "http://merchant:8002"

        # Mock HTTP client - always return pending
        mock_http_client = AsyncMock()
        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.json = AsyncMock(return_value={
            "status": "pending_merchant_signature"
        })
        mock_response.raise_for_status = AsyncMock()

        mock_http_client.get = AsyncMock(return_value=mock_response)
        mock_agent.http_client = mock_http_client

        signed_mandate = await cart_service.wait_for_merchant_signature(
            agent=mock_agent,
            cart_mandate_id="cart_001",
            timeout=1,  # Short timeout
            poll_interval=0.1
        )

        # Should return None after timeout
        assert signed_mandate is None


class TestCartCostCalculations:
    """Test cart cost calculations"""

    @pytest.mark.asyncio
    async def test_tax_calculation(self):
        """Test tax calculation (10%)"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"

        # Mock database and product
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.id = "product_001"
        mock_product.name = "Test Product"
        mock_product.description = "Test"
        mock_product.price = 10000  # 100 JPY
        mock_product.sku = "SKU001"
        mock_product.image_url = ""
        mock_product.product_metadata = '{}'

        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.get_by_id = AsyncMock(return_value=mock_product)

            cart_request = {
                "intent_mandate_id": "intent_001",
                "items": [{"product_id": "product_001", "quantity": 1}],
                "shipping_address": {}
            }

            cart_mandate = await cart_service.create_cart_mandate(
                agent=mock_agent,
                cart_request=cart_request
            )

            # Verify tax (10% of subtotal)
            tax_value = float(cart_mandate["tax"]["value"])
            subtotal_value = float(cart_mandate["subtotal"]["value"])

            assert tax_value == subtotal_value * 0.1

    @pytest.mark.asyncio
    async def test_shipping_calculation(self):
        """Test shipping cost calculation"""
        from services.merchant_agent.services import cart_service

        # Mock agent
        mock_agent = Mock()
        mock_agent.merchant_id = "merchant_001"
        mock_agent.merchant_name = "Test Merchant"

        # Mock database and product
        mock_session = AsyncMock()
        mock_product = Mock()
        mock_product.id = "product_001"
        mock_product.name = "Test Product"
        mock_product.description = "Test"
        mock_product.price = 10000
        mock_product.sku = "SKU001"
        mock_product.image_url = ""
        mock_product.product_metadata = '{}'

        mock_db_manager = AsyncMock()
        async def mock_get_session():
        class MockContext:
            async def __aenter__(self):
                return mock_session
            async def __aexit__(self, *args):
                pass
        return MockContext()
    mock_db_manager.get_session = mock_get_session
        mock_agent.db_manager = mock_db_manager

        with patch('services.merchant_agent.services.cart_service.ProductCRUD') as mock_crud:
            mock_crud.get_by_id = AsyncMock(return_value=mock_product)

            cart_request = {
                "intent_mandate_id": "intent_001",
                "items": [{"product_id": "product_001", "quantity": 1}],
                "shipping_address": {}
            }

            cart_mandate = await cart_service.create_cart_mandate(
                agent=mock_agent,
                cart_request=cart_request
            )

            # Verify shipping cost (500 JPY)
            shipping_value = float(cart_mandate["shipping"]["cost"]["value"])
            assert shipping_value == 500.0
