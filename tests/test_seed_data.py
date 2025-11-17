"""
Tests for Seed Data Module

Tests cover:
- SAMPLE_PRODUCTS data structure
- SAMPLE_USERS data structure
- SAMPLE_PAYMENT_METHODS data structure
- Data validation
"""

import pytest


class TestSampleProducts:
    """Test SAMPLE_PRODUCTS data"""

    def test_sample_products_defined(self):
        """Test that SAMPLE_PRODUCTS is defined"""
        from common.seed_data import SAMPLE_PRODUCTS

        # Should have products
        assert isinstance(SAMPLE_PRODUCTS, list)
        assert len(SAMPLE_PRODUCTS) > 0

    def test_product_structure(self):
        """Test that each product has required fields"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            # Validate required fields
            assert 'sku' in product
            assert 'name' in product
            assert 'description' in product
            assert 'price' in product
            assert 'inventory_count' in product
            assert 'image_url' in product
            assert 'metadata' in product

    def test_product_sku_format(self):
        """Test that SKUs follow expected format"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            # SKU should be a string
            assert isinstance(product['sku'], str)
            assert len(product['sku']) > 0

    def test_product_price_valid(self):
        """Test that prices are positive integers"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            # Price should be positive integer (in smallest currency unit)
            assert isinstance(product['price'], int)
            assert product['price'] > 0

    def test_product_inventory_valid(self):
        """Test that inventory counts are non-negative"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            # Inventory should be non-negative integer
            assert isinstance(product['inventory_count'], int)
            assert product['inventory_count'] >= 0

    def test_product_metadata_structure(self):
        """Test that metadata is a dictionary"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            # Metadata should be a dict
            assert isinstance(product['metadata'], dict)

    def test_product_names_are_unique(self):
        """Test that product names are unique"""
        from common.seed_data import SAMPLE_PRODUCTS

        names = [p['name'] for p in SAMPLE_PRODUCTS]

        # All names should be unique
        assert len(names) == len(set(names))

    def test_product_skus_are_unique(self):
        """Test that SKUs are unique"""
        from common.seed_data import SAMPLE_PRODUCTS

        skus = [p['sku'] for p in SAMPLE_PRODUCTS]

        # All SKUs should be unique
        assert len(skus) == len(set(skus))


class TestSampleUsers:
    """Test SAMPLE_USERS data"""

    def test_sample_users_defined(self):
        """Test that SAMPLE_USERS is defined"""
        from common.seed_data import SAMPLE_USERS

        # Should have users
        assert isinstance(SAMPLE_USERS, list)
        assert len(SAMPLE_USERS) > 0

    def test_user_structure(self):
        """Test that each user has required fields"""
        from common.seed_data import SAMPLE_USERS

        for user in SAMPLE_USERS:
            # Validate required fields
            assert 'id' in user
            assert 'display_name' in user
            assert 'email' in user

    def test_user_id_format(self):
        """Test that user IDs follow expected format"""
        from common.seed_data import SAMPLE_USERS

        for user in SAMPLE_USERS:
            # User ID should be a string
            assert isinstance(user['id'], str)
            assert len(user['id']) > 0

    def test_user_email_format(self):
        """Test that emails contain @ symbol"""
        from common.seed_data import SAMPLE_USERS

        for user in SAMPLE_USERS:
            # Email should contain @
            assert '@' in user['email']

    def test_user_ids_are_unique(self):
        """Test that user IDs are unique"""
        from common.seed_data import SAMPLE_USERS

        user_ids = [u['id'] for u in SAMPLE_USERS]

        # All user IDs should be unique
        assert len(user_ids) == len(set(user_ids))

    def test_user_emails_are_unique(self):
        """Test that emails are unique"""
        from common.seed_data import SAMPLE_USERS

        emails = [u['email'] for u in SAMPLE_USERS]

        # All emails should be unique
        assert len(emails) == len(set(emails))


class TestSamplePaymentMethods:
    """Test SAMPLE_PAYMENT_METHODS data"""

    def test_sample_payment_methods_defined(self):
        """Test that SAMPLE_PAYMENT_METHODS is defined"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        # Should have payment methods
        assert isinstance(SAMPLE_PAYMENT_METHODS, list)
        assert len(SAMPLE_PAYMENT_METHODS) > 0

    def test_payment_method_structure(self):
        """Test that each payment method has required fields"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            # Validate required fields
            assert 'id' in pm
            assert 'user_id' in pm
            assert 'payment_method' in pm

    def test_payment_method_details_structure(self):
        """Test that payment_method details have required fields"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            pm_details = pm['payment_method']

            # Validate payment method details
            assert 'type' in pm_details
            assert 'display_name' in pm_details
            assert 'card_last4' in pm_details
            assert 'card_brand' in pm_details
            assert 'billing_address' in pm_details
            assert 'requires_step_up' in pm_details

    def test_payment_method_type_format(self):
        """Test that type follows AP2 protocol"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            pm_type = pm['payment_method']['type']

            # Should be AP2 payment method type
            assert pm_type == 'https://a2a-protocol.org/payment-methods/ap2-payment'

    def test_payment_method_card_brands(self):
        """Test that card brands are valid"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        valid_brands = ['Visa', 'Amex', 'JCB', 'Mastercard']

        for pm in SAMPLE_PAYMENT_METHODS:
            card_brand = pm['payment_method']['card_brand']

            # Should be a valid card brand
            assert card_brand in valid_brands

    def test_payment_method_last4_format(self):
        """Test that card_last4 is 4 characters"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            last4 = pm['payment_method']['card_last4']

            # Should be 4 characters
            assert len(last4) == 4
            assert last4.isdigit()

    def test_payment_method_requires_step_up(self):
        """Test that requires_step_up is boolean"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            requires_step_up = pm['payment_method']['requires_step_up']

            # Should be boolean
            assert isinstance(requires_step_up, bool)

    def test_payment_method_ids_are_unique(self):
        """Test that payment method IDs are unique"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        pm_ids = [pm['id'] for pm in SAMPLE_PAYMENT_METHODS]

        # All IDs should be unique
        assert len(pm_ids) == len(set(pm_ids))

    def test_payment_method_billing_address_structure(self):
        """Test that billing address has required fields"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        for pm in SAMPLE_PAYMENT_METHODS:
            billing_address = pm['payment_method']['billing_address']

            # Validate billing address
            assert 'country' in billing_address
            assert 'postal_code' in billing_address

    def test_step_up_payment_methods_exist(self):
        """Test that at least one payment method requires step-up"""
        from common.seed_data import SAMPLE_PAYMENT_METHODS

        step_up_methods = [
            pm for pm in SAMPLE_PAYMENT_METHODS
            if pm['payment_method']['requires_step_up']
        ]

        # Should have at least one step-up method
        assert len(step_up_methods) > 0


class TestDataConsistency:
    """Test data consistency across collections"""

    def test_payment_methods_reference_valid_users(self):
        """Test that payment methods reference existing users"""
        from common.seed_data import SAMPLE_USERS, SAMPLE_PAYMENT_METHODS

        user_ids = {u['id'] for u in SAMPLE_USERS}

        for pm in SAMPLE_PAYMENT_METHODS:
            user_id = pm['user_id']

            # User ID should reference an existing user
            assert user_id in user_ids


class TestProductCategories:
    """Test product metadata and categories"""

    def test_products_have_categories(self):
        """Test that products have category in metadata"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            metadata = product['metadata']

            # Should have category
            assert 'category' in metadata

    def test_products_have_brands(self):
        """Test that products have brand in metadata"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            metadata = product['metadata']

            # Should have brand
            assert 'brand' in metadata


class TestProductPricing:
    """Test product pricing consistency"""

    def test_price_in_smallest_unit(self):
        """Test that prices are in smallest currency unit (e.g., yen)"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            price = product['price']

            # Price should be in smallest unit (yen for JPY)
            # All prices should be divisible by 100 for display purposes
            # (e.g., 80000 yen = ¥800)
            assert price >= 1000  # At least ¥10


class TestImageUrls:
    """Test image URL consistency"""

    def test_image_urls_start_with_slash(self):
        """Test that image URLs start with /"""
        from common.seed_data import SAMPLE_PRODUCTS

        for product in SAMPLE_PRODUCTS:
            image_url = product['image_url']

            # Image URLs should start with /
            assert image_url.startswith('/')

    def test_image_urls_have_extension(self):
        """Test that image URLs have file extension"""
        from common.seed_data import SAMPLE_PRODUCTS

        valid_extensions = ['.png', '.jpg', '.jpeg', '.webp']

        for product in SAMPLE_PRODUCTS:
            image_url = product['image_url']

            # Should have a valid image extension
            assert any(image_url.endswith(ext) for ext in valid_extensions)
