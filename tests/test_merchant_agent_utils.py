"""
Tests for Merchant Agent Utils Helpers

Tests cover:
- cart_helpers.py (merchant_agent)
- llm_utils.py (merchant_agent)
- cart_mandate_helpers.py (merchant_agent_mcp)
- product_helpers.py (merchant_agent_mcp)
"""

import pytest
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch


# ============================================================================
# Merchant Agent Cart Helpers Tests
# ============================================================================


class TestMerchantAgentCartHelpers:
    """Test merchant_agent cart helpers"""

    def test_build_cart_items_from_products(self):
        """Test building cart items from products"""
        from services.merchant_agent.utils.cart_helpers import CartHelpers

        # Create mock products
        product1 = Mock()
        product1.name = "Test Product 1"
        product1.description = "Description 1"
        product1.price = 10000  # 10000 cents = 100 JPY
        product1.sku = "SKU-001"
        product1.image_url = "/images/test1.png"
        product1.product_metadata = json.dumps({"category": "test", "brand": "test_brand"})

        product2 = Mock()
        product2.name = "Test Product 2"
        product2.description = "Description 2"
        product2.price = 20000  # 20000 cents = 200 JPY
        product2.sku = "SKU-002"
        product2.image_url = "/images/test2.png"
        product2.product_metadata = None

        products = [product1, product2]
        quantities = [2, 1]

        cart_items, subtotal_cents = CartHelpers.build_cart_items_from_products(products, quantities)

        # Verify cart items
        assert len(cart_items) == 2

        # Check first item
        assert cart_items[0]["name"] == "Test Product 1"
        assert cart_items[0]["quantity"] == 2
        assert cart_items[0]["unit_price"]["value"] == 100.0  # 10000 cents / 100
        assert cart_items[0]["total_price"]["value"] == 200.0  # 100 * 2
        assert cart_items[0]["category"] == "test"
        assert cart_items[0]["brand"] == "test_brand"

        # Check second item
        assert cart_items[1]["name"] == "Test Product 2"
        assert cart_items[1]["quantity"] == 1
        assert cart_items[1]["unit_price"]["value"] == 200.0
        assert cart_items[1]["total_price"]["value"] == 200.0

        # Check subtotal (200 + 200 = 400 JPY = 40000 cents)
        assert subtotal_cents == 40000

    def test_calculate_cart_costs(self):
        """Test cart cost calculation"""
        from services.merchant_agent.utils.cart_helpers import CartHelpers

        subtotal_cents = 100000  # 1000 JPY

        costs = CartHelpers.calculate_cart_costs(subtotal_cents)

        # Verify tax (10%)
        assert costs["tax_cents"] == 10000  # 100 JPY

        # Verify shipping (fixed 500 JPY)
        assert costs["shipping_cost_cents"] == 50000  # 500 JPY

        # Verify total
        assert costs["total_cents"] == 160000  # 1000 + 100 + 500 = 1600 JPY


# ============================================================================
# Merchant Agent LLM Utils Tests
# ============================================================================


class TestMerchantAgentLLMUtils:
    """Test merchant_agent LLM utilities"""

    def test_extract_keywords_simple_basic(self):
        """Test basic keyword extraction"""
        from services.merchant_agent.utils.llm_utils import extract_keywords_simple

        text = "かわいいグッズを購入したい"
        keywords = extract_keywords_simple(text)

        # Keywords are extracted (compound words or individual words)
        assert len(keywords) > 0
        # 「を」などの助詞は除外される
        assert "を" not in keywords

    def test_extract_keywords_simple_with_parentheses(self):
        """Test keyword extraction with parentheses"""
        from services.merchant_agent.utils.llm_utils import extract_keywords_simple

        text = "グッズを買いたい（カテゴリ・ブランド指定なし）"
        keywords = extract_keywords_simple(text)

        # カッコ内は削除される
        assert "カテゴリ" not in keywords
        assert "ブランド" not in keywords
        # 「グッズ」は残る
        assert "グッズ" in keywords

    def test_extract_keywords_simple_empty_text(self):
        """Test keyword extraction with empty text"""
        from services.merchant_agent.utils.llm_utils import extract_keywords_simple

        keywords = extract_keywords_simple("")
        assert keywords == []

    def test_extract_keywords_simple_no_keywords(self):
        """Test keyword extraction when no keywords found"""
        from services.merchant_agent.utils.llm_utils import extract_keywords_simple

        # 助詞や記号のみのテキスト
        text = "を、が、に"
        keywords = extract_keywords_simple(text)

        # キーワードが抽出できない場合は空文字列で全商品検索
        assert keywords == [""]

    def test_parse_json_from_llm_with_code_block(self):
        """Test JSON parsing from LLM with code block"""
        from services.merchant_agent.utils.llm_utils import parse_json_from_llm

        text = """```json
{
    "key": "value",
    "number": 123
}
```"""
        result = parse_json_from_llm(text)

        assert result is not None
        assert result["key"] == "value"
        assert result["number"] == 123

    def test_parse_json_from_llm_with_plain_json(self):
        """Test JSON parsing from plain JSON"""
        from services.merchant_agent.utils.llm_utils import parse_json_from_llm

        text = '{"key": "value", "list": [1, 2, 3]}'
        result = parse_json_from_llm(text)

        assert result is not None
        assert result["key"] == "value"
        assert result["list"] == [1, 2, 3]

    def test_parse_json_from_llm_invalid_json(self):
        """Test JSON parsing with invalid JSON"""
        from services.merchant_agent.utils.llm_utils import parse_json_from_llm

        text = "This is not JSON"
        result = parse_json_from_llm(text)

        # パース失敗時はNoneを返す
        assert result is None

    def test_parse_json_from_llm_array(self):
        """Test JSON parsing with array"""
        from services.merchant_agent.utils.llm_utils import parse_json_from_llm

        text = '```[{"id": 1}, {"id": 2}]```'
        result = parse_json_from_llm(text)

        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["id"] == 1


# ============================================================================
# Merchant Agent MCP Cart Mandate Helpers Tests
# ============================================================================


class TestCartMandateHelpers:
    """Test merchant_agent_mcp cart mandate helpers"""

    def test_init(self):
        """Test CartMandateHelpers initialization"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        assert helpers.merchant_id == "merchant_001"
        assert helpers.merchant_name == "Test Merchant"
        assert helpers.shipping_fee == 500.0
        assert helpers.tax_rate == 0.1

    def test_build_cart_items(self):
        """Test building cart items"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        cart_plan = {
            "items": [
                {"product_id": 1, "quantity": 2},
                {"product_id": 2, "quantity": 1}
            ]
        }

        products_map = {
            1: {
                "name": "Product 1",
                "description": "Description 1",
                "price_jpy": 1000.0,
                "image_url": "/img1.png"
            },
            2: {
                "name": "Product 2",
                "description": "Description 2",
                "price_jpy": 2000.0,
                "image_url": "/img2.png",
                "refund_period_days": 60
            }
        }

        display_items, raw_items, subtotal = helpers.build_cart_items(cart_plan, products_map)

        # Verify display items
        assert len(display_items) == 2
        assert display_items[0]["label"] == "Product 1"
        assert display_items[0]["amount"]["value"] == 2000.0  # 1000 * 2
        assert display_items[1]["refund_period"] == 60 * 86400

        # Verify raw items
        assert len(raw_items) == 2
        assert raw_items[0]["quantity"] == 2
        assert raw_items[0]["total_price"]["value"] == 2000.0

        # Verify subtotal
        assert subtotal == 4000.0  # 2000 + 2000

    def test_calculate_tax(self):
        """Test tax calculation"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        tax, tax_label = helpers.calculate_tax(10000.0)

        assert tax == 1000.0
        assert "10%" in tax_label

    def test_calculate_shipping_fee_with_fee(self):
        """Test shipping fee calculation when below threshold"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        # Below threshold
        shipping = helpers.calculate_shipping_fee(3000.0)
        assert shipping == 500.0

    def test_calculate_shipping_fee_free(self):
        """Test shipping fee calculation when above threshold"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        # Above threshold
        shipping = helpers.calculate_shipping_fee(6000.0)
        assert shipping == 0.0

    def test_build_cart_mandate_structure(self):
        """Test building cart mandate structure"""
        from services.merchant_agent_mcp.utils.cart_mandate_helpers import CartMandateHelpers

        helpers = CartMandateHelpers(
            merchant_id="merchant_001",
            merchant_name="Test Merchant",
            merchant_url="https://test.example.com",
            shipping_fee=500.0,
            free_shipping_threshold=5000.0,
            tax_rate=0.1
        )

        display_items = [
            {
                "label": "Test Item",
                "amount": {"value": 1000.0, "currency": "JPY"}
            }
        ]

        raw_items = [
            {
                "product_id": 1,
                "name": "Test Item",
                "quantity": 1,
                "unit_price": {"value": 1000.0, "currency": "JPY"}
            }
        ]

        shipping_address = {
            "recipient": "Test User",
            "postal_code": "100-0001",
            "address_line1": "Test Address"
        }

        session_data = {
            "intent_mandate_id": "intent_123",
            "cart_name": "Test Cart"
        }

        cart_mandate = helpers.build_cart_mandate_structure(
            display_items, raw_items, 1000.0, shipping_address, session_data
        )

        # Verify structure
        assert "contents" in cart_mandate
        assert "payment_request" in cart_mandate["contents"]
        assert cart_mandate["contents"]["merchant_name"] == "Test Merchant"
        assert cart_mandate["_metadata"]["merchant_id"] == "merchant_001"
        assert cart_mandate["_metadata"]["intent_mandate_id"] == "intent_123"

        # Verify payment request
        payment_request = cart_mandate["contents"]["payment_request"]
        assert len(payment_request["method_data"]) > 0
        assert "options" in payment_request
        assert payment_request["details"]["total"]["amount"]["value"] == 1000.0


# ============================================================================
# Merchant Agent MCP Product Helpers Tests
# ============================================================================


class TestMerchantAgentProductHelpers:
    """Test merchant_agent product helpers"""

    @pytest.mark.asyncio
    async def test_sync_products_to_meilisearch(self):
        """Test syncing products to Meilisearch"""
        from services.merchant_agent.utils.product_helpers import ProductHelpers
        from datetime import datetime, timezone

        # Mock dependencies
        db_manager = Mock()
        search_client = Mock()

        # Mock async methods
        search_client.create_index = Mock(return_value=None)
        search_client.configure_index = Mock(return_value=None)
        search_client.clear_index = Mock(return_value=None)
        search_client.add_documents = Mock(return_value=None)

        # Make them awaitable
        async def async_return(value=None):
            return value

        search_client.create_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.configure_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.clear_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.add_documents = Mock(side_effect=lambda docs: async_return())

        # Create mock products
        product1 = Mock()
        product1.id = 1
        product1.name = "Test Product 1"
        product1.description = "Description 1"
        product1.price = 10000  # cents
        product1.metadata = {"category": "test_cat", "brand": "test_brand"}
        product1.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        product2 = Mock()
        product2.id = 2
        product2.name = "Test Product 2"
        product2.description = None
        product2.price = 20000
        product2.metadata = None
        product2.created_at = None

        # Mock session and CRUD
        mock_session = Mock()

        async def aenter(self):
            return mock_session

        async def aexit(self, *args):
            return None

        mock_session.__aenter__ = aenter
        mock_session.__aexit__ = aexit

        db_manager.get_session = Mock(return_value=mock_session)

        # Mock ProductCRUD
        with patch('common.database.ProductCRUD') as MockProductCRUD:
            async def mock_list_all(session, limit):
                return [product1, product2]

            MockProductCRUD.list_all = mock_list_all

            # Test sync
            helpers = ProductHelpers(db_manager)
            await helpers.sync_products_to_meilisearch(search_client)

            # Verify search client methods were called
            search_client.create_index.assert_called_once()
            search_client.configure_index.assert_called_once()
            search_client.clear_index.assert_called_once()
            search_client.add_documents.assert_called_once()

            # Verify documents structure
            call_args = search_client.add_documents.call_args[0][0]
            assert len(call_args) == 2
            assert call_args[0]["id"] == 1
            assert call_args[0]["name"] == "Test Product 1"
            assert call_args[0]["price_jpy"] == 100.0
            assert call_args[0]["category"] == "test_cat"
            assert call_args[1]["description"] == ""  # None converted to ""

    @pytest.mark.asyncio
    async def test_sync_products_to_meilisearch_with_sqlalchemy_metadata(self):
        """Test syncing products with SQLAlchemy MetaData object"""
        from services.merchant_agent.utils.product_helpers import ProductHelpers

        db_manager = Mock()
        search_client = Mock()

        # Mock async methods
        async def async_return(value=None):
            return value

        search_client.create_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.configure_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.clear_index = Mock(side_effect=lambda **kwargs: async_return())
        search_client.add_documents = Mock(side_effect=lambda docs: async_return())

        # Create mock product with SQLAlchemy MetaData
        product = Mock()
        product.id = 1
        product.name = "Test"
        product.description = "Desc"
        product.price = 10000
        product.created_at = None

        # Mock SQLAlchemy MetaData
        metadata_mock = Mock()
        metadata_mock.__class__.__name__ = "MetaData"
        product.metadata = metadata_mock

        # Mock session
        mock_session = Mock()
        async def aenter(self):
            return mock_session
        async def aexit(self, *args):
            return None
        mock_session.__aenter__ = aenter
        mock_session.__aexit__ = aexit
        db_manager.get_session = Mock(return_value=mock_session)

        with patch('common.database.ProductCRUD') as MockProductCRUD:
            async def mock_list_all(session, limit):
                return [product]
            MockProductCRUD.list_all = mock_list_all

            helpers = ProductHelpers(db_manager)
            await helpers.sync_products_to_meilisearch(search_client)

            # Verify documents - category/brand should be empty for SQLAlchemy metadata
            call_args = search_client.add_documents.call_args[0][0]
            assert call_args[0]["category"] == ""
            assert call_args[0]["brand"] == ""

    @pytest.mark.asyncio
    async def test_sync_products_to_meilisearch_error_handling(self):
        """Test error handling in sync_products_to_meilisearch"""
        from services.merchant_agent.utils.product_helpers import ProductHelpers

        db_manager = Mock()
        search_client = Mock()

        # Make create_index raise an exception
        async def raise_error(**kwargs):
            raise Exception("Meilisearch error")

        search_client.create_index = Mock(side_effect=raise_error)

        helpers = ProductHelpers(db_manager)

        # Should not raise, just log the error
        await helpers.sync_products_to_meilisearch(search_client)

        # Verify create_index was called
        search_client.create_index.assert_called_once()


# ============================================================================
# Merchant Agent MCP Product Helpers Tests (from merchant_agent_mcp)
# ============================================================================


class TestProductHelpers:
    """Test merchant_agent_mcp product helpers"""

    def test_map_product_to_dict(self):
        """Test mapping product to dict"""
        from services.merchant_agent_mcp.utils.product_helpers import ProductHelpers

        # Create mock product
        product = Mock()
        product.id = 1
        product.sku = "SKU-001"
        product.name = "Test Product"
        product.description = "Test Description"
        product.price = 10000  # cents
        product.inventory_count = 50
        product.image_url = "/test.png"
        product.metadata = {"category": "test", "brand": "test_brand", "refund_period_days": 60}

        product_dict = ProductHelpers.map_product_to_dict(product)

        assert product_dict["id"] == 1
        assert product_dict["sku"] == "SKU-001"
        assert product_dict["name"] == "Test Product"
        assert product_dict["price_cents"] == 10000
        assert product_dict["price_jpy"] == 100.0  # 10000 / 100
        assert product_dict["category"] == "test"
        assert product_dict["brand"] == "test_brand"
        assert product_dict["refund_period_days"] == 60

    def test_map_product_to_dict_with_sqlalchemy_metadata(self):
        """Test mapping product with SQLAlchemy MetaData object"""
        from services.merchant_agent_mcp.utils.product_helpers import ProductHelpers

        # Create mock product with SQLAlchemy MetaData
        product = Mock()
        product.id = 1
        product.sku = "SKU-002"
        product.name = "Test Product 2"
        product.description = "Description 2"
        product.price = 20000
        product.inventory_count = 100
        product.image_url = "/test2.png"

        # Mock SQLAlchemy MetaData object
        metadata_mock = Mock()
        metadata_mock.__class__.__name__ = "MetaData"
        product.metadata = metadata_mock

        product_dict = ProductHelpers.map_product_to_dict(product)

        assert product_dict["id"] == 1
        assert product_dict["price_jpy"] == 200.0
        # Metadata should be empty dict
        assert product_dict["category"] is None
        assert product_dict["brand"] is None
        assert product_dict["refund_period_days"] == 30  # default

    def test_map_products_to_list(self):
        """Test mapping products list"""
        from services.merchant_agent_mcp.utils.product_helpers import ProductHelpers

        # Create mock products
        product1 = Mock()
        product1.id = 1
        product1.sku = "SKU-001"
        product1.name = "Product 1"
        product1.description = "Desc 1"
        product1.price = 10000
        product1.inventory_count = 10
        product1.image_url = "/img1.png"
        product1.metadata = {}

        product2 = Mock()
        product2.id = 2
        product2.sku = "SKU-002"
        product2.name = "Product 2"
        product2.description = "Desc 2"
        product2.price = 20000
        product2.inventory_count = 0  # Out of stock
        product2.image_url = "/img2.png"
        product2.metadata = {}

        product3 = Mock()
        product3.id = 3
        product3.sku = "SKU-003"
        product3.name = "Product 3"
        product3.description = "Desc 3"
        product3.price = 30000
        product3.inventory_count = 5
        product3.image_url = "/img3.png"
        product3.metadata = {}

        products = [product1, product2, product3]
        products_list = ProductHelpers.map_products_to_list(products)

        # Only products with inventory > 0 should be included
        assert len(products_list) == 2
        assert products_list[0]["id"] == 1
        assert products_list[1]["id"] == 3
        # product2 (out of stock) should be skipped

    def test_map_products_to_list_empty(self):
        """Test mapping empty products list"""
        from services.merchant_agent_mcp.utils.product_helpers import ProductHelpers

        products_list = ProductHelpers.map_products_to_list([])
        assert products_list == []
